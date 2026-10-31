"""Check frozen inference artifacts; local digests detect release mismatches.

Digests are not signed distribution or protection if every file is replaced.
"""

from __future__ import annotations
import csv
import hashlib
import json
import math
from pathlib import Path


def _json(path: Path) -> dict:
    def reject_constant(value):
        raise ValueError(f"Non-finite JSON number: {value}")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON field: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=unique_keys,
        )
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Frozen artifact is missing or invalid: {path.name}"
        ) from error


def _number(value, name: str, *, positive: bool = False) -> float:
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not (0 < value <= 1 if positive else 0 <= value <= 1)
    ):
        raise ValueError(f"Invalid frozen {name}")
    return float(value)


def _digest(value, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError(f"Invalid {name} SHA256")
    return value


def verified_model_bytes(root: Path, metadata: dict) -> bytes:
    """Hash and return the same bytes supplied to ONNX Runtime."""
    try:
        if metadata.get("model_path") != "model.onnx":
            raise ValueError("Frozen model path must be model.onnx")
        exported = metadata["export"]
        expected = _digest(exported["model_sha256"], "ONNX model")
        path = Path(root) / "artifacts/model.onnx"
        size = exported["model_bytes"]
        if (
            type(size) is not int
            or not 1 <= size <= 2_000_000
            or path.stat().st_size != size
        ):
            raise ValueError("ONNX model size mismatch or unsupported artifact size")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected or len(content) != size:
            raise ValueError(
                "ONNX model SHA256/size mismatch; restore the matching frozen bundle"
            )
        return content
    except (KeyError, TypeError, OSError) as error:
        raise ValueError(
            "Frozen ONNX model or its export metadata is unavailable"
        ) from error


def load_frozen_metadata(root: Path, verify_model: bool = True) -> dict:
    """Require metadata, normal calibration and frozen selection to agree."""
    root = Path(root)
    metadata, freeze = (
        _json(root / "artifacts/metadata.json"),
        _json(root / "reports/frozen_configuration.json"),
    )
    try:
        if (
            type(metadata["schema_version"]) is not int
            or metadata["schema_version"] != 1
            or type(metadata["image_size"]) is not int
            or metadata["image_size"] != 256
            or metadata["input_shape"] != [1, 3, 256, 256]
            or metadata["input_name"] != "image"
            or metadata["output_name"] != "reconstruction"
        ):
            raise ValueError("Unsupported frozen model input/output contract")
        if any(
            metadata["input"][key] != value
            for key, value in {
                "color": "RGB",
                "layout": "NCHW",
                "dtype": "float32",
                "range": [0, 1],
                "alpha_compositing": "opaque white before resize",
                "min_side": 32,
                "max_side": 4096,
                "max_pixels": 16_000_000,
                "max_file_bytes": 12 * 1024 * 1024,
                "supported_upload_formats": ["PNG", "JPEG", "WEBP"],
            }.items()
        ):
            raise ValueError("Unsupported frozen image preprocessing contract")
        threshold = _number(metadata["threshold"], "threshold")
        fraction = _number(metadata["top_fraction"], "top fraction", positive=True)
        if (
            metadata["score_top_fraction"] != fraction
            or metadata["score"]["top_fraction"] != fraction
            or metadata["score"]["pixel_count"] != math.ceil(256 * 256 * fraction)
            or metadata["score"]["is_probability"] is not False
            or metadata["score"]["smoothing"] is not None
            or metadata["calibration"]["strict_greater_than"] is not True
        ):
            raise ValueError("Inconsistent frozen scoring contract")
        if freeze["threshold"] != threshold or freeze["top_fraction"] != fraction:
            raise ValueError("Metadata and frozen calibration configuration disagree")
        checkpoint_hash = _digest(freeze["checkpoint_sha256"], "checkpoint")
        if metadata["model_version"] != "meshlens-ae-" + checkpoint_hash[:12]:
            raise ValueError("Model version and frozen checkpoint digest disagree")
        # An ONNX-only inference bundle need not include PyTorch weights. When
        # they are bundled, reject a stale/mixed release even without PyTorch.
        checkpoint_path = root / "artifacts/checkpoint.pt"
        if checkpoint_path.exists() and (
            checkpoint_path.stat().st_size > 2_000_000
            or hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
            != checkpoint_hash
        ):
            raise ValueError("Bundled checkpoint SHA256 mismatch")
        for key in ("latent_channels", "epochs", "best_epoch", "noise_std"):
            if metadata["architecture"][key] != freeze["candidate"][key]:
                raise ValueError("Metadata and frozen architecture disagree")
        calibration = metadata["calibration"]
        count, rank = freeze["calibration_count"], freeze["calibration_order_rank"]
        alpha = _number(freeze["calibration_alpha"], "calibration alpha", positive=True)
        if (
            type(count) is not int
            or count < 1
            or type(rank) is not int
            or rank != math.ceil((count + 1) * (1 - alpha))
            or not 1 <= rank <= count
            or calibration["count"] != count
            or calibration["alpha"] != alpha
            or calibration["order_statistic_rank"] != rank
        ):
            raise ValueError("Inconsistent frozen normal calibration rank")
        score_path = root / "reports/calibration_scores.csv"
        if score_path.stat().st_size > 1_000_000:
            raise ValueError("Frozen normal calibration file exceeds expected bounds")
        score_bytes = score_path.read_bytes()
        expected_scores = _digest(
            freeze["calibration_score_sha256"], "normal calibration"
        )
        if hashlib.sha256(score_bytes).hexdigest() != expected_scores:
            raise ValueError("Normal calibration scores SHA256 mismatch")
        records = list(csv.DictReader(score_bytes.decode("utf-8").splitlines()))
        if (
            len(records) != count
            or len({r["path"] for r in records}) != count
            or any(r["split"] != "calibration" or r["label"] != "0" for r in records)
        ):
            raise ValueError(
                "Frozen calibration must contain only the recorded normal images"
            )
        values = [_number(float(row["score"]), "calibration score") for row in records]
        if sorted(values)[rank - 1] != threshold:
            raise ValueError(
                "Threshold does not match the frozen normal order statistic"
            )
        if verify_model:
            verified_model_bytes(root, metadata)
    except (KeyError, TypeError, OSError, UnicodeError, OverflowError) as error:
        raise ValueError(
            "Frozen model metadata/calibration is incomplete or invalid"
        ) from error
    return metadata


def load_development_selection(root: Path) -> dict:
    """Check the recorded development-only winner and its data lineage."""
    root = Path(root)
    selection = _json(root / "reports/selection.json")
    try:
        if (
            selection["test_loaded_during_selection"] is not False
            or selection["calibration_loaded_during_selection"] is not False
        ):
            raise ValueError(
                "Selection must exclude calibration and official test data"
            )
        expected = _digest(selection["manifest_sha256"], "selection manifest")
        if (
            hashlib.sha256((root / "data/manifest.csv").read_bytes()).hexdigest()
            != expected
        ):
            raise ValueError("Development selection manifest SHA256 mismatch")
        candidates = selection["candidates"]
        if not isinstance(candidates, list) or len(candidates) != 4:
            raise ValueError(
                "Expected the two planned candidates and two score fractions"
            )
        combinations = set()
        for candidate in candidates:
            name, fraction = candidate["name"], candidate["top_fraction"]
            if name not in {"compact-clean", "denoising"} or fraction not in {
                0.01,
                0.05,
            }:
                raise ValueError("Unexpected development candidate or score fraction")
            combinations.add((name, fraction))
            if candidate["checkpoint"] != f"artifacts/candidate-{name}.pt":
                raise ValueError(
                    "Candidate checkpoint path does not match planned experiment"
                )
            _number(candidate["development_synthetic_auroc"], "development AUROC")
            _number(candidate["normal_tune_mse"], "normal development error")
        if len(combinations) != 4:
            raise ValueError("Duplicate or missing development candidate comparison")
        winner = sorted(
            candidates,
            key=lambda row: (
                -row["development_synthetic_auroc"],
                row["normal_tune_mse"],
                row["top_fraction"],
            ),
        )[0]
        if selection["selected"] != winner:
            raise ValueError(
                "Selected candidate disagrees with frozen development rule"
            )
    except (KeyError, TypeError, OSError) as error:
        raise ValueError("Development selection is incomplete or invalid") from error
    return selection
