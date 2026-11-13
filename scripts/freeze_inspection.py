#!/usr/bin/env python3
"""Freeze the selected inspection detector and normal-only operating point before QA."""

from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "src/meshlens/texture_detector.py",
    "src/meshlens/inspection_input.py",
    "web/texture_detector.js",
    "web/inspection_input.js",
)
CONDITIONS = (
    "original",
    "brightness_070",
    "brightness_130",
    "shift_8x4_ref256",
    "blur_sigma_0p8_ref256",
    "jpeg_quality_75",
)
FREEZE_PATH = "reports/inspection/frozen_configuration.json"
FROZEN_FILES = (
    "artifacts/inspection/detector-model.json",
    "artifacts/inspection/detector.json",
    "artifacts/inspection/calibration.json",
    "reports/inspection/selection.json",
    "reports/inspection/protocol.json",
    "data/manifest.csv",
)


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def encode(value) -> bytes:
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode("utf-8")


def load(path: Path):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"Duplicate JSON field: {key}")
            value[key] = item
        return value

    def invalid(value):
        raise ValueError(f"Nonfinite JSON number: {value}")

    return json.loads(
        path.read_bytes(), object_pairs_hook=pairs, parse_constant=invalid
    )


def manifest_rows(root: Path) -> list[dict]:
    with (root / "data/manifest.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if (
        len(rows) != 342
        or len({r["path"] for r in rows}) != 342
        or len({r["sha256"] for r in rows}) != 342
    ):
        raise ValueError(
            "The fixed dataset manifest must contain342 unique source images"
        )
    counts = {
        split: sum(r["split"] == split for r in rows)
        for split in ("fit", "tune", "calibration", "test")
    }
    if counts != dict(fit=160, tune=52, calibration=52, test=78):
        raise ValueError("Dataset partitions differ from the planned160/52/52/78 split")
    if any(r["label"] != "0" for r in rows if r["split"] != "test"):
        raise ValueError("Only normal images can enter development or calibration")
    if sum(r["label"] == "1" for r in rows if r["split"] == "test") != 57:
        raise ValueError("Official test must contain57 defects and21 normals")
    return rows


def validate_calibration(root: Path, model: dict, scores: list[dict]) -> None:
    rows = {r["path"]: r for r in manifest_rows(root) if r["split"] == "calibration"}
    if (
        not isinstance(scores, list)
        or len(scores) != 52
        or {r.get("path") for r in scores} != set(rows)
    ):
        raise ValueError(
            "Calibration must contain exactly the reserved52 normal images"
        )
    values = []
    for item in scores:
        if (
            item.get("sha256") != rows[item["path"]]["sha256"]
            or item.get("label", 0) != 0
        ):
            raise ValueError("Calibration image provenance or normal label differs")
        score = item.get("score")
        if (
            type(score) not in (int, float)
            or not math.isfinite(score)
            or score < 0
            or round(score, 8) != score
        ):
            raise ValueError(
                "Calibration scores must be finite, nonnegative and quantized to8 decimals"
            )
        values.append(score)
    if sorted(values)[50] != model["threshold"]:
        raise ValueError(
            "Threshold must be the frozen normal order statistic at rank51"
        )
    if model["calibration"] != {
        "count": 52,
        "alpha": 0.05,
        "strict_greater_than": True,
    }:
        raise ValueError("Unexpected calibration policy")


def protocol() -> dict:
    return {
        "schema_version": 1,
        "dataset": "MVTec AD grid",
        "test_images": 78,
        "test_normal": 21,
        "test_defect": 57,
        "records_expected": 468,
        "selection_used_test": False,
        "calibration_used_test": False,
        "decision_rule": "score > threshold",
        "score_decimals": 8,
        "conditions": list(CONDITIONS),
        "transforms": {
            "original": "Decoded source image; no transform",
            "brightness_070": "Pillow ImageEnhance.Brightness factor0.70 before canonical preprocessing",
            "brightness_130": "Pillow ImageEnhance.Brightness factor1.30 before canonical preprocessing",
            "shift_8x4_ref256": "Reflect pad dx=round(width*8/256),dy=round(height*4/256), then take firstH x W pixels",
            "blur_sigma_0p8_ref256": "Pillow GaussianBlur radius0.8*min(width,height)/256",
            "jpeg_quality_75": "Pillow JPEG quality75,subsampling2,decodeRGB",
        },
        "unusable_policy": "Unusable defects count as misses; unusable clean images are not correct negatives and are reported separately.",
        "interval_method": "two-sided Wilson95%",
        "benchmark_reuse": True,
        "prior_evaluation_known": True,
        "new_blind_validation": False,
        "algorithm_changed_after_prior_test": False,
        "recovery_context": "Recovery/reproducibility run of the same previously frozen A256joint detector. Prior56/57 defect alerts and4/21 clean alerts were already known from lost evidence files. No architecture, score or threshold tuning is performed in this recovery run.",
        "qualification": "Public benchmark re-evaluation, not an independent target-line or unseen field cohort.",
    }


