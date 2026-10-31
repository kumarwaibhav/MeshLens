#!/usr/bin/env python3
"""Run source, frozen-model and browser-math verification without retraining.

The quick path uses committed model artifacts and sample images. Add --full-data
for the complete licensed benchmark archive and per-file integrity audit.
Project owner: Kumar Waibhav AKshat <kwa.waibhav@gmail.com>.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def raw_inventory() -> dict:
    with (ROOT / 'data/manifest.csv').open(newline='', encoding='utf-8') as stream:
        images = list(csv.DictReader(stream))
    masks = json.loads((ROOT / 'data/mask_checksums.json').read_text())
    present_images = sum((ROOT / item['path']).is_file() for item in images)
    present_masks = sum((ROOT / item['path']).is_file() for item in masks)
    complete = present_images == len(images) and present_masks == len(masks)
    return {'status': 'complete' if complete else ('absent' if present_images == present_masks == 0 else 'partial'),
            'expected_images': len(images), 'available_images': present_images,
            'expected_masks': len(masks), 'available_masks': present_masks}


def observed_versions() -> dict:
    versions = {}
    for name in ['torch', 'numpy', 'Pillow', 'onnx', 'onnxruntime', 'scikit-learn', 'pytest']:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def source_hashes() -> dict:
    paths = []
    for folder in ['src', 'scripts', 'tests', 'web', '.github']:
        paths.extend(path for path in (ROOT / folder).rglob('*')
                     if path.is_file() and '__pycache__' not in path.parts
                     and path.suffix in {'.py', '.js', '.mjs', '.json', '.css', '.html', '.yml'})
    paths.extend(path for path in ROOT.iterdir() if path.is_file()
                 and (path.name.startswith('requirements') or path.name in {'package.json', 'package-lock.json', 'pyproject.toml'}))
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


def test_summary(path: Path) -> dict:
    if not path.is_file():
        return {}
    cases = list(ET.parse(path).getroot().iter('testcase'))
    return {'tests': len(cases), **{key: sum(item.find(tag) is not None for item in cases)
                                   for key, tag in [('failures', 'failure'), ('errors', 'error'), ('skipped', 'skipped')]}}


def run_check(name: str, command: list[str], env: dict, timeout: int) -> dict:
    started = time.perf_counter()
    print(f'\n{name}', flush=True)
    try:
        result = subprocess.run(command, cwd=ROOT, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=timeout, check=False)
        output = result.stdout
        exit_code = result.returncode
    except (OSError, subprocess.TimeoutExpired) as error:
        output = str(error)
        exit_code = 1
    print(output, flush=True)
    return {'name': name, 'command': command, 'exit_code': exit_code,
            'seconds': round(time.perf_counter() - started, 3), 'output': output}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full-data', action='store_true',
                        help='Download/check the entire pinned research dataset before tests.')
    args = parser.parse_args()
    (ROOT / 'reports').mkdir(exist_ok=True)
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT / 'src') + os.pathsep + env.get('PYTHONPATH', '')
    for variable in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
        env[variable] = '1'
    env['PYTHONHASHSEED'] = '42'
    source_before = source_hashes()
    checks = []
    (ROOT / 'reports/verification-junit.xml').unlink(missing_ok=True)
    (ROOT / 'reports/verification-node-junit.xml').unlink(missing_ok=True)
    if args.full_data:
        checks.append(run_check('Download and audit pinned benchmark',
                                [sys.executable, 'scripts/download_data.py'], env, 600))
        if checks[-1]['exit_code']:
            report = {'status': 'failed', 'checks': checks}
            (ROOT / 'reports/verification.json').write_text(json.dumps(report, indent=2) + '\n')
            return 1
    checks.append(run_check('Python source, model parity and data contracts',
                            [sys.executable, '-m', 'pytest', '-q',
                             '--junitxml=reports/verification-junit.xml'], env, 300))
    node = shutil.which('node')
    if node:
        test_files = [str(path.relative_to(ROOT)) for path in sorted((ROOT / 'tests').glob('*.test.mjs'))]
        checks.append(run_check('Browser lifecycle, input integrity, numerical, build and server contracts',
                                [node, '--test', '--test-reporter=spec', '--test-reporter-destination=stdout',
                                 '--test-reporter=junit', '--test-reporter-destination=reports/verification-node-junit.xml',
                                 *test_files], env, 120))
    else:
        checks.append({'name': 'Browser numerical and export contracts', 'exit_code': 1,
                       'output': 'Node.js is required. Install Node.js 22 or newer and run verification again.'})
    checks.append(run_check('Compile source and scripts',
                            [sys.executable, '-m', 'compileall', '-q', 'src', 'scripts'], env, 60))
    summary = test_summary(ROOT / 'reports/verification-junit.xml')
    node_summary = test_summary(ROOT / 'reports/verification-node-junit.xml')
    source_after = source_hashes()
    changed_sources = [name for name in sorted(set(source_before) | set(source_after)) if source_before.get(name) != source_after.get(name)]
    checks.append({'name': 'Source remained unchanged during verification', 'exit_code': int(bool(changed_sources)),
                   'output': '\n'.join(changed_sources)})
    success = all(item['exit_code'] == 0 for item in checks)
    report = {'status': 'passed' if success else 'failed',
              'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'python_version': sys.version.split()[0], 'full_data_requested': args.full_data,
              'package_versions': observed_versions(), 'raw_dataset_inventory': raw_inventory(),
              'tracked_real_images': len(list((ROOT / 'artifacts/samples').glob('*.png'))),
              'artifact_sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in [ROOT / 'artifacts/checkpoint.pt', ROOT / 'artifacts/model.onnx'] if path.is_file()},
              'python_test_summary': summary,
              'node_test_summary': node_summary, 'source_sha256': source_after,
              'verification_scope': 'Local source, frozen PyTorch/ONNX parity, real tracked-sample inference, adversarial data/CLI/recovery tests, actual app.js lifecycle with browser API doubles, still-image container guards, build integrity, local HTTP server and available raw-data hashes. Native browser decoding/layout, physical camera hardware and factory performance require separate validation.',
              'checks': checks}
    destination = ROOT / 'reports/verification.json'
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(f'\nVerification {report["status"]}: {destination}', flush=True)
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
