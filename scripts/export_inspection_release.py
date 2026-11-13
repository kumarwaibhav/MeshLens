#!/usr/bin/env python3
"""Derive the public inspection release from hash-bound independent raw records."""

# ruff: noqa: E402 -- Bootstrap the repository before importing its release helpers.
from __future__ import annotations
import argparse
from datetime import datetime
import io
import json
import math
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from scripts.freeze_inspection import (
    CONDITIONS,
    FREEZE_PATH,
    digest,
    encode,
    load,
    manifest_rows,
    verify_freeze,
)

RAW_PATH = "reports/inspection/independent_evaluation.json"
PUBLIC_PATH = "reports/inspection/evaluation.json"


def wilson(successes: int, total: int) -> dict:
    if not total:
        return {"lower": 0.0, "upper": 1.0}
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = (
        z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    )
    return {"lower": max(0.0, center - half), "upper": min(1.0, center + half)}


def summarize(rows: list[dict], threshold: float) -> dict:
    positives = [r for r in rows if r["label"] == 1]
    negatives = [r for r in rows if r["label"] == 0]
    tp = sum(r["decision"] == "review" for r in positives)
    fp = sum(r["decision"] == "review" for r in negatives)
    tn = sum(r["decision"] == "within_range" for r in negatives)
    pi = sum(r["decision"] == "unusable" for r in positives)
    ni = sum(r["decision"] == "unusable" for r in negatives)
    scored_p = [r["score"] for r in positives if r["decision"] != "unusable"]
    scored_n = [r["score"] for r in negatives if r["decision"] != "unusable"]
    auc = (
        sum(1 if p > n else 0.5 if p == n else 0 for p in scored_p for n in scored_n)
        / (len(scored_p) * len(scored_n))
        if scored_p and scored_n
        else None
    )
    fn = len(positives) - tp
    model = {
        "auroc": auc,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / len(positives) if positives else 0.0,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
        "accuracy": (tp + tn) / len(rows) if rows else 0.0,
        "true_positive": tp,
        "false_negative": fn,
        "true_negative": tn,
        "false_positive": fp,
        "threshold": threshold,
        "samples": len(rows),
    }
    ci = {
        "recall": wilson(tp, len(positives)),
        "precision": wilson(tp, tp + fp),
        "false_alarm_rate": wilson(fp, len(negatives)),
        "clean_review_or_inconclusive_rate": wilson(fp + ni, len(negatives)),
        "accuracy": wilson(tp + tn, len(rows)),
    }
    return {
        "model": model,
        "coverage": {
            "total": len(rows),
            "scored": len(rows) - pi - ni,
            "inconclusive": pi + ni,
            "defective_inconclusive": pi,
            "clean_inconclusive": ni,
        },
        "binomial_wilson_intervals_95": ci,
        "normal_samples": len(negatives),
        "false_alarms": fp,
        "false_alarm_rate": fp / len(negatives) if negatives else 0.0,
        "clean_review_or_inconclusive_rate": (fp + ni) / len(negatives)
        if negatives
        else 0.0,
        "mean_score": sum(scored_n) / len(scored_n) if scored_n else None,
    }


def stress_summary(summary: dict) -> dict:
    model, coverage = summary["model"], summary["coverage"]
    return {
        **summary,
        "defective": model["true_positive"] + model["false_negative"],
        "defect_alerts": model["true_positive"],
        "clean": summary["normal_samples"],
        "clean_alerts": model["false_positive"],
        "defective_unusable": coverage["defective_inconclusive"],
        "clean_unusable": coverage["clean_inconclusive"],
        "defect_recall": model["recall"],
        "clean_false_alarm_rate": summary["false_alarm_rate"],
    }


