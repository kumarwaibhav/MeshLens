"""Independent physical-part rosters remain the acceptance denominator."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from statistics import NormalDist
import subprocess
import sys

import pytest

from meshlens.field_qualification import _rate, qualify_field


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def csv_bytes(fields, rows) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


@pytest.fixture
def evidence(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "artifacts").mkdir()
    benchmark = csv_bytes(["sha256"], [{"sha256": digest(b"benchmark")}])
    (tmp_path / "data/manifest.csv").write_bytes(benchmark)
    (tmp_path / "data/provenance.json").write_text(json.dumps({"manifest_sha256": digest(benchmark), "image_count": 1}))
    (tmp_path / "artifacts/samples.json").write_text(json.dumps({"samples": [{"sha256": digest(b"gallery")}]}))
    artifact = tmp_path / "detector.json"
    artifact.write_bytes(b'{"model":"fixture"}')
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"model_version": "field-fixture-1", "threshold": 1.0,
                                   "export": {"model_sha256": digest(artifact.read_bytes())},
                                   "calibration": {"strict_greater_than": True}}))
    cohort = [{"part_id": f"part-{i}", "image_sha256": digest(f"independent-{i}".encode()), "label": int(i >= 100)} for i in range(200)]
    scores = [{**row, "run_id": "run-1", "status": "scored", "score": 2 if row["label"] else 0.5} for row in cohort]
    protocol = {
        "schema_version": 1,
        "dataset": {"dataset_id": "independent-line-a", "role": "field_holdout", "source_kind": "target_line_capture",
                    "held_out_from_development": True, "one_record_per_part": True,
                    "capture_scope": "camera A; shift 1; fixed lens and light", "label_method": "physical inspection and independent reconciliation",
                    "collection_start": "2026-11-01", "collection_end": "2026-11-02"},
        "run": {"run_id": "run-1", "model_version": "field-fixture-1", "threshold": 1.0,
                "decision_rule": "score > threshold", "artifact_sha256": digest(artifact.read_bytes()), "metadata_sha256": digest(metadata.read_bytes()),
                "protocol_frozen_at": "2026-10-31T00:00:00+00:00", "scored_at": "2026-11-03T00:00:00+00:00"},
        "acceptance": {"min_clean_parts": 100, "min_defect_parts": 100, "confidence_level": 0.95,
                       "min_recall_lower_bound": 0.95, "max_clean_review_upper_bound": 0.05, "min_class_coverage": 1.0},
    }

    def write():
        manifest = csv_bytes(["part_id", "image_sha256", "label"], cohort)
        records = csv_bytes(["run_id", "part_id", "image_sha256", "label", "status", "score"], scores)
        (tmp_path / "cohort.csv").write_bytes(manifest)
        (tmp_path / "scores.csv").write_bytes(records)
        protocol["dataset"]["manifest_sha256"] = digest(manifest)
        protocol["run"]["records_sha256"] = digest(records)
        (tmp_path / "run.json").write_text(json.dumps(protocol))

    def qualify(**kwargs):
        write()
        return qualify_field(tmp_path, cohort_manifest=tmp_path / "cohort.csv", records=tmp_path / "scores.csv", provenance=tmp_path / "run.json",
                             model_artifact=artifact, model_metadata=metadata, **kwargs)

    return tmp_path, cohort, scores, protocol, metadata, write, qualify


def test_wilson_known_boundaries():
    z = NormalDist().inv_cdf(0.975)
    assert _rate(100, 100, z)["lower"] == pytest.approx(0.9630065017930143)
    assert _rate(0, 100, z)["upper"] == pytest.approx(0.03699349820698568)
    assert _rate(0, 0, z) == {"count": 0, "parts": 0, "value": None, "lower": 0.0, "upper": 1.0}


def test_independent_complete_cohort_passes(evidence):
    report = evidence[-1]()
    assert report["status"] == "pass" and all(report["checks"].values())
    assert report["counts"]["flagged_defects"] == 100 and report["exclusions"]["excluded_image_hashes"] == 2


def test_missing_and_inconclusive_stay_in_denominator(evidence):
    _, _, scores, _, _, _, qualify = evidence
    scores.pop()
    scores[0].update(status="inconclusive", score="")
    report = qualify()
    assert report["status"] == "fail" and report["rates"]["defect_recall"]["value"] == 0.99
    assert report["rates"]["clean_review_rate"]["count"] == 1 and report["counts"]["parts_missing_score_record"] == 1
    assert not report["checks"]["defect_coverage"] and not report["checks"]["clean_coverage"]


def test_strict_threshold_and_absent_class(evidence):
    _, cohort, scores, _, _, _, qualify = evidence
    scores[100]["score"] = 1.0
    assert qualify()["counts"]["missed_defects"] == 1
    del cohort[100:]
    del scores[100:]
    report = qualify()
    assert not report["checks"]["minimum_defect_parts"] and report["rates"]["defect_recall"]["value"] is None


def test_benchmark_and_gallery_leakage(evidence):
    _, cohort, _, _, _, _, qualify = evidence
    for content in (b"benchmark", b"gallery"):
        cohort[0]["image_sha256"] = digest(content)
        with pytest.raises(ValueError, match="matches a benchmark"):
            qualify()


def test_active_gallery_leakage(evidence):
    root, cohort, _, _, _, _, qualify = evidence
    (root / "artifacts/inspection").mkdir()
    (root / "artifacts/inspection/samples.json").write_text(json.dumps({"samples": [{"sha256": digest(b"active-gallery")}]}))
    cohort[0]["image_sha256"] = digest(b"active-gallery")
    with pytest.raises(ValueError, match="matches a benchmark"):
        qualify()


def test_additional_development_exclusion(evidence):
    root, cohort, _, _, _, _, qualify = evidence
    extra = root / "development.csv"
    extra.write_bytes(csv_bytes(["sha256"], [{"sha256": cohort[0]["image_sha256"]}]))
    with pytest.raises(ValueError, match="matches a benchmark"):
        qualify(exclude_manifests=(extra,))


def test_duplicate_parts_images_and_records(evidence):
    _, cohort, scores, _, _, _, qualify = evidence
    cohort.append(cohort[0].copy())
    with pytest.raises(ValueError, match="Duplicate physical part"):
        qualify()
    cohort[-1]["part_id"] = "other-part"
    with pytest.raises(ValueError, match="Duplicate physical part"):
        qualify()
    cohort.pop()
    scores.append(scores[0].copy())
    with pytest.raises(ValueError, match="duplicate scored part"):
        qualify()


def test_mixed_runs_and_conflicting_labels(evidence):
    _, _, scores, _, _, _, qualify = evidence
    scores[0]["run_id"] = "another-run"
    with pytest.raises(ValueError, match="different scoring run"):
        qualify()
    scores[0].update(run_id="run-1", label=1)
    with pytest.raises(ValueError, match="different image or label"):
        qualify()


def test_score_must_be_finite_nonnegative_or_blank_inconclusive(evidence):
    _, _, scores, _, _, _, qualify = evidence
    for invalid in ("nan", "inf", "-inf", "-0.1", ""):
        scores[0]["score"] = invalid
        with pytest.raises(ValueError):
            qualify()
    scores[0].update(status="inconclusive", score="1")
    with pytest.raises(ValueError, match="blank score"):
        qualify()


def test_model_threshold_and_hash_mismatch(evidence):
    _, _, _, protocol, _, _, qualify = evidence
    protocol["run"]["threshold"] = -1
    with pytest.raises(ValueError, match="nonnegative"):
        qualify()
    protocol["run"]["threshold"] = 2
    with pytest.raises(ValueError, match="differs from frozen"):
        qualify()
    protocol["run"].update(threshold=1, artifact_sha256="0" * 64)
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        qualify()


def test_conflicting_metadata_hash_and_comparator(evidence):
    _, _, _, protocol, metadata_path, _, qualify = evidence
    metadata = json.loads(metadata_path.read_text())
    metadata["model_sha256"] = metadata["export"]["model_sha256"]
    metadata["export"]["model_sha256"] = "0" * 64
    metadata_path.write_text(json.dumps(metadata))
    protocol["run"]["metadata_sha256"] = digest(metadata_path.read_bytes())
    with pytest.raises(ValueError, match="Export model hash conflicts"):
        qualify()
    metadata["export"]["model_sha256"] = metadata["model_sha256"]
    metadata["calibration"]["strict_greater_than"] = False
    metadata_path.write_text(json.dumps(metadata))
    protocol["run"]["metadata_sha256"] = digest(metadata_path.read_bytes())
    with pytest.raises(ValueError, match="strict greater-than"):
        qualify()


def test_independence_dates_and_count_type(evidence):
    _, _, _, protocol, _, _, qualify = evidence
    protocol["dataset"]["held_out_from_development"] = False
    with pytest.raises(ValueError, match="held out"):
        qualify()
    protocol["dataset"].update(held_out_from_development=True, collection_end="2026-11-04")
    with pytest.raises(ValueError, match="finish after scoring"):
        qualify()
    protocol["dataset"]["collection_end"] = "2026-11-02"
    protocol["acceptance"]["min_clean_parts"] = True
    with pytest.raises(ValueError, match="positive integer"):
        qualify()


def test_tampered_records(evidence):
    root, _, _, _, _, write, _ = evidence
    write()
    (root / "scores.csv").write_bytes((root / "scores.csv").read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        qualify_field(root, cohort_manifest=root / "cohort.csv", records=root / "scores.csv", provenance=root / "run.json",
                      model_artifact=root / "detector.json", model_metadata=root / "metadata.json")


def test_cli_entrypoint_status_and_preserve_report(evidence, tmp_path):
    root, _, scores, _, _, write, _ = evidence
    write()
    script = Path(__file__).resolve().parents[1] / "scripts/qualify_field.py"
    command = [sys.executable, str(script), "--cohort-manifest", str(root / "cohort.csv"), "--records", str(root / "scores.csv"),
               "--provenance", str(root / "run.json"), "--model-artifact", str(root / "detector.json"), "--model-metadata", str(root / "metadata.json")]
    good = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert good.returncode == 0, good.stderr
    assert json.loads(good.stdout)["status"] == "pass"
    scores[100]["score"] = 1
    write()
    failed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert failed.returncode == 1
    report = tmp_path / "existing.json"
    report.write_text("keep-me")
    blocked = subprocess.run([*command, "--report", str(report)], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert blocked.returncode == 2 and report.read_text() == "keep-me"
