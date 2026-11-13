"""Frozen release consistency, conservative input gates and the ordinary CLI."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image
import pytest

from meshlens.inspection import InspectionDetector, MAX_FILE_BYTES


def encoded(value):
    return (json.dumps(value, allow_nan=False) + "\n").encode()


def sha(content):
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def bundle(tmp_path):
    artifacts, reports = tmp_path / "artifacts/inspection", tmp_path / "reports/inspection"
    artifacts.mkdir(parents=True)
    reports.mkdir(parents=True)
    model = {"kind": "normal-lattice-v1", "image_size": 256, "preprocessing": "area-rgb8-v1",
             "variant": "local", "tail_fraction": 0.005, "fit_scale": 1.0, "threshold": 1.0, "score_decimals": 8}
    model_bytes = encoded(model)
    rows = [{"path": f"train/good/{i:03}.png", "sha256": sha(str(i).encode()),
             "score": 0.5 if i < 50 else float(i - 49)} for i in range(52)]
    calibration_bytes = encoded(rows)
    metadata = {
        "schema_version": 1, "model_version": "fixture-inspect-1", "runtime": "texture-js",
        "image_size": 256, "preprocessing": "area-rgb8-v1",
        "input_quality": {"min_side": 256, "max_aspect_ratio": 1.5},
        "threshold": 1.0, "decision": "strict-greater-than", "score_is_probability": False,
        "outputs": {"score_name": "score", "map_name": "anomaly_map", "map_size": 256},
        "export": {"model_file": "detector-model.json", "model_sha256": sha(model_bytes), "model_bytes": len(model_bytes)},
        "calibration": {"count": 52, "alpha": 0.05, "order_statistic_rank": 51, "scores_sha256": sha(calibration_bytes)},
    }
    freeze = {"schema_version": 1, "model_version": "fixture-inspect-1", "model_sha256": sha(model_bytes),
              "model_bytes": len(model_bytes), "threshold": 1.0, "preprocessing": "area-rgb8-v1",
              "calibration_sha256": sha(calibration_bytes)}

    def save():
        metadata_bytes = encoded(metadata)
        freeze["metadata_sha256"] = sha(metadata_bytes)
        (artifacts / "detector.json").write_bytes(metadata_bytes)
        (artifacts / "detector-model.json").write_bytes(model_bytes)
        (artifacts / "calibration.json").write_bytes(calibration_bytes)
        (reports / "frozen_configuration.json").write_bytes(encoded(freeze))

    save()
    return tmp_path, metadata, freeze, save


def test_frozen_input_threshold_and_map_decision(bundle, monkeypatch):
    detector = InspectionDetector(bundle[0])
    assert detector.available
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    monkeypatch.setattr("meshlens.texture_detector.score_texture", lambda tensor, model: (1.0, np.zeros((256, 256)), 0.5))
    tied = detector.inspect_image(image)
    assert tied.status == "scored" and tied.is_anomaly is False
    assert tied.decision == "within_range" and np.all(tied.canonical_input == 255)
    assert tied.canonical_input.dtype == np.uint8
    assert tied.model_version == "fixture-inspect-1" and tied.score_is_probability is False
    assert tied.to_dict()["score"] == 1.0 and "anomaly_map" not in tied.to_dict()
    monkeypatch.setattr("meshlens.texture_detector.score_texture", lambda tensor, model: (1.00000001, np.ones((256, 256)), 0.5))
    assert detector.inspect_image(image).is_anomaly is True


def test_unusable_pattern_is_inconclusive(bundle):
    result = InspectionDetector(bundle[0]).inspect_image(Image.new("RGB", (256, 256), "white"))
    assert result.status == "inconclusive" and result.reason == "mesh-pattern-unavailable"
    assert result.score is None and result.is_anomaly is None


@pytest.mark.parametrize("size,reason", [((255, 256), "input-low-resolution"), ((256, 385), "input-aspect-ratio"), ((31, 256), "image-dimensions"), ((4097, 256), "image-dimensions")])
def test_geometry_rejected_before_canonical_decode(bundle, monkeypatch, size, reason):
    detector = InspectionDetector(bundle[0])
    monkeypatch.setattr("meshlens.inspection.inspection_rgb8", lambda *_: pytest.fail("Invalid geometry reached decode"))
    result = detector.inspect_image(Image.new("RGB", size))
    assert result.status == "inconclusive" and result.reason == reason and result.is_anomaly is None


@pytest.mark.parametrize("field,value", [("threshold", 2.0), ("preprocessing", "bilinear"), ("decision", "greater-or-equal"), ("score_is_probability", True)])
def test_malformed_or_conflicting_metadata_abstains(bundle, field, value):
    root, metadata, _, save = bundle
    metadata[field] = value
    save()
    result = InspectionDetector(root).inspect_image(Image.new("RGB", (256, 256)))
    assert result.status == "inconclusive" and result.reason == "model-unavailable"
    assert result.score is None and result.threshold is None


def test_metadata_model_and_calibration_tampering_fail_closed(bundle):
    root, metadata, _, save = bundle
    for relative in ("artifacts/inspection/detector.json", "artifacts/inspection/detector-model.json", "artifacts/inspection/calibration.json"):
        target = root / relative
        target.write_bytes(target.read_bytes() + b" ")
        detector = InspectionDetector(root)
        assert not detector.available
        assert detector.inspect_image(Image.new("RGB", (256, 256))).reason == "model-unavailable"
        save()
    metadata["export"]["model_sha256"] = None
    save()
    assert not InspectionDetector(root).available


def test_unfrozen_source_change_abstains(bundle):
    root, _, freeze, save = bundle
    (root / "source.py").write_text("original")
    freeze["source_code"] = {"source.py": sha(b"original")}
    save()
    assert InspectionDetector(root).available
    (root / "source.py").write_text("changed")
    assert not InspectionDetector(root).available


@pytest.mark.parametrize("score,anomaly", [(float("nan"), np.zeros((256, 256))), (-1, np.zeros((256, 256))), (0.5, np.full((256, 256), float("inf"))), (0.5, np.full((256, 256), -1)), (0.5, np.zeros((8, 8)))])
def test_invalid_outputs_cannot_be_clean_decisions(bundle, monkeypatch, score, anomaly):
    monkeypatch.setattr("meshlens.texture_detector.score_texture", lambda tensor, model: (score, anomaly, 0.5))
    result = InspectionDetector(bundle[0]).inspect_image(Image.new("RGB", (256, 256)))
    assert result.status == "inconclusive" and result.reason == "inference-failed"
    assert result.score is None and result.is_anomaly is None


def test_supported_file_provenance_and_corruption(bundle, monkeypatch):
    root = bundle[0]
    path = root / "image.png"
    Image.new("RGB", (256, 256)).save(path)
    monkeypatch.setattr("meshlens.texture_detector.score_texture", lambda tensor, model: (0.5, np.zeros((256, 256)), 0.5))
    detector = InspectionDetector(root)
    result = detector.inspect(path)
    assert result.status == "scored" and result.source_sha256 == sha(path.read_bytes())
    assert detector.inspect(root / "missing.png").reason == "input-missing"
    path.write_bytes(b"not an image")
    assert detector.inspect(path).reason == "invalid-image"
    Image.new("RGB", (256, 256)).save(path, format="GIF")
    assert detector.inspect(path).reason == "unsupported-format"
    path.write_bytes(b"X" * (MAX_FILE_BYTES + 1))
    assert detector.inspect(path).reason == "input-file-size"


def test_animation_containers_abstain_before_decode(bundle):
    root = bundle[0]
    fixtures = json.loads((Path(__file__).parent / "fixtures/image-containers.json").read_text())
    detector = InspectionDetector(root)
    for name in ("pngAnimated", "webpAnimated"):
        path = root / f"{name}.image"
        path.write_bytes(base64.b64decode(fixtures[name]))
        result = detector.inspect(path)
        assert result.reason == "animated-image" and result.is_anomaly is None


def test_actual_cli_entrypoint_from_other_directory(bundle, tmp_path):
    root = bundle[0]
    image = root / "blank.png"
    Image.new("RGB", (256, 256), "white").save(image)
    script = Path(__file__).resolve().parents[1] / "scripts/inspect_image.py"
    output = tmp_path / "new-output.json"
    command = [sys.executable, str(script), str(image), "--bundle", str(root), "--output", str(output)]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "inconclusive" and report["reason"] == "mesh-pattern-unavailable"
    assert json.loads(output.read_text()) == report
    blocked = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert blocked.returncode == 2 and json.loads(output.read_text()) == report


def test_real_frozen_artifact_and_cli_evidence(project_root, tmp_path):
    if not (project_root / "artifacts/inspection/detector.json").exists():
        pytest.skip("The selected release has not yet been frozen")
    image = project_root / "data/raw/grid/train/good/000.png"
    if not image.exists():
        pytest.skip("Raw training example is not installed in this test environment")
    script = project_root / "scripts/inspect_image.py"
    evidence = tmp_path / "real-evidence"
    result = subprocess.run([sys.executable, str(script), str(image), "--bundle", str(project_root), "--evidence", str(evidence)],
                            cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    document = json.loads(result.stdout)
    assert document["status"] == "scored" and document["score_is_probability"] is False
    assert document["source_sha256"] == sha(image.read_bytes()) and (evidence / "canonical-input.png").is_file()
    with Image.open(evidence / "relative-anomaly-map.png") as anomaly:
        assert anomaly.mode == "L" and anomaly.size == (256, 256)
    assert json.loads((evidence / "result.json").read_text()) == document