def verified_records(root: Path) -> tuple[dict, dict, list[dict]]:
    frozen = verify_freeze(root)
    metadata = load(root / "artifacts/inspection/detector.json")
    raw = load(root / RAW_PATH)
    frozen_hash = digest((root / FREEZE_PATH).read_bytes())
    if (
        raw.get("freeze_sha256") != frozen_hash
        or raw.get("model_sha256") != metadata["export"]["model_sha256"]
        or raw.get("model_version") != metadata["model_version"]
        or raw.get("evaluation", {}).get("cutoff") != metadata["threshold"]
    ):
        raise ValueError(
            "Independent evaluation does not bind the exact frozen model and threshold"
        )
    if (
        raw.get("schema_version") != 1
        or raw.get("threshold_was_tuned") is not False
        or raw.get("source_manifest_sha256") != metadata["dataset"]["manifest_sha256"]
        or raw.get("protocol_sha256")
        != digest((root / "reports/inspection/protocol.json").read_bytes())
    ):
        raise ValueError("Raw evaluation protocol/source provenance differs")
    evaluated_at = datetime.fromisoformat(raw["evaluated_at"])
    frozen_at = datetime.fromisoformat(frozen["frozen_at"])
    if (
        evaluated_at.utcoffset() is None
        or frozen_at.utcoffset() is None
        or evaluated_at < frozen_at
    ):
        raise ValueError(
            "Evaluation must occur after this freeze with timezone-aware timestamps"
        )
    source = {r["path"]: r for r in manifest_rows(root) if r["split"] == "test"}
    records = raw["evaluation"]["records"]
    if not isinstance(records, list) or len(records) != 468:
        raise ValueError(
            "Independent evaluation must contain78images x6conditions, including inconclusive outcomes"
        )
    seen = set()
    for item in records:
        name = item.get("path")
        condition = item.get("variant")
        key = (name, condition)
        if name not in source or condition not in CONDITIONS or key in seen:
            raise ValueError("Duplicate, unknown or missing evaluation image/condition")
        seen.add(key)
        original = source[name]
        if (
            item.get("sha256") != original["sha256"]
            or type(item.get("label")) is not int
            or item["label"] != int(original["label"])
            or item.get("defect_type") != original["defect_type"]
        ):
            raise ValueError("Independent evaluation image provenance/label mismatch")
        score = item.get("score")
        decision = item.get("decision")
        reason = item.get("unusable_reason")
        if score is not None and (
            type(score) not in (float, int)
            or not math.isfinite(score)
            or score < 0
            or round(score, 8) != score
        ):
            raise ValueError("Scores must be finite nonnegative8decimal frozen values")
        if decision == "unusable":
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("Inconclusive records require a reason")
        elif (
            score is None
            or reason is not None
            or decision
            != ("review" if score > metadata["threshold"] else "within_range")
        ):
            raise ValueError(
                "Evaluation decision differs from strict score > threshold"
            )
        if (
            type(item.get("wall_ms")) not in (int, float)
            or not math.isfinite(item["wall_ms"])
            or item["wall_ms"] < 0
        ):
            raise ValueError("Invalid measured evaluation time")
    if seen != {(name, condition) for name in source for condition in CONDITIONS}:
        raise ValueError(
            "Evaluation does not cover each official test image under every condition"
        )
    return metadata, raw, records


def evaluation(root: Path, metadata: dict, records: list[dict]) -> dict:
    threshold = metadata["threshold"]
    protocol = load(root / "reports/inspection/protocol.json")
    conditions = {
        name: summarize([r for r in records if r["variant"] == name], threshold)
        for name in CONDITIONS
    }
    original = [r for r in records if r["variant"] == "original"]
    by_defect = {
        name: summarize([r for r in original if r["defect_type"] == name], threshold)
        for name in sorted({r["defect_type"] for r in original})
    }
    base = conditions["original"]
    return {
        "schema_version": 1,
        "model_version": metadata["model_version"],
        "model_sha256": metadata["export"]["model_sha256"],
        "threshold": threshold,
        "score_is_probability": False,
        "test_count": 78,
        "test_normal": 21,
        "test_defect": 57,
        "model": base["model"],
        "coverage": base["coverage"],
        "binomial_wilson_intervals_95": base["binomial_wilson_intervals_95"],
        "per_defect": by_defect,
        "conditions": conditions,
        "stress_tests": {
            name: stress_summary(summary) for name, summary in conditions.items()
        },
        "freeze_sha256": digest((root / FREEZE_PATH).read_bytes()),
        "raw_report_sha256": digest((root / RAW_PATH).read_bytes()),
        "protocol": {
            **protocol,
            "source_manifest_sha256": metadata["dataset"]["manifest_sha256"],
            "development_manifest_sha256": metadata["dataset"][
                "development_manifest_sha256"
            ],
            "freeze_sha256": digest((root / FREEZE_PATH).read_bytes()),
            "raw_report_sha256": digest((root / RAW_PATH).read_bytes()),
        },
        "qualification": {
            "status": "benchmark_only",
            "automated_line_inspection_qualified": False,
            "independent_target_line_qualified": False,
            "physical_camera_validation_completed": False,
            "reason": "Recovery/reproducibility re-evaluation of a previously used public benchmark. No independent physical target-line qualification.",
        },
        "uncertainty_notes": "Wilson95% intervals reflect fixed-model finite counts; correlated transformed versions are not independent new parts. Unusable defects count as misses; unusable clean images are reported separately, not accepted.",
        "latency_scope": "Raw wall_ms covers detector input preparation/scoring in the evaluation environment; it does not qualify camera-to-decision latency or target-line deadlines.",
    }


