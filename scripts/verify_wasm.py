#!/usr/bin/env python3
"""Compare actual WebAssembly inference with Python ORT on identical tensors.

This verifies the shipped browser numerical code, not browser image decoding,
DOM behavior, physical cameras or every browser/device combination.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import onnxruntime as ort
from PIL import Image

from meshlens.core import preprocess_image, read_manifest, residual_score

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full-test', action='store_true', help='Use all official test images when raw data is present.')
    args = parser.parse_args()
    node = shutil.which('node')
    if not node:
        raise SystemExit('Node.js is required for the actual WebAssembly backend.')
    metadata = json.loads((ROOT / 'artifacts/metadata.json').read_text())
    model = ROOT / 'artifacts/model.onnx'
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(model), sess_options=options, providers=['CPUExecutionProvider'])
    size = int(metadata['image_size'])
    fraction = float(metadata.get('score', {}).get('top_fraction', metadata.get('top_fraction', .01)))
    if args.full_test:
        rows = [item for item in read_manifest(ROOT) if item['split'] == 'test']
        sources = [(item['path'], ROOT / item['path']) for item in rows]
    else:
        gallery = json.loads((ROOT / 'artifacts/samples.json').read_text())['samples']
        sources = [(item['id'], ROOT / 'artifacts/samples' / item['filename']) for item in gallery]
    if not sources:
        raise SystemExit('A tracked real-image sample is required; no synthetic fallback is used.')
    with tempfile.TemporaryDirectory(prefix='meshlens-wasm-') as directory:
        temporary = Path(directory)
        samples = []
        for index, (identifier, filename) in enumerate(sources):
            with Image.open(filename) as image:
                values = preprocess_image(image, size=size)
            reconstruction = session.run(None, {session.get_inputs()[0].name: values[None]})[0][0]
            score, _ = residual_score(values, reconstruction, fraction)
            input_file = temporary / f'{index:03}-input.f32'
            output_file = temporary / f'{index:03}-expected.f32'
            values.astype('<f4', copy=False).tofile(input_file)
            reconstruction.astype('<f4', copy=False).tofile(output_file)
            samples.append({'id': identifier, 'input_file': str(input_file),
                            'expected_output_file': str(output_file), 'expected_score': score})
        manifest = {'model': str(model), 'shape': [1, 3, size, size], 'image_size': size,
                    'top_fraction': fraction, 'threshold': float(metadata['threshold']),
                    'reconstruction_tolerance': 3e-5, 'score_tolerance': 2e-6, 'samples': samples}
        manifest_file = temporary / 'inputs.json'
        output = temporary / 'result.json'
        manifest_file.write_text(json.dumps(manifest))
        result = subprocess.run([node, str(ROOT / 'scripts/verify_wasm.mjs'), str(manifest_file), str(output)],
                                cwd=ROOT, text=True, capture_output=True, timeout=300, check=False)
        print(result.stdout, end='')
        if result.stderr:
            print(result.stderr, end='')
        if not output.is_file():
            raise SystemExit(f'WASM verification did not produce a report (exit {result.returncode}).')
        report = json.loads(output.read_text())
    report.update({'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                   'python_onnxruntime_version': ort.__version__, 'model_sha256': hashlib.sha256(model.read_bytes()).hexdigest(),
                   'threshold': float(metadata['threshold']), 'top_fraction': fraction,
                   'input_mode': 'canonical RGB Float32 NCHW tensors shared byte-for-byte across both runtimes',
                   'sample_source': 'all official test images' if args.full_test else 'tracked preprocessed gallery images',
                   'scope': 'Actual ONNXRuntimeWeb WASM and deployed browser residual/score functions versus Python ORT. Browser decoding, image resizing, DOM interactions and physical cameras are outside this check.'})
    destination = ROOT / 'reports/wasm-parity.json'
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return 0 if report['status'] == 'passed' and result.returncode == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
