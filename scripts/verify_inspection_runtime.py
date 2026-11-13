"""Check18 served gallery PNGs; --full-test also checks all78 official sources."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from meshlens.inspection import InspectionDetector  # noqa: E402 -- source bootstrap
from meshlens.inspection_evaluation import verify_bytes, verify_frozen_bundle  # noqa: E402


def digest(content):
    return hashlib.sha256(content).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze-sha256')
    parser.add_argument('--scope', choices=('official', 'gallery', 'all'))
    parser.add_argument('--full-test', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.full_test and args.scope not in (None, 'all'):
        parser.error('--full-test conflicts with a narrower --scope')
    scope = 'all' if args.full_test else args.scope or 'gallery'
    frozen_path = ROOT / 'reports/inspection/frozen_configuration.json'
    pin = args.freeze_sha256 or digest(frozen_path.read_bytes())
    freeze, metadata, official = verify_frozen_bundle(ROOT, frozen_path, pin)
    detector = InspectionDetector(ROOT)
    if not detector.available or metadata['runtime'] != 'texture-js':
        raise ValueError('The frozen portable texture detector is unavailable')
    model = json.loads((ROOT / 'artifacts/inspection' / metadata['export']['model_file']).read_bytes())
    cases = [('official', ROOT, row) for row in official] if scope in ('official', 'all') else []
    gallery_sha = None
    if scope in ('gallery', 'all'):
        base = ROOT / 'artifacts/inspection'
        content = (base / 'samples.json').read_bytes()
        gallery_sha = digest(content)
        samples = json.loads(content)['samples']
        if len(samples) != 18 or len({row['filename'] for row in samples}) != 18:
            raise ValueError('Expected18 distinct gallery replays')
        sources = {row['path']: row for row in official}
        for row in samples:
            source = sources.get(row['source_path'])
            if (source is None or source['sha256'] != row['source_sha256'] or source['label'] != row['label']
                    or source['defect_type'] != row['defect_type'] or row['model_version'] != freeze['model_version']
                    or row['preprocessing'] != metadata['preprocessing']
                    or re.fullmatch(r'[A-Za-z0-9_-]+\.png', row['filename']) is None
                    or type(row['expected_anomaly']) is not bool
                    or row['expected_anomaly'] != (row['expected_score'] > freeze['threshold'])):
                raise ValueError('Gallery provenance differs from the frozen detector')
            cases.append(('gallery', base, {**row, 'path': 'samples/' + row['filename']}))
    with tempfile.TemporaryDirectory(prefix='meshlens-parity-') as temporary:
        directory = Path(temporary)
        samples = []
        for index, (source_scope, base, row) in enumerate(cases):
            path = (base / row['path']).resolve()
            if not path.is_relative_to(base.resolve()):
                raise ValueError('Image path escapes the parity bundle')
            verify_bytes(path, row['sha256'])
            with Image.open(path) as image:
                if source_scope == 'gallery' and (image.format != 'PNG' or image.mode != 'RGB'
                                                  or image.size != (metadata['image_size'], metadata['image_size'])):
                    raise ValueError('Gallery image is not a canonicalRGB stillPNG')
                result = detector.inspect_image(image)
                native = np.asarray(ImageOps.exif_transpose(image).convert('RGBA'))
            if result.canonical_input is None:
                raise ValueError('Input did not reach canonical preprocessing')
            if source_scope == 'gallery' and (result.score != row['expected_score']
                                              or result.is_anomaly != row['expected_anomaly']
                                              or not np.array_equal(result.canonical_input, native[..., :3])):
                raise ValueError('Served gallery pixels changed the original frozen outcome')
            native.tofile(directory / f'{index}.rgba')
            result.canonical_input.tofile(directory / f'{index}.rgb')
            if result.status == 'scored':
                result.anomaly_map.astype('<f8').tofile(directory / f'{index}.map')
            samples.append({'id': row['path'], 'scope': source_scope, 'width': native.shape[1], 'height': native.shape[0],
                            'rgba_file': str(directory / f'{index}.rgba'), 'rgb_file': str(directory / f'{index}.rgb'),
                            'map_file': str(directory / f'{index}.map'), 'score': result.score, 'reason': result.reason})
            if (index + 1) % 10 == 0 or index + 1 == len(cases):
                print(f'PreparedPython evidence {index + 1}/{len(cases)}', file=sys.stderr, flush=True)
        inputs = directory / 'inputs.json'
        inputs.write_text(json.dumps({'model': model, 'threshold': freeze['threshold'], 'samples': samples}, allow_nan=False))
        child = subprocess.run(['node', str(ROOT / 'scripts/verify_inspection_runtime.mjs'), str(inputs)],
                               capture_output=True, text=True, timeout=1800, check=False)
        if not child.stdout.strip():
            raise RuntimeError(child.stderr.strip() or 'No portable runtime report')
        report = json.loads(child.stdout)
    verify_frozen_bundle(ROOT, frozen_path, pin)
    if gallery_sha and digest((ROOT / 'artifacts/inspection/samples.json').read_bytes()) != gallery_sha:
        raise ValueError('Gallery changed during verification')
    report.update({'schema_version': 1, 'freeze_sha256': pin, 'freeze_pin_was_explicit': bool(args.freeze_sha256),
                   'model_sha256': freeze['model_sha256'], 'model_version': freeze['model_version'], 'scope': scope,
                   'gallery_manifest_sha256': gallery_sha, 'threshold': freeze['threshold'],
                   'verified_at': datetime.now(timezone.utc).isoformat(),
                   'python_implementation_sha256': freeze['source_code']['src/meshlens/texture_detector.py'],
                   'browser_implementation_sha256': freeze['source_code']['web/texture_detector.js'],
                   'verification_script_sha256': digest(Path(__file__).read_bytes()),
                   'map_comparison': 'FullPython Float64 versus shippedJavaScript Float32 map',
                   'input_decode_note': 'Pillow nativeRGBA for numerical agreement; actual browser decoder validation is separate.',
                   'gallery_note': 'Gallery replays official benchmark images; it is not an independent cohort.'})
    output = args.output or ROOT / ('reports/inspection/gallery-runtime-parity.json' if scope == 'gallery'
                                   else 'reports/inspection/runtime_parity.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'records'}, indent=2))
    if child.returncode or not report['passed']:
        raise SystemExit('Frozen portable runtime verification failed')


if __name__ == '__main__':
    main()
