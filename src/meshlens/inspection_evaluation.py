"""Independent frozen-detector evaluation. No selection or calibration occurs here."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import statistics
import time
from typing import Callable

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


def verify_bytes(path: Path, digest: str) -> bytes:
    if not isinstance(digest, str) or re.fullmatch(r'[a-f0-9]{64}', digest) is None:
        raise ValueError('An explicit lowercase SHA-256 pin is required')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"Frozen bytes changed: {path}")
    return data


def verify_freeze(
    freeze_path: Path,
    freeze_sha256: str,
    artifacts: dict[Path, str],
) -> dict:
    """Verify the immutable freeze record and externally recorded artifact digests."""
    freeze = json.loads(verify_bytes(freeze_path, freeze_sha256))
    if not isinstance(freeze, dict) or not artifacts:
        raise ValueError("A freeze record and artifact digests are required")
    for path, digest in artifacts.items():
        verify_bytes(path, digest)
    return freeze


def verify_frozen_bundle(root: Path, freeze_path: Path, pin: str) -> tuple[dict, dict, list[dict]]:
    """Check every frozen input before opening any held-out image pixels."""
    root = root.resolve()
    freeze = json.loads(verify_bytes(freeze_path, pin))
    if freeze.get('schema_version') != 1 or freeze.get('selection_used_test') is not False:
        raise ValueError('Expected a schema-1 freeze explicitly excluding test selection')
    artifacts, reports = root / 'artifacts/inspection', root / 'reports/inspection'
    recovery_format = isinstance(freeze.get('files'), dict)
    if recovery_format:
        files = freeze['files']
        required = {'src/meshlens/inspection_input.py', 'web/inspection_input.js',
                    'src/meshlens/texture_detector.py', 'web/texture_detector.js',
                    'artifacts/inspection/detector-model.json', 'artifacts/inspection/detector.json',
                    'artifacts/inspection/calibration.json', 'reports/inspection/protocol.json',
                    'reports/inspection/selection.json', 'data/manifest.csv'}
        if not required.issubset(files):
            raise ValueError('The recovery freeze omits required artifact/source digests')
        for relative, entry in files.items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError('A frozen file escapes the bundle')
            content = verify_bytes(path, entry['sha256'])
            if type(entry['bytes']) is not int or entry['bytes'] != len(content):
                raise ValueError('Frozen file byte counts differ')
        freeze = {**freeze, 'metadata_sha256': files['artifacts/inspection/detector.json']['sha256'],
                  'calibration_sha256': files['artifacts/inspection/calibration.json']['sha256'],
                  'protocol_sha256': files['reports/inspection/protocol.json']['sha256'],
                  'selection_sha256': files['reports/inspection/selection.json']['sha256'],
                  'source_manifest_sha256': files['data/manifest.csv']['sha256'],
                  'model_bytes': files['artifacts/inspection/detector-model.json']['bytes'],
                  'preprocessing': 'area-rgb8-v1',
                  'source_code': {key: files[key]['sha256'] for key in required if key.startswith(('src/', 'web/'))}}
    metadata = json.loads(verify_bytes(artifacts / 'detector.json', freeze['metadata_sha256']))
    calibration = json.loads(verify_bytes(artifacts / 'calibration.json', freeze['calibration_sha256']))
    protocol = json.loads(verify_bytes(reports / 'protocol.json', freeze['protocol_sha256']))
    selection = json.loads(verify_bytes(reports / 'selection.json', freeze['selection_sha256']))
    manifest_bytes = verify_bytes(root / 'data/manifest.csv', freeze['source_manifest_sha256'])
    exported = metadata['export']
    filename = exported['model_file']
    if not isinstance(filename, str) or re.fullmatch(r'[A-Za-z0-9_.-]+', filename) is None:
        raise ValueError('Frozen model filename must be a plain basename')
    model = verify_bytes(artifacts / filename, freeze['model_sha256'])
    if (len(model) != freeze['model_bytes'] or len(model) != exported['model_bytes']
            or exported['model_sha256'] != freeze['model_sha256']):
        raise ValueError('Frozen model byte identity differs')
    if (metadata['model_version'] != freeze['model_version'] or metadata['threshold'] != freeze['threshold']
            or metadata['preprocessing'] != freeze['preprocessing'] or metadata['preprocessing'] != 'area-rgb8-v1'
            or metadata['decision'] != 'strict-greater-than'):
        raise ValueError('The frozen input/decision contracts disagree')
    if recovery_format:
        if (protocol.get('conditions') != list(STRESSES) or protocol.get('selection_used_test') is not False
                or protocol.get('calibration_used_test') is not False or protocol.get('prior_evaluation_known') is not True
                or protocol.get('new_blind_validation') is not False
                or protocol.get('algorithm_changed_after_prior_test') is not False):
            raise ValueError('The recovery protocol changed or incorrectly claims blind evaluation')
        selected = json.loads(model)
        if (selection['data_manifest_sha256'] != freeze['source_manifest_sha256']
                or selection['development_manifest_sha256'] != metadata['dataset']['development_manifest_sha256']
                or any(selection[key] != selected[key] for key in ('kind', 'image_size', 'variant', 'tail_fraction', 'fit_scale'))):
            raise ValueError('Recovered selection and frozen model differ')
    else:
        if (protocol.get('declared_before_candidate_test_evaluation') is not True
                or protocol['dataset_manifest_sha256'] != freeze['source_manifest_sha256']
                or protocol['held_out']['stress_variants'] != list(STRESSES)):
            raise ValueError('The held-out protocol changed')
        if (selection.get('selection_used_test') is not False
                or selection['selected_model_sha256'] != freeze['model_sha256']
                or selection['selected_model_version'] != freeze['model_version']
                or selection['source_manifest_sha256'] != freeze['source_manifest_sha256']
                or selection['development_manifest_sha256'] != protocol['development_manifest_sha256']):
            raise ValueError('Selection provenance differs')
    sources = freeze.get('source_code')
    if not isinstance(sources, dict) or not sources:
        raise ValueError('Frozen numerical source digests are required')
    for relative, digest in sources.items():
        source = (root / relative).resolve()
        if not source.is_relative_to(root):
            raise ValueError('A frozen source path escapes the bundle')
        verify_bytes(source, digest)
    rows = list(csv.DictReader(io.StringIO(manifest_bytes.decode('utf-8'))))
    if len({row['path'] for row in rows}) != len(rows):
        raise ValueError('Dataset image paths must be unique')
    for row in rows:
        if row['label'] not in ('0', '1'):
            raise ValueError('Dataset labels must be binary')
        row['label'] = int(row['label'])
    normals = {row['path']: row for row in rows if row['split'] == 'calibration' and row['label'] == 0}
    if not isinstance(calibration, list) or len(calibration) != 52 or len(normals) != 52:
        raise ValueError('Expected exactly 52 normal calibration images')
    seen, scores = set(), []
    for row in calibration:
        source = normals.get(row['path'])
        score = row['score']
        if (source is None or row['path'] in seen or row['sha256'] != source['sha256']
                or type(score) not in (int, float) or not math.isfinite(score) or score < 0):
            raise ValueError('Invalid calibration provenance or scores')
        seen.add(row['path'])
        scores.append(score)
    rank = math.ceil((len(scores) + 1) * .95)
    calibration_metadata = metadata['calibration']
    if (rank != 51 or sorted(scores)[rank - 1] != freeze['threshold']
            or calibration_metadata['count'] != 52 or calibration_metadata['alpha'] != .05
            or calibration_metadata['order_statistic_rank'] != rank
            or calibration_metadata['scores_sha256'] != freeze['calibration_sha256']):
        raise ValueError('Threshold is not the preregistered normal calibration quantile')
    held_out = [row for row in rows if row['split'] == 'test']
    if len(held_out) != 78 or sum(row['label'] for row in held_out) != 57:
        raise ValueError('Expected 78 held-out images including 57 defective images')
    return freeze, metadata, held_out


def shift_view(image: Image.Image) -> Image.Image:
    """Translate a view by 8 and 4 pixels at the 256-pixel reference scale."""
    pixels = np.asarray(image)
    width, height = image.size
    dx = max(1, round(width * 8 / 256))
    dy = max(1, round(height * 4 / 256))
    padded = np.pad(pixels, ((dy, dy), (dx, dx), (0, 0)), mode="reflect")
    return Image.fromarray(padded[0:height, 0:width].copy())


def jpeg_reencode(image: Image.Image) -> Image.Image:
    with io.BytesIO() as buffer:
        image.save(buffer, format="JPEG", quality=75, subsampling=2)
        buffer.seek(0)
        with Image.open(buffer) as reloaded:
            return reloaded.convert("RGB")


STRESSES: dict[str, Callable[[Image.Image], Image.Image]] = {
    "original": lambda image: image,
    "brightness_070": lambda image: ImageEnhance.Brightness(image).enhance(0.70),
    "brightness_130": lambda image: ImageEnhance.Brightness(image).enhance(1.30),
    "shift_8x4_ref256": shift_view,
    "blur_sigma_0p8_ref256": lambda image: image.filter(
        ImageFilter.GaussianBlur(0.8 * min(image.size) / 256)
    ),
    "jpeg_quality_75": jpeg_reencode,
}


def wilson(successes: int, n: int) -> list[float] | None:
    if n == 0:
        return None
    z = statistics.NormalDist().inv_cdf(0.975)
    p = successes / n
    scale = 1 + z**2 / n
    middle = (p + z**2 / (2 * n)) / scale
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / scale
    return [max(0.0, middle - half), min(1.0, middle + half)]


def summarize(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError('At least one evaluated image is required')
    positive = [row for row in rows if row["label"] == 1]
    negative = [row for row in rows if row["label"] == 0]
    positive_alerts = sum(row["decision"] == "review" for row in positive)
    negative_alerts = sum(row["decision"] == "review" for row in negative)
    positive_unusable = sum(row["decision"] == "unusable" for row in positive)
    negative_unusable = sum(row["decision"] == "unusable" for row in negative)
    positive_scores = [row["score"] for row in positive if row["score"] is not None and row['decision'] != 'unusable']
    negative_scores = [row["score"] for row in negative if row["score"] is not None and row['decision'] != 'unusable']
    auc = None
    if positive_scores and negative_scores:
        pair_wins = sum(
            1 if a > b else 0.5 if a == b else 0
            for a in positive_scores for b in negative_scores
        )
        auc = pair_wins / (len(positive_scores) * len(negative_scores))
    timing = [row["wall_ms"] for row in rows]
    return {
        "images": len(rows),
        "defective": len(positive),
        "clean": len(negative),
        "defect_alerts": positive_alerts,
        "defects_in_range": len(positive) - positive_alerts - positive_unusable,
        "clean_in_range": len(negative) - negative_alerts - negative_unusable,
        "clean_alerts": negative_alerts,
        "defective_unusable": positive_unusable,
        "clean_unusable": negative_unusable,
        "defect_recall": positive_alerts / len(positive) if positive else None,
        "recall_wilson_95": wilson(positive_alerts, len(positive)),
        "clean_false_alarm_rate": negative_alerts / len(negative) if negative else None,
        "false_alarm_wilson_95": wilson(negative_alerts, len(negative)),
        "clean_review_or_unusable_rate": (
            (negative_alerts + negative_unusable) / len(negative) if negative else None
        ),
        "coverage": (len(rows) - positive_unusable - negative_unusable) / len(rows),
        "scored_images": len(positive_scores) + len(negative_scores),
        "scored_images_auroc": auc,
        "score_wall_ms_median": statistics.median(timing),
        "score_wall_ms_p95": float(np.quantile(timing, 0.95)),
    }


def score_prediction(
    prediction: float | tuple[float | None, str | None], cutoff: float
) -> tuple[float | None, str, str | None]:
    if isinstance(prediction, tuple):
        score, unusable = prediction
    else:
        score, unusable = prediction, None
    if score is not None:
        if type(score) is bool or not math.isfinite(score) or score < 0:
            raise ValueError("Anomaly scores must be finite and nonnegative")
        score = float(score)
    if unusable is not None:
        if not isinstance(unusable, str) or not unusable.strip():
            raise ValueError("An unusable image requires a reason")
        return score, "unusable", unusable
    if score is None:
        raise ValueError("An image without a score requires an unusable reason")
    return score, "review" if score > cutoff else "within_range", None


def summarize_conditions(records: list[dict], variants: list[str]) -> dict:
    metrics = {}
    for name in variants:
        current = [row for row in records if row['variant'] == name]
        groups = defaultdict(list)
        for row in current:
            groups[row['defect_type']].append(row)
        metrics[name] = {**summarize(current),
                         'per_defect': {key: summarize(group) for key, group in groups.items()},
                         'unusable_reasons': dict(Counter(row['unusable_reason'] for row in current
                                                         if row['unusable_reason']))}
    return metrics


def evaluate(
    rows: list[dict],
    source_root: Path,
    score_image: Callable[[Image.Image], float | tuple[float | None, str | None]],
    cutoff: float,
    *,
    stress: bool,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Load verified inputs and score without passing file paths or labels to the detector."""
    if not rows or type(cutoff) is bool or not math.isfinite(cutoff) or cutoff < 0:
        raise ValueError("The evaluation requires images and a finite nonnegative cutoff")
    if len({row['path'] for row in rows}) != len(rows):
        raise ValueError('Evaluation paths must be unique')
    source_root = source_root.resolve()
    records = []
    transforms = STRESSES if stress else {"original": STRESSES["original"]}
    for row in rows:
        label = row["label"]
        if type(label) is not int or label not in (0, 1):
            raise ValueError("Evaluation labels must be integers 0 and 1")
        path = (source_root / row["path"]).resolve()
        if not path.is_relative_to(source_root):
            raise ValueError(f"Image path escapes evaluation root: {row['path']}")
        content = verify_bytes(path, row["sha256"])
        with Image.open(io.BytesIO(content)) as source:
            image = source.copy()
        for name, transform in transforms.items():
            sample = transform(image.copy() if name == "original" else image.convert("RGB"))
            started = time.perf_counter()
            result = score_image(sample)
            elapsed = (time.perf_counter() - started) * 1000
            score, decision, unusable = score_prediction(result, cutoff)
            records.append({
                "path": row["path"], "sha256": row["sha256"], "label": label,
                "defect_type": row["defect_type"], "variant": name,
                "score": score, "decision": decision, "unusable_reason": unusable,
                "wall_ms": elapsed,
            })
            if progress:
                progress(len(records), len(rows) * len(transforms))
    metrics = summarize_conditions(records, list(transforms))
    return {"cutoff": cutoff, "metrics": metrics, "records": records}