def write_gallery(root: Path, metadata: dict, records: list[dict]) -> dict:
    import numpy as np
    from PIL import Image
    from meshlens.inspection_input import inspection_rgb8

    original = {r["path"]: r for r in records if r["variant"] == "original"}
    groups = ("good", "bent", "broken", "glue", "metal_contamination", "thread")
    paths = [
        f"data/raw/grid/test/{name}/{index:03}.png"
        for name in groups
        for index in (0, 1, 2)
    ]
    paths[paths.index("data/raw/grid/test/glue/002.png")] = (
        "data/raw/grid/test/glue/008.png"
    )
    miss = original["data/raw/grid/test/glue/008.png"]
    if miss["label"] != 1 or miss["decision"] != "within_range":
        raise ValueError("Canonical gallery must include actual missed defect glue/008")
    destination = root / "artifacts/inspection/samples"
    destination.mkdir(parents=True, exist_ok=True)
    samples = []
    image_entries = {}
    for path in paths:
        record = original[path]
        source = (root / path).read_bytes()
        if digest(source) != record["sha256"]:
            raise ValueError("Gallery source image digest differs from evaluation")
        with Image.open(io.BytesIO(source)) as image:
            rgb = inspection_rgb8(image, metadata["image_size"])
        buffer = io.BytesIO()
        Image.fromarray(rgb).save(buffer, format="PNG")
        content = buffer.getvalue()
        name = f"{record['defect_type']}-{Path(path).stem}.png"
        (destination / name).write_bytes(content)
        image_entries["images/" + name] = content
        samples.append(
            {
                "id": Path(name).stem,
                "filename": name,
                "label": record["label"],
                "defect_type": record["defect_type"],
                "expected_score": record["score"],
                "expected_anomaly": record["decision"] == "review",
                "expected_decision": record["decision"],
                "model_version": metadata["model_version"],
                "preprocessing": metadata["preprocessing"],
                "source_path": path,
                "source_sha256": record["sha256"],
                "sha256": digest(content),
                "rgb8_sha256": digest(np.ascontiguousarray(rgb).tobytes()),
            }
        )
    expected_files = {s["filename"] for s in samples}
    for old in destination.glob("*.png"):
        if old.name not in expected_files:
            old.unlink()
    gallery = {
        "schema_version": 1,
        "model_version": metadata["model_version"],
        "model_sha256": metadata["export"]["model_sha256"],
        "threshold": metadata["threshold"],
        "count": 18,
        "preprocessing": "area-rgb8-v1",
        "samples": samples,
        "purpose": "Already-evaluated public benchmark replay, not independent validation; includes actual missed defect glue-008.",
        "license": "CC-BY-NC-SA-4.0",
        "curation": {
            "after_test": True,
            "selection": "Three images per group; actual miss glue008 replaces glue002 after evaluation for transparent failure illustration.",
            "independent_validation": False,
        },
    }
    readme = f"""# MeshLens: 18 benchmark replay examples\n\nThese are canonical 256 px derivatives of already-evaluated MVTec AD Grid test images.\nThey are not independent field validation data. Uploading them does not retrain the model.\n\nThe active detector is {metadata["model_version"]}. Its frozen score is not a probability.\nReview only when score > {metadata["threshold"]}; equality is within range.\nTry good-000.png, bent-000.png, then glue-008.png: glue-008 is an actual missed defect.\nLow score does not establish defect-free material. Read manifest.json for all known labels.\nReconstruction is a historical autoencoder illustration, separate from the active detector score.\n\nAll 342 Grid benchmark images already belong to this experiment. Capture and independently label\nnew target-line images for independent validation; transformed copies are not new parts.\nOfficial dataset: https://www.mvtec.com/research-teaching/datasets/mvtec-ad\nData copyright: MVTec Software GmbH and original authors.\nLicense: CC BY-NC-SA 4.0; noncommercial. Terms apply to derivatives.\nhttps://creativecommons.org/licenses/by-nc-sa/4.0/\n"""
    entries = {
        "README.md": readme.encode(),
        "manifest.json": encode(gallery),
        **image_entries,
    }
    for public, source in [
        ("DATASET-LICENSE.txt", "license.txt"),
        ("DATASET-README.txt", "readme.txt"),
    ]:
        entries[public] = (root / "data/raw/grid" / source).read_bytes()
    kit = root / "web/downloads/MeshLens-18-Benchmark-Examples.zip"
    kit.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        kit, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name, content in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    gallery["download"] = {
        "filename": kit.name,
        "sha256": digest(kit.read_bytes()),
        "bytes": kit.stat().st_size,
    }
    (root / "artifacts/inspection/samples.json").write_bytes(encode(gallery))
    return gallery


def export(root: Path = ROOT) -> dict:
    metadata, _, records = verified_records(root)
    public = evaluation(root, metadata, records)
    gallery = write_gallery(root, metadata, records)
    (root / PUBLIC_PATH).write_bytes(encode(public))
    return {
        "model_version": metadata["model_version"],
        "model": public["model"],
        "samples": len(gallery["samples"]),
        "evaluation_sha256": digest((root / PUBLIC_PATH).read_bytes()),
        "kit_sha256": gallery["download"]["sha256"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(export(args.root), indent=2, allow_nan=False))
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
