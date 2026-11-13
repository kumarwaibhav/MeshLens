"""Evaluate the SHA-pinned frozen detector; no model or threshold tuning occurs."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from meshlens.inspection_evaluation import STRESSES, evaluate, summarize_conditions, verify_frozen_bundle  # noqa: E402 -- source bootstrap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=ROOT)
    parser.add_argument('--freeze', type=Path)
    parser.add_argument('--freeze-sha256', required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--original-only', action='store_true')
    parser.add_argument('--workers', type=int, default=1, choices=range(1, 9), help='Independent image workers; timings share host resources')
    args = parser.parse_args()
    root = args.bundle.resolve()
    freeze_path = args.freeze or root / 'reports/inspection/frozen_configuration.json'
    freeze, metadata, rows = verify_frozen_bundle(root, freeze_path, args.freeze_sha256)
    from meshlens.inspection import InspectionDetector
    detector = InspectionDetector(root)
    if not detector.available:
        raise ValueError('The pinned detector is unavailable')
    def score_image(image):
        result = detector.inspect_image(image)
        if result.model_version != freeze['model_version'] or result.model_sha256 != freeze['model_sha256']:
            raise ValueError('Runtime model identity differs from the freeze')
        if result.status == 'inconclusive':
            if not result.reason:
                raise ValueError('Inconclusive inputs require a reason')
            return None, result.reason
        if result.status != 'scored' or result.threshold != freeze['threshold']:
            raise ValueError('Runtime decision contract differs from the freeze')
        if result.is_anomaly is not (result.score > freeze['threshold']):
            raise ValueError('Runtime decisions differ from strict greater-than')
        pixels, anomaly = np.asarray(result.canonical_input), np.asarray(result.anomaly_map)
        size, map_size = metadata['image_size'], metadata['outputs']['map_size']
        if pixels.dtype != np.uint8 or pixels.shape != (size, size, 3):
            raise ValueError('Invalid canonical input array')
        if anomaly.shape != (map_size, map_size) or not np.isfinite(anomaly).all() or np.any(anomaly < 0):
            raise ValueError('Invalid anomaly map')
        return result.score
    def progress(done, total):
        if done % 12 == 0 or done == total:
            print(f'Scored frozen inputs {done}/{total}', file=sys.stderr, flush=True)
    if args.workers == 1:
        evaluation = evaluate(rows, root, score_image, freeze['threshold'], stress=not args.original_only, progress=progress)
    else:
        chunks = {}
        completed = 0
        total = len(rows) * (1 if args.original_only else len(STRESSES))
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(evaluate, [row], root, score_image, freeze['threshold'],
                                   stress=not args.original_only): index for index, row in enumerate(rows)}
            for future in as_completed(futures):
                chunk = future.result()
                chunks[futures[future]] = chunk['records']
                completed += len(chunk['records'])
                progress(completed, total)
        records = [record for index in range(len(rows)) for record in chunks[index]]
        variants = ['original'] if args.original_only else list(STRESSES)
        evaluation = {'cutoff': freeze['threshold'], 'records': records,
                      'metrics': summarize_conditions(records, variants)}
    verify_frozen_bundle(root, freeze_path, args.freeze_sha256)
    report = {'schema_version': 1, 'freeze_sha256': args.freeze_sha256,
              'model_sha256': freeze['model_sha256'], 'model_version': freeze['model_version'],
              'evaluated_at': datetime.now(timezone.utc).isoformat(), 'threshold_was_tuned': False,
              'source_manifest_sha256': freeze['source_manifest_sha256'], 'protocol_sha256': freeze['protocol_sha256'],
              'evaluation_source_sha256': hashlib.sha256((ROOT / 'src/meshlens/inspection_evaluation.py').read_bytes()).hexdigest(),
              'evaluation_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'metric_policy': 'Inconclusive defects count as misses; inconclusive clean inputs are not correct clean decisions. AUROC excludes inconclusive inputs.',
              'stress_note': 'Perturbed versions reuse the same 78 source images; they are not independent physical parts.',
              'workers': args.workers, 'timing_note': 'Wall timings include input preprocessing and share host resources; not factory throughput qualification.',
              'evaluation': evaluation}
    output = args.output or root / 'reports/inspection/independent_evaluation.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'output': str(output.resolve()), 'records': len(evaluation['records']),
                      'original': evaluation['metrics']['original']}, indent=2))


if __name__ == '__main__':
    main()
