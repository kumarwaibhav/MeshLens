#!/usr/bin/env python3
"""Compare a frozen checkpoint across isolated PyTorch runtimes.

Both phases use the identical checkpoint, canonical preprocessing, saved image
roles and frozen threshold. No model is retrained and no threshold is retuned.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run_phase(phase: str, directory: Path) -> int:
    import numpy as np
    from PIL import Image
    import torch
    from meshlens.core import preprocess_image, read_manifest, residual_score
    from meshlens.model import load_checkpoint

    torch.set_num_threads(4)
    model, _ = load_checkpoint(ROOT / 'artifacts/checkpoint.pt')
    metadata = json.loads((ROOT / 'artifacts/metadata.json').read_text())
    threshold = float(metadata['threshold'])
    fraction = float(metadata.get('score', {}).get('top_fraction', metadata.get('top_fraction', .01)))
    rows = [item for item in read_manifest(ROOT) if item['split'] in {'calibration', 'test'}]
    if Counter(item['split'] for item in rows) != {'calibration': 52, 'test': 78}:
        raise ValueError('The complete 52 calibration and 78 official test images are required.')
    digest = hashlib.sha256((ROOT / 'artifacts/checkpoint.pt').read_bytes()).hexdigest()
    if phase == 'reference':
        published = {}
        for filename in ['calibration_scores.csv', 'test_scores.csv']:
            with (ROOT / 'reports' / filename).open(newline='', encoding='utf-8') as stream:
                for item in csv.DictReader(stream):
                    if item['path'] in published:
                        raise ValueError('Published calibration and test records overlap.')
                    published[item['path']] = float(item['score'])
        if set(published) != {item['path'] for item in rows}:
            raise ValueError('Published calibration/test scores do not cover the complete frozen comparison.')
        records = []
        for index, row in enumerate(rows):
            with Image.open(ROOT / row['path']) as image:
                values = preprocess_image(image)
            with torch.inference_mode():
                reconstruction = model(torch.from_numpy(values[None])).numpy()[0]
            score, _ = residual_score(values, reconstruction, fraction)
            published_error = abs(score - published[row['path']])
            if published_error > 1e-12:
                raise ValueError(f'Original runtime no longer reproduces published image score: {row["path"]}')
            output_file = f'{index:03}-torch-reference.npy'
            np.save(directory / output_file, reconstruction, allow_pickle=False)
            records.append({'path': row['path'], 'split': row['split'], 'score': score,
                            'prediction': bool(score > threshold), 'output_file': output_file,
                            'published_score': published[row['path']], 'published_score_abs_error': published_error,
                            'input_tensor_sha256': hashlib.sha256(values.tobytes(order='C')).hexdigest()})
        baseline = {'torch_version': torch.__version__, 'checkpoint_sha256': digest,
                    'torch_module_path': torch.__file__,
                    'threshold': threshold, 'top_fraction': fraction, 'records': records}
        (directory / 'reference.json').write_text(json.dumps(baseline, indent=2) + '\n')
        print(f'Reference runtime {torch.__version__}: {len(records)} frozen-image reconstructions saved.', flush=True)
        return 0
    reference = json.loads((directory / 'reference.json').read_text())
    if reference['checkpoint_sha256'] != digest:
        raise ValueError('Checkpoint changed between runtime comparison phases.')
    if reference['threshold'] != threshold or reference['top_fraction'] != fraction:
        raise ValueError('Frozen numerical contract changed between comparison phases.')
    records = []
    for row, original in zip(rows, reference['records'], strict=True):
        if row['path'] != original['path']:
            raise ValueError('Image manifest changed between comparison phases.')
        with Image.open(ROOT / row['path']) as image:
            values = preprocess_image(image)
        input_digest = hashlib.sha256(values.tobytes(order='C')).hexdigest()
        if input_digest != original['input_tensor_sha256']:
            raise ValueError('Canonical input tensor changed between runtime comparison phases.')
        with torch.inference_mode():
            reconstruction = model(torch.from_numpy(values[None])).numpy()[0]
        expected = np.load(directory / original['output_file'], allow_pickle=False)
        score, _ = residual_score(values, reconstruction, fraction)
        records.append({'path': row['path'], 'split': row['split'],
                        'input_tensor_sha256': input_digest,
                        'max_reconstruction_abs_error': float(np.max(np.abs(reconstruction - expected))),
                        'reference_score': original['score'], 'patched_runtime_score': score,
                        'published_score': original['published_score'],
                        'reference_published_score_abs_error': original['published_score_abs_error'],
                        'score_abs_error': abs(score - original['score']),
                        'reference_margin_to_threshold': original['score'] - threshold,
                        'patched_margin_to_threshold': score - threshold,
                        'reference_anomaly': original['prediction'], 'patched_runtime_anomaly': bool(score > threshold)})
    changed = sum(item['reference_anomaly'] != item['patched_runtime_anomaly'] for item in records)
    changed_by_split = {split: sum(item['split'] == split and item['reference_anomaly'] != item['patched_runtime_anomaly']
                                  for item in records) for split in ['calibration', 'test']}
    maximum_output_error = max(item['max_reconstruction_abs_error'] for item in records)
    maximum_score_error = max(item['score_abs_error'] for item in records)
    report = {'status': 'passed' if changed == 0 and maximum_output_error <= 2e-5 and maximum_score_error <= 2e-6 else 'failed',
              'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'reference_torch_version': reference['torch_version'], 'patched_torch_version': torch.__version__,
              'reference_torch_module_path': reference['torch_module_path'], 'patched_torch_module_path': torch.__file__,
              'checkpoint_sha256': digest, 'threshold': threshold, 'top_fraction': fraction,
              'images': len(records), 'split_counts': dict(Counter(item['split'] for item in rows)),
              'max_reconstruction_abs_error': maximum_output_error,
              'max_score_abs_error': maximum_score_error, 'changed_decisions': changed,
              'max_reference_published_score_abs_error': max(item['reference_published_score_abs_error'] for item in records),
              'changed_decisions_by_split': changed_by_split,
              'numerically_within_tolerance': maximum_output_error <= 2e-5 and maximum_score_error <= 2e-6,
              'official_test_decisions_unchanged': changed_by_split['test'] == 0,
              'calibration_reference_equal_to_threshold': sum(item['split'] == 'calibration' and item['reference_margin_to_threshold'] == 0 for item in records),
              'calibration_patched_equal_to_threshold': sum(item['split'] == 'calibration' and item['patched_margin_to_threshold'] == 0 for item in records),
              'changed_decision_paths': [item['path'] for item in records if item['reference_anomaly'] != item['patched_runtime_anomaly']],
              'minimum_official_test_reference_absolute_margin': min(abs(item['reference_margin_to_threshold']) for item in records if item['split'] == 'test'),
              'reconstruction_tolerance': 2e-5, 'score_tolerance': 2e-6,
              'threshold_policy': 'The threshold from the original training runtime remains frozen. Exact ties use strict score > threshold; numerical tolerance does not alter or retune any decision.',
              'scope': 'Same frozen checkpoint and 130 canonical image tensors across isolated CPU runtimes. This does not assert that retraining under a different runtime produces identical weights.',
              'records': records}
    (ROOT / 'reports/runtime-upgrade-validation.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(f'Patched runtime {torch.__version__}: {report["status"]}, {len(records)} images, {changed} changed decisions, max score error {maximum_score_error}.', flush=True)
    return 0 if report['status'] == 'passed' else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-deps', type=Path, help='Original training runtime package directory.')
    parser.add_argument('--patched-deps', type=Path, help='Separate patched PyTorch package directory.')
    parser.add_argument('--phase', choices=['reference', 'compare'], help=argparse.SUPPRESS)
    parser.add_argument('--temporary-dir', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.phase:
        if args.temporary_dir is None:
            parser.error('Internal comparison phase requires a temporary directory.')
        return run_phase(args.phase, args.temporary_dir)
    if args.base_deps is None or args.patched_deps is None:
        parser.error('Both --base-deps and --patched-deps are required; packages are never installed implicitly.')
    with tempfile.TemporaryDirectory(prefix='meshlens-runtime-') as temporary:
        for phase, paths in [('reference', [args.base_deps]), ('compare', [args.patched_deps, args.base_deps])]:
            env = dict(os.environ)
            env['PYTHONPATH'] = os.pathsep.join([*(str(path.resolve()) for path in paths), str(ROOT / 'src')])
            for variable in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
                env[variable] = '4'
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--phase', phase,
                                     '--temporary-dir', temporary], cwd=ROOT, env=env, timeout=300, check=False)
            if result.returncode:
                return result.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
