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
import signal
import subprocess
import sys
import tempfile
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
    """Incomplete JUnit evidence must never become a successful verification."""
    try:
        root = ET.parse(path).getroot()
        if root.tag not in {'testsuite', 'testsuites'}:
            raise ValueError('The JUnit root is not a test suite')
        cases = list(root.iter('testcase'))
        if not cases:
            raise ValueError('The JUnit report contains no test cases')
    except (OSError, ET.ParseError, ValueError) as error:
        return {'status': 'failed', 'tests': 0, 'failures': 0, 'errors': 1, 'skipped': 0,
                'error': f'JUnit evidence is unavailable or invalid: {error}'}
    counts = {'tests': len(cases), **{key: sum(item.find(tag) is not None for item in cases)
                                    for key, tag in [('failures', 'failure'), ('errors', 'error'), ('skipped', 'skipped')]}}
    return {'status': 'failed' if counts['failures'] or counts['errors'] else 'passed', **counts}


def write_report(path: Path, report: dict) -> None:
    """Replace old results atomically, including before running any checks."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _stop_process_tree(process: subprocess.Popen) -> None:
    """Stop only the session/tree created for this individual check."""
    if os.name == 'posix':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif os.name == 'nt':
        try:
            completed = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       timeout=5, check=False)
            if completed.returncode and process.poll() is None:
                process.kill()
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        process.kill()


def _output_text(value) -> str:
    return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''


def run_check(name: str, command: list[str], env: dict, timeout: int) -> dict:
    started = time.perf_counter()
    print(f'\n{name}', flush=True)
    process = None
    timed_out = False
    output = ''
    try:
        options = {'start_new_session': True} if os.name == 'posix' else {}
        if os.name == 'nt':
            options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen(command, cwd=ROOT, env=env, text=True, encoding='utf-8',
                                   errors='replace', stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **options)
        try:
            output, _ = process.communicate(timeout=timeout)
            exit_code = process.returncode
        except subprocess.TimeoutExpired as error:
            timed_out = True
            output = _output_text(error.output)
            _stop_process_tree(process)
            try:
                remaining, _ = process.communicate(timeout=5)
            except subprocess.TimeoutExpired as drain_error:
                remaining = drain_error.output
                if process.stdout:
                    process.stdout.close()
                process.wait(timeout=5)
            remaining = _output_text(remaining)
            output = remaining if remaining.startswith(output) else output + remaining
            output += f'\nVerification check timed out after {timeout} seconds; its process tree was stopped.\n'
            exit_code = 124
    except OSError as error:
        output += str(error)
        exit_code = 1
    except BaseException:
        if process is not None:
            _stop_process_tree(process)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                if process.stdout:
                    process.stdout.close()
        raise
    print(output, flush=True)
    return {'name': name, 'command': command, 'exit_code': exit_code,
            'seconds': round(time.perf_counter() - started, 3), 'output': output, 'timed_out': timed_out}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full-data', action='store_true', help='Download/check the pinned benchmark before tests.')
    args = parser.parse_args(argv)
    (ROOT / 'reports').mkdir(exist_ok=True)
    destination = ROOT / 'reports/verification.json'
    pending = {'status': 'failed', 'tests': 0, 'failures': 0, 'errors': 1, 'skipped': 0,
               'error': 'This suite has not completed in the current run.'}
    checks = []
    report = {'status': 'failed', 'completed': False, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'python_version': sys.version.split()[0], 'full_data_requested': args.full_data,
              'python_test_summary': dict(pending), 'node_test_summary': dict(pending), 'checks': checks}
    write_report(destination, report)
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT / 'src') + os.pathsep + env.get('PYTHONPATH', '')
    for variable in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
        env[variable] = '1'
    env['PYTHONHASHSEED'] = '42'
    source_before = None
    interrupted = False
    try:
        for filename in ('verification-junit.xml', 'verification-node-junit.xml'):
            (ROOT / 'reports' / filename).unlink(missing_ok=True)
        source_before = source_hashes()
        proceed = True
        if args.full_data:
            checks.append(run_check('Download and audit pinned benchmark',
                                    [sys.executable, 'scripts/download_data.py'], env, 600))
            write_report(destination, report)
            proceed = checks[-1]['exit_code'] == 0
        if proceed:
            checks.append(run_check('Python source, model parity and data contracts',
                                    [sys.executable, '-m', 'pytest', '-q', '--junitxml=reports/verification-junit.xml'], env, 300))
            report['python_test_summary'] = test_summary(ROOT / 'reports/verification-junit.xml')
            checks.append({'name': 'Python JUnit evidence is complete',
                           'exit_code': int(report['python_test_summary']['status'] != 'passed'),
                           'output': report['python_test_summary'].get('error', '')})
            write_report(destination, report)
            node = shutil.which('node')
            if node:
                test_files = [str(path.relative_to(ROOT)) for path in sorted((ROOT / 'tests').glob('*.test.mjs'))]
                checks.append(run_check('Browser lifecycle, input integrity, numerical, build and server contracts',
                                        [node, '--test', '--test-concurrency=1', '--test-reporter=spec',
                                         '--test-reporter-destination=stdout', '--test-reporter=junit',
                                         '--test-reporter-destination=reports/verification-node-junit.xml', *test_files], env, 300))
            else:
                checks.append({'name': 'Browser contracts', 'exit_code': 1,
                               'output': 'Node.js is required. Install Node.js 22 or newer.'})
            report['node_test_summary'] = test_summary(ROOT / 'reports/verification-node-junit.xml')
            checks.append({'name': 'Node JUnit evidence is complete',
                           'exit_code': int(report['node_test_summary']['status'] != 'passed'),
                           'output': report['node_test_summary'].get('error', '')})
            write_report(destination, report)
            checks.append(run_check('Compile source and scripts',
                                    [sys.executable, '-m', 'compileall', '-q', 'src', 'scripts'], env, 60))
        report['completed'] = True
    except KeyboardInterrupt:
        interrupted = True
        report['error'] = 'Verification was interrupted.'
        checks.append({'name': 'Verification runner completed', 'exit_code': 130, 'output': report['error']})
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {error}'
        checks.append({'name': 'Verification runner completed', 'exit_code': 1, 'output': report['error']})
    for key, observe in [('package_versions', observed_versions), ('raw_dataset_inventory', raw_inventory),
                         ('source_sha256', source_hashes)]:
        try:
            report[key] = observe()
        except Exception as error:
            report[key] = {}
            checks.append({'name': f'Record {key}', 'exit_code': 1, 'output': str(error)})
    after = report['source_sha256']
    changed = [name for name in sorted(set(source_before or {}) | set(after))
               if (source_before or {}).get(name) != after.get(name)]
    checks.append({'name': 'Source remained unchanged during verification',
                   'exit_code': int(source_before is None or bool(changed)), 'output': '\n'.join(changed)})
    try:
        report['tracked_real_images'] = len(list((ROOT / 'artifacts/samples').glob('*.png')))
        report['artifact_sha256'] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                     for path in [ROOT / 'artifacts/checkpoint.pt', ROOT / 'artifacts/model.onnx'] if path.is_file()}
    except OSError as error:
        checks.append({'name': 'Record artifact inventory', 'exit_code': 1, 'output': str(error)})
    success = report['completed'] and all(item['exit_code'] == 0 for item in checks)
    report['status'] = 'passed' if success else 'failed'
    report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    report['verification_scope'] = 'Source, frozen model parity, data/input contracts, CLI/recovery, browser doubles, build integrity and local server. Native browser/layout, camera hardware and factory performance require separate validation.'
    write_report(destination, report)
    print(f'\nVerification {report["status"]}: {destination}', flush=True)
    return 0 if success else 130 if interrupted else 1


if __name__ == '__main__':
    raise SystemExit(main())
