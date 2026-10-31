"""Recompute published operating points and metrics from per-image records."""
from collections import Counter
import csv
import hashlib
import json
import math

import pytest
from sklearn.metrics import average_precision_score, roc_auc_score

from meshlens.core import read_manifest


def read_csv(path):
    with path.open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def test_frozen_threshold_comes_only_from_reserved_normal_calibration(project_root):
    manifest = {item['path']: item for item in read_manifest(project_root)}
    rows = read_csv(project_root / 'reports/calibration_scores.csv')
    metadata = json.loads((project_root / 'artifacts/metadata.json').read_text())
    frozen = json.loads((project_root / 'reports/frozen_configuration.json').read_text())
    expected_paths = {path for path, item in manifest.items() if item['split'] == 'calibration'}
    assert {item['path'] for item in rows} == expected_paths
    assert len(rows) == len(expected_paths) == 52
    assert all(item['split'] == 'calibration' and int(item['label']) == 0 for item in rows)
    rank = math.ceil((len(rows) + 1) * (1 - metadata['calibration']['alpha']))
    threshold = sorted(float(item['score']) for item in rows)[rank - 1]
    assert metadata['threshold'] == pytest.approx(threshold, abs=1e-12)
    assert frozen['threshold'] == pytest.approx(threshold, abs=1e-12)
    assert frozen['calibration_order_rank'] == math.ceil((len(rows) + 1) * .95) == 51
    assert frozen['calibration_score_sha256'] == hashlib.sha256((project_root / 'reports/calibration_scores.csv').read_bytes()).hexdigest()
    assert frozen['checkpoint_sha256'] == hashlib.sha256((project_root / 'artifacts/checkpoint.pt').read_bytes()).hexdigest()


def test_published_test_metrics_match_every_frozen_per_image_decision(project_root):
    manifest = {item['path']: item for item in read_manifest(project_root)}
    rows = read_csv(project_root / 'reports/test_scores.csv')
    report = json.loads((project_root / 'reports/metrics.json').read_text())
    metadata = json.loads((project_root / 'artifacts/metadata.json').read_text())
    expected_paths = {path for path, item in manifest.items() if item['split'] == 'test'}
    assert {item['path'] for item in rows} == expected_paths
    assert len(rows) == len(expected_paths) == 78
    labels, scores, counts = [], [], Counter()
    for item in rows:
        label, predicted = int(item['label']), int(item['prediction'])
        score, threshold = float(item['score']), float(item['threshold'])
        assert item['split'] == 'test'
        assert label == int(manifest[item['path']]['label'])
        assert predicted == int(score > threshold)
        assert threshold == metadata['threshold']
        counts[(label, predicted)] += 1
        labels.append(label)
        scores.append(score)
    measured = report['model']
    tn, fp, fn, tp = (counts[(0, 0)], counts[(0, 1)], counts[(1, 0)], counts[(1, 1)])
    assert [measured[key] for key in ['true_negative', 'false_positive', 'false_negative', 'true_positive']] == [tn, fp, fn, tp]
    assert measured['precision'] == pytest.approx(tp / (tp + fp) if tp + fp else 0)
    assert measured['recall'] == pytest.approx(tp / (tp + fn))
    assert measured['f1'] == pytest.approx(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0)
    assert measured['accuracy'] == pytest.approx((tp + tn) / len(rows))
    assert measured['auroc'] == pytest.approx(roc_auc_score(labels, scores))
    assert measured['average_precision'] == pytest.approx(average_precision_score(labels, scores))
    assert metadata['metrics'] == measured
    assert report['test_normal'] == tn + fp == 21
    assert report['test_defect'] == fn + tp == 57
    for defect, summary in report['per_defect'].items():
        subset = [item for item in rows if item['defect_type'] == defect]
        assert summary['count'] == len(subset)
        assert summary['flagged'] == sum(int(item['prediction']) for item in subset)
        assert summary['flag_rate'] == pytest.approx(summary['flagged'] / len(subset))


def test_pca_baseline_has_its_own_normal_only_calibration_and_measured_ranking(project_root):
    manifest = {item['path']: item for item in read_manifest(project_root)}
    calibration = read_csv(project_root / 'reports/baseline_calibration_scores.csv')
    report = json.loads((project_root / 'reports/metrics.json').read_text())
    expected_paths = {path for path, item in manifest.items() if item['split'] == 'calibration'}
    assert {item['path'] for item in calibration} == expected_paths
    assert len(calibration) == len(expected_paths)
    assert all(int(item['label']) == 0 for item in calibration)
    rank = math.ceil((len(calibration) + 1) * .95)
    threshold = sorted(float(item['score']) for item in calibration)[rank - 1]
    assert report['baseline_patch_pca']['threshold'] == pytest.approx(threshold, abs=1e-12)
    rows = read_csv(project_root / 'reports/test_scores.csv')
    labels = [int(item['label']) for item in rows]
    scores = [float(item['pca_score']) for item in rows]
    measured = report['baseline_patch_pca']
    assert measured['auroc'] == pytest.approx(roc_auc_score(labels, scores))
    assert measured['average_precision'] == pytest.approx(average_precision_score(labels, scores))
    counts = Counter((label, int(score > threshold)) for label, score in zip(labels, scores, strict=True))
    tn, fp, fn, tp = (counts[(0, 0)], counts[(0, 1)], counts[(1, 0)], counts[(1, 1)])
    assert [measured[key] for key in ['true_negative', 'false_positive', 'false_negative', 'true_positive']] == [tn, fp, fn, tp]
    assert measured['precision'] == pytest.approx(tp / (tp + fp) if tp + fp else 0)
    assert measured['recall'] == pytest.approx(tp / (tp + fn))
    assert measured['f1'] == pytest.approx(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0)
    assert measured['accuracy'] == pytest.approx((tn + tp) / len(rows))


def test_bundled_samples_are_real_labeled_test_images_with_recorded_digests(project_root):
    samples = json.loads((project_root / 'artifacts/samples.json').read_text())
    manifest = {item['path']: item for item in read_manifest(project_root)}
    scores = {item['path']: item for item in read_csv(project_root / 'reports/test_scores.csv')}
    assert samples['count'] == len(samples['samples']) == 18
    assert any(int(sample['label']) == 0 for sample in samples['samples'])
    assert any(int(sample['label']) == 1 for sample in samples['samples'])
    filenames = set()
    for sample in samples['samples']:
        assert sample['filename'] not in filenames
        filenames.add(sample['filename'])
        original = manifest[sample['source_path']]
        assert original['split'] == 'test'
        assert int(original['label']) == int(sample['label'])
        assert sample['expected_score'] == pytest.approx(float(scores[sample['source_path']]['score']), abs=1e-10)
        assert bool(sample['expected_anomaly']) == bool(int(scores[sample['source_path']]['prediction']))
        file = project_root / 'artifacts/samples' / sample['filename']
        assert file.is_file()
        assert sample['sha256'] == hashlib.sha256(file.read_bytes()).hexdigest()