def put_same(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(
                f"Existing frozen input differs: {path}; create a separate release rather than overwrite it"
            )
    else:
        with path.open("xb") as stream:
            stream.write(content)


def prepare_inputs(root: Path) -> None:
    model_bytes = (root / "artifacts/texture/texture-model.json").read_bytes()
    model = json.loads(model_bytes)
    scores_bytes = (root / "reports/texture/calibration-scores.json").read_bytes()
    selection_bytes = (root / "reports/texture/frozen-candidate.json").read_bytes()
    selected = json.loads(selection_bytes)
    if (
        model.get("kind") != "normal-lattice-v1"
        or model.get("image_size") != 256
        or model.get("variant") != "joint"
        or model.get("tail_fraction") != 0.005
        or model.get("score_decimals") != 8
        or model.get("threshold") != 1.01049636
        or model.get("frozen_candidate_sha256") != digest(selection_bytes)
        or model.get("implementation_sha256")
        != digest((root / SOURCES[0]).read_bytes())
        or model.get("preprocessing_sha256") != digest((root / SOURCES[1]).read_bytes())
        or selected.get("fit_count") != 160
        or selected.get("tune_clean_count") != 52
        or model.get("data_manifest_sha256")
        != digest((root / "data/manifest.csv").read_bytes())
    ):
        raise ValueError(
            "The selected A256 joint detector differs from its frozen development contract"
        )
    validate_calibration(root, model, json.loads(scores_bytes))
    model_hash = digest(model_bytes)
    metadata = {
        "schema_version": 1,
        "name": "MeshLens repeat-based mesh inspection detector",
        "model_version": "meshlens-inspect-" + model_hash[:12],
        "runtime": "texture-js",
        "image_size": 256,
        "preprocessing": "area-rgb8-v1",
        "threshold": model["threshold"],
        "decision": "strict-greater-than",
        "decision_rule": "score > threshold",
        "score_decimals": 8,
        "score_is_probability": False,
        "variant": model["variant"],
        "tail_fraction": model["tail_fraction"],
        "export": {
            "model_file": "detector-model.json",
            "model_sha256": model_hash,
            "model_bytes": len(model_bytes),
        },
        "outputs": {"score_name": "score", "map_name": "anomaly_map", "map_size": 256},
        "input_quality": {
            "min_side": 256,
            "max_aspect_ratio": 1.5,
            "min_repeat_directions": 2,
        },
        "calibration": {
            "count": 52,
            "alpha": 0.05,
            "order_statistic_rank": 51,
            "strict_greater_than": True,
            "scores_sha256": digest(scores_bytes),
        },
        "dataset": {
            "name": "MVTec AD",
            "category": "grid",
            "fit": 160,
            "tune": 52,
            "calibration": 52,
            "test": 78,
            "manifest_sha256": model["data_manifest_sha256"],
            "development_manifest_sha256": model["development_manifest_sha256"],
            "license": "CC-BY-NC-SA-4.0",
        },
        "qualification": {
            "status": "benchmark_only",
            "automated_line_inspection_qualified": False,
            "independent_target_line_qualified": False,
        },
        "owner": {"name": "Kumar Waibhav AKshat", "email": "kwa.waibhav@gmail.com"},
    }
    for path, content in [
        ("artifacts/inspection/detector-model.json", model_bytes),
        ("artifacts/inspection/calibration.json", scores_bytes),
        ("artifacts/inspection/detector.json", encode(metadata)),
        ("reports/inspection/selection.json", selection_bytes),
        ("reports/inspection/protocol.json", encode(protocol())),
    ]:
        put_same(root / path, content)


def verify_freeze(root: Path) -> dict:
    frozen = load(root / FREEZE_PATH)
    if frozen.get("schema_version") != 1 or set(frozen.get("files", {})) != set(
        FROZEN_FILES + SOURCES
    ):
        raise ValueError("Unexpected freeze schema or missing bound numerical sources")
    for relative, expected in frozen["files"].items():
        content = (root / relative).read_bytes()
        if expected != {"sha256": digest(content), "bytes": len(content)}:
            raise ValueError(f"Frozen source/artifact SHA256 mismatch: {relative}")
    model = load(root / "artifacts/inspection/detector-model.json")
    metadata = load(root / "artifacts/inspection/detector.json")
    validate_calibration(
        root, model, load(root / "artifacts/inspection/calibration.json")
    )
    if (
        metadata["threshold"] != model["threshold"]
        or frozen["threshold"] != model["threshold"]
        or metadata["model_version"] != frozen["model_version"]
        or frozen["decision_rule"] != "score > threshold"
        or frozen["calibration"]["order_statistic_rank"] != 51
    ):
        raise ValueError(
            "Freeze model identity, threshold or calibration contract differs"
        )
    return frozen


def create_freeze(root: Path = ROOT) -> dict:
    prepare_inputs(root)
    if (root / FREEZE_PATH).exists():
        verify_freeze(root)
    else:
        metadata = load(root / "artifacts/inspection/detector.json")
        frozen = {
            "schema_version": 1,
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "model_version": metadata["model_version"],
            "model_sha256": metadata["export"]["model_sha256"],
            "threshold": metadata["threshold"],
            "decision_rule": "score > threshold",
            "score_decimals": 8,
            "calibration": metadata["calibration"],
            "selection_used_test": False,
            "files": {
                name: {
                    "sha256": digest((root / name).read_bytes()),
                    "bytes": (root / name).stat().st_size,
                }
                for name in FROZEN_FILES + SOURCES
            },
            "qualification": {
                "status": "benchmark_only",
                "automated_line_inspection_qualified": False,
            },
        }
        put_same(root / FREEZE_PATH, encode(frozen))
        verify_freeze(root)
    return {
        "path": FREEZE_PATH,
        "sha256": digest((root / FREEZE_PATH).read_bytes()),
        **load(root / FREEZE_PATH),
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--check", action="store_true", help="Verify an existing freeze without writing"
    )
    args = parser.parse_args(argv)
    try:
        result = verify_freeze(args.root) if args.check else create_freeze(args.root)
        print(
            json.dumps(
                {
                    "freeze_sha256": digest((args.root / FREEZE_PATH).read_bytes()),
                    "model_version": result["model_version"],
                },
                indent=2,
            )
        )
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
