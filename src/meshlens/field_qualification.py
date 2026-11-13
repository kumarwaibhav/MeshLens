"""Qualify a frozen inspection release against an independent field cohort."""

from __future__ import annotations

from collections import Counter
import csv
from datetime import date, datetime
import hashlib
import io
import json
import math
from pathlib import Path
import re
from statistics import NormalDist


COHORT_FIELDS = {"part_id", "image_sha256", "label"}
SCORE_FIELDS = COHORT_FIELDS | {"run_id", "status", "score"}
DECISION_RULE = "score > threshold"


def _json(content: bytes, name: str):
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate field {key} in {name}")
            result[key] = value
        return result

    return json.loads(content.decode("utf-8-sig"), object_pairs_hook=unique_fields)


def _object(value, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _text(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _identifier(value, name: str) -> str:
    value = _text(value, name)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError(f"Invalid {name}; use a short alphanumeric identifier")
    return value


def _digest(value, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError(f"Invalid SHA256 for {name}")
    return value.lower()


def _match_digest(content: bytes, expected, name: str) -> str:
    actual = hashlib.sha256(content).hexdigest()
    if actual != _digest(expected, name):
        raise ValueError(f"{name} SHA256 mismatch")
    return actual


def _number(value, name: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite number")
    try:
        value = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} must be a finite number") from error
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return value


def _time(value, name: str) -> datetime:
    moment = datetime.fromisoformat(_text(value, name))
    if moment.utcoffset() is None:
        raise ValueError(f"{name} must include a time zone")
    return moment


def _csv_rows(content: bytes, fields: set[str], name: str):
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
    columns = reader.fieldnames or []
    if not fields.issubset(columns) or len(columns) != len(set(columns)):
        raise ValueError(f"{name} must have unique headers and contain {', '.join(sorted(fields))}")
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Malformed row in {name} at line {reader.line_num}")
        yield {key: value.strip() for key, value in row.items()}


def _exclude_hashes(root: Path, manifests: tuple[Path, ...]) -> tuple[set[str], dict]:
    benchmark = (root / "data/manifest.csv").read_bytes()
    provenance = _object(_json((root / "data/provenance.json").read_bytes(), "benchmark provenance"), "benchmark provenance")
    _match_digest(benchmark, provenance.get("manifest_sha256"), "benchmark manifest")
    hashes = {_digest(row["sha256"], "benchmark image") for row in _csv_rows(benchmark, {"sha256"}, "benchmark manifest")}
    if not hashes or len(hashes) != provenance.get("image_count"):
        raise ValueError("Benchmark image hashes do not match the declared count")
    galleries = []
    for relative in ("artifacts/samples.json", "artifacts/inspection/samples.json"):
        gallery_path = root / relative
        if not gallery_path.exists() and relative.startswith("artifacts/inspection/"):
            continue
        content = gallery_path.read_bytes()
        gallery = _object(_json(content, "example gallery"), "example gallery")
        samples = gallery.get("samples")
        if not isinstance(samples, list) or not samples:
            raise ValueError("Example gallery must contain image hashes")
        for sample in samples:
            hashes.add(_digest(_object(sample, "gallery sample").get("sha256"), "gallery image"))
        galleries.append({"path": relative, "sha256": hashlib.sha256(content).hexdigest()})
    additional = []
    for manifest in manifests:
        content = manifest.read_bytes()
        for row in _csv_rows(content, {"sha256"}, manifest.name):
            hashes.add(_digest(row["sha256"], "excluded development image"))
        additional.append({"name": manifest.name, "sha256": hashlib.sha256(content).hexdigest()})
    return hashes, {
        "benchmark_manifest_sha256": hashlib.sha256(benchmark).hexdigest(),
        "gallery_manifests": galleries,
        "additional_manifests": additional,
        "excluded_image_hashes": len(hashes),
    }


def _read_cohort(content: bytes, excluded: set[str]) -> dict[str, tuple[str, int]]:
    cohort = {}
    hashes = set()
    for row in _csv_rows(content, COHORT_FIELDS, "cohort manifest"):
        part = _identifier(row["part_id"], "part_id").casefold()
        digest = _digest(row["image_sha256"], "field image")
        if digest in excluded:
            raise ValueError(f"Part {part} matches a benchmark, gallery, or development image")
        if part in cohort or digest in hashes:
            raise ValueError(f"Duplicate physical part or image in cohort manifest: {part}")
        if row["label"] not in {"0", "1"}:
            raise ValueError(f"Part {part} requires label 0 for clean or 1 for defective")
        cohort[part] = (digest, int(row["label"]))
        hashes.add(digest)
    if not cohort:
        raise ValueError("The cohort manifest must contain at least one physical part")
    return cohort


def _read_scores(content: bytes, cohort: dict, run_id: str, threshold: float) -> dict:
    decisions = {}
    for row in _csv_rows(content, SCORE_FIELDS, "score records"):
        part = _identifier(row["part_id"], "part_id").casefold()
        if row["run_id"] != run_id:
            raise ValueError(f"Part {part} belongs to a different scoring run")
        if part not in cohort or part in decisions:
            raise ValueError(f"Unregistered or duplicate scored part: {part}")
        digest, label = cohort[part]
        if _digest(row["image_sha256"], "score record image") != digest or row["label"] != str(label):
            raise ValueError(f"Part {part} has a different image or label in the cohort manifest")
        if row["status"] == "inconclusive" and not row["score"]:
            decisions[part] = None
        elif row["status"] == "scored":
            score = _number(float(row["score"]), f"score for {part}")
            if score < 0:
                raise ValueError(f"Score for {part} must be nonnegative")
            decisions[part] = score > threshold
        else:
            raise ValueError(f"Part {part} requires a scored result or an inconclusive result with a blank score")
    return decisions


def _rate(successes: int, trials: int, z: float) -> dict:
    if not trials:
        return {"count": successes, "parts": trials, "value": None, "lower": 0.0, "upper": 1.0}
    proportion = successes / trials
    z_squared = z * z
    denominator = 1 + z_squared / trials
    center = (proportion + z_squared / (2 * trials)) / denominator
    margin = z * math.sqrt(proportion * (1 - proportion) / trials + z_squared / (4 * trials**2)) / denominator
    return {
        "count": successes,
        "parts": trials,
        "value": proportion,
        "lower": 0.0 if successes == 0 else max(0.0, center - margin),
        "upper": 1.0 if successes == trials else min(1.0, center + margin),
    }


def _acceptance(value) -> dict:
    raw = _object(value, "acceptance")
    result = {}
    for field in ("min_clean_parts", "min_defect_parts"):
        count = raw.get(field)
        if type(count) is not int or count < 1:
            raise ValueError(f"acceptance.{field} must be a positive integer")
        result[field] = count
    for field, maximum_inclusive in (
        ("confidence_level", False),
        ("min_recall_lower_bound", True),
        ("min_class_coverage", True),
    ):
        number = _number(raw.get(field), f"acceptance.{field}")
        if not 0 < number <= 1 or (number == 1 and not maximum_inclusive):
            raise ValueError(f"acceptance.{field} is outside its valid probability range")
        result[field] = number
    bound = _number(raw.get("max_clean_review_upper_bound"), "acceptance.max_clean_review_upper_bound")
    if not 0 <= bound < 1:
        raise ValueError("acceptance.max_clean_review_upper_bound must be in [0, 1)")
    result["max_clean_review_upper_bound"] = bound
    return result


def qualify_field(
    root: Path,
    *,
    cohort_manifest: Path,
    records: Path,
    provenance: Path,
    model_artifact: Path,
    model_metadata: Path,
    exclude_manifests: tuple[Path, ...] = (),
) -> dict:
    """Verify evidence and apply frozen statistical criteria to the full cohort."""
    provenance_bytes = provenance.read_bytes()
    protocol = _object(_json(provenance_bytes, "field provenance"), "field provenance")
    if type(protocol.get("schema_version")) is not int or protocol["schema_version"] != 1:
        raise ValueError("Unsupported field provenance schema version")
    dataset = _object(protocol.get("dataset"), "dataset")
    dataset_id = _identifier(dataset.get("dataset_id"), "dataset_id")
    if dataset.get("role") != "field_holdout" or dataset.get("source_kind") != "target_line_capture":
        raise ValueError("Field qualification requires independent images captured on the target line")
    if dataset.get("held_out_from_development") is not True or dataset.get("one_record_per_part") is not True:
        raise ValueError("Confirm that the field cohort was held out from development and uses one record per physical part")
    capture_scope = _text(dataset.get("capture_scope"), "dataset.capture_scope")
    label_method = _text(dataset.get("label_method"), "dataset.label_method")
    first_date = date.fromisoformat(_text(dataset.get("collection_start"), "dataset.collection_start"))
    last_date = date.fromisoformat(_text(dataset.get("collection_end"), "dataset.collection_end"))
    if last_date < first_date:
        raise ValueError("Field collection end precedes the start")

    run = _object(protocol.get("run"), "run")
    run_id = _identifier(run.get("run_id"), "run_id")
    model_version = _identifier(run.get("model_version"), "model_version")
    threshold = _number(run.get("threshold"), "run.threshold")
    if threshold < 0:
        raise ValueError("run.threshold must be nonnegative")
    if run.get("decision_rule") != DECISION_RULE:
        raise ValueError(f"Field run decision rule must be '{DECISION_RULE}'")
    frozen_at = _time(run.get("protocol_frozen_at"), "run.protocol_frozen_at")
    scored_at = _time(run.get("scored_at"), "run.scored_at")
    if frozen_at > scored_at:
        raise ValueError("The field protocol must be frozen before scoring")
    if last_date > scored_at.date():
        raise ValueError("Field collection cannot finish after scoring")
    acceptance = _acceptance(protocol.get("acceptance"))

    with model_artifact.open("rb") as stream:
        artifact_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    if artifact_sha256 != _digest(run.get("artifact_sha256"), "model artifact"):
        raise ValueError("Model artifact SHA256 mismatch")
    metadata_bytes = model_metadata.read_bytes()
    metadata_sha256 = _match_digest(metadata_bytes, run.get("metadata_sha256"), "model metadata")
    metadata = _object(_json(metadata_bytes, "model metadata"), "model metadata")
    export = _object(metadata.get("export", {}), "model metadata export")
    metadata_artifact = metadata.get("model_sha256", export.get("model_sha256"))
    if (
        metadata.get("model_version") != model_version
        or _number(metadata.get("threshold"), "model metadata threshold") != threshold
        or _digest(metadata_artifact, "metadata model artifact") != artifact_sha256
    ):
        raise ValueError("Run model version, threshold, or artifact differs from frozen metadata")
    if "model_sha256" in export and _digest(export["model_sha256"], "exported model") != artifact_sha256:
        raise ValueError("Export model hash conflicts with the actual model")
    if metadata.get("decision_rule", DECISION_RULE) != DECISION_RULE:
        raise ValueError("Model metadata uses a different decision rule")
    if metadata.get("decision", "strict-greater-than") != "strict-greater-than":
        raise ValueError("Model metadata must use a strict greater-than decision")
    calibration = _object(metadata.get("calibration", {}), "model calibration")
    if calibration.get("strict_greater_than", True) is not True:
        raise ValueError("Model calibration must use a strict greater-than comparison")

    cohort_bytes = cohort_manifest.read_bytes()
    cohort_sha256 = _match_digest(cohort_bytes, dataset.get("manifest_sha256"), "cohort manifest")
    excluded, exclusion_provenance = _exclude_hashes(root, exclude_manifests)
    cohort = _read_cohort(cohort_bytes, excluded)
    records_bytes = records.read_bytes()
    records_sha256 = _match_digest(records_bytes, run.get("records_sha256"), "score records")
    decisions = _read_scores(records_bytes, cohort, run_id, threshold)

    outcomes = Counter((label, decisions.get(part)) for part, (_, label) in cohort.items())
    tp, fn, unscored_defects = (outcomes[(1, outcome)] for outcome in (True, False, None))
    fp, tn, unscored_clean = (outcomes[(0, outcome)] for outcome in (True, False, None))
    defects = tp + fn + unscored_defects
    clean = fp + tn + unscored_clean
    z = -NormalDist().inv_cdf((1 - acceptance["confidence_level"]) / 2)
    rates = {
        "defect_recall": _rate(tp, defects, z),
        "false_alarm_rate": _rate(fp, clean, z),
        "clean_review_rate": _rate(fp + unscored_clean, clean, z),
        "defect_coverage": _rate(tp + fn, defects, z),
        "clean_coverage": _rate(fp + tn, clean, z),
    }
    checks = {
        "minimum_defect_parts": defects >= acceptance["min_defect_parts"],
        "minimum_clean_parts": clean >= acceptance["min_clean_parts"],
        "defect_recall_bound": rates["defect_recall"]["lower"] >= acceptance["min_recall_lower_bound"],
        "clean_review_bound": rates["clean_review_rate"]["upper"] <= acceptance["max_clean_review_upper_bound"],
        "defect_coverage": (rates["defect_coverage"]["value"] or 0.0) >= acceptance["min_class_coverage"],
        "clean_coverage": (rates["clean_coverage"]["value"] or 0.0) >= acceptance["min_class_coverage"],
    }
    return {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "dataset": {
            "dataset_id": dataset_id,
            "role": "field_holdout",
            "capture_scope": capture_scope,
            "label_method": label_method,
            "collection_start": first_date.isoformat(),
            "collection_end": last_date.isoformat(),
            "manifest_sha256": cohort_sha256,
        },
        "run": {
            "run_id": run_id,
            "model_version": model_version,
            "artifact_sha256": artifact_sha256,
            "metadata_sha256": metadata_sha256,
            "records_sha256": records_sha256,
            "provenance_sha256": hashlib.sha256(provenance_bytes).hexdigest(),
            "threshold": threshold,
            "decision_rule": DECISION_RULE,
            "protocol_frozen_at": frozen_at.isoformat(),
            "scored_at": scored_at.isoformat(),
        },
        "counts": {
            "defect_parts": defects,
            "clean_parts": clean,
            "flagged_defects": tp,
            "missed_defects": fn,
            "false_alarms": fp,
            "clean_not_flagged": tn,
            "inconclusive_defect_parts": unscored_defects,
            "inconclusive_clean_parts": unscored_clean,
            "parts_missing_score_record": len(cohort) - len(decisions),
        },
        "interval_method": "two-sided Wilson",
        "exclusions": exclusion_provenance,
        "rates": rates,
        "acceptance": acceptance,
        "checks": checks,
    }
