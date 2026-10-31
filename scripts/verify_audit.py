#!/usr/bin/env python3
"""Summarize named regression evidence without claiming exhaustive correctness."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from verify_project import source_hashes

ROOT = Path(__file__).resolve().parents[1]


def read_json(name: str) -> dict:
    path = ROOT / 'reports' / name
    return json.loads(path.read_text()) if path.is_file() else {}


def cases(name: str) -> list:
    path = ROOT / 'reports' / name
    return list(ET.parse(path).getroot().iter('testcase')) if path.is_file() else []


def coverage(area: str, selected: list, evidence: list[str], limits: str = '') -> dict:
    failures = [item.attrib.get('name') for item in selected if item.find('failure') is not None or item.find('error') is not None]
    skipped = [item.attrib.get('name') for item in selected if item.find('skipped') is not None]
    status = 'not_verified' if not selected else ('fail' if failures else ('not_verified' if skipped else 'pass'))
    return {'area': area, 'status': status, 'tests': len(selected), 'failures': failures, 'skipped': skipped,
            'evidence': evidence, 'limitations': limits}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full-data', action='store_true')
    parser.add_argument('--reuse-verification', action='store_true', help='Reuse a completed report only when its recorded source hashes still match.')
    args = parser.parse_args()
    if not args.reuse_verification:
        command = [sys.executable, str(ROOT / 'scripts/verify_project.py')]
        if args.full_data:
            command.append('--full-data')
        subprocess.run(command, cwd=ROOT, check=False)
    verification = read_json('verification.json')
    current_source = source_hashes()
    source_matches = bool(verification.get('source_sha256')) and verification['source_sha256'] == current_source
    python = cases('verification-junit.xml')
    node = cases('verification-node-junit.xml')
    def py(module):
        return [item for item in python if item.attrib.get('classname', '').endswith(module)]

    def js(filename):
        return [item for item in node if Path(item.attrib.get('file', '')).name == filename]

    adversarial, workflow = py('test_adversarial'), py('test_workflow')

    def matches(items, words):
        return [item for item in items if any(word in item.attrib.get('name', '') for word in words)]
    matrix = [
        coverage('Preprocessing, residual mathematics and finite-sample normal calibration', py('test_core') + matches(adversarial, ['preprocessing', 'alpha_', 'animated_', 'animation_']), ['verification-junit.xml']),
        coverage('Dataset role/path/hash contracts, archive extraction and acquisition rollback', py('test_data') + matches(workflow, ['archive', 'reference', 'download', 'repair']), ['verification-junit.xml']),
        coverage('Actual frozen checkpoint, ONNX parity and 18 real replay images', py('test_model'), ['verification-junit.xml'], 'The tracked image test is mandatory even without the raw research dataset.'),
        coverage('Frozen bundle consistency, poisoned checkpoints and safe model-byte loading', matches(adversarial, ['bundle', 'metadata', 'frozen_', 'checkpoint', 'tampering', 'onnx_session']), ['verification-junit.xml']),
        coverage('CLI real inference, JSON/image evidence and friendly invalid-input handling', matches(adversarial, ['test_cli_']), ['verification-junit.xml']),
        coverage('Poisoned resume rejection and exact interrupted miniature training continuity', matches(workflow, ['resume', 'interrupted_training']), ['verification-junit.xml'], 'The recovery test runs the real trainer with a tiny network; the published model is not retrained.'),
        coverage('Actual app.js upload, replay, camera, session, storage and cancellation lifecycle', js('app-lifecycle.test.mjs'), ['verification-node-junit.xml'], 'Browser DOM, decoder, camera and ORT APIs are controlled doubles; these tests do not validate camera hardware or native image decoding.'),
        coverage('Still-image container guards and actual WebCrypto/noble hash fallback', js('validation.test.mjs'), ['verification-node-junit.xml'], 'Container inspection bounds decoding requests; the native decoder must still reject invalid compressed pixels.'),
        coverage('Atomic build integrity, tampered fixtures and safe local HTTP server', js('build-server.test.mjs'), ['verification-node-junit.xml'], 'The build fixture uses tiny runtime files; actual WASM execution is a separate check.'),
        coverage('Browser numerical, threshold-tie and CSV export mathematics', js('inference.test.mjs'), ['verification-node-junit.xml']),
    ]
    wasm, runtime = read_json('wasm-parity.json'), read_json('runtime-upgrade-validation.json')
    model_digest = hashlib.sha256((ROOT / 'artifacts/model.onnx').read_bytes()).hexdigest()
    checkpoint_digest = hashlib.sha256((ROOT / 'artifacts/checkpoint.pt').read_bytes()).hexdigest()
    matrix.append({'area': 'Actual ONNXRuntimeWeb WASM on all 78 official test tensors',
                   'status': 'pass' if wasm.get('status') == 'passed' and wasm.get('samples') == 78 and wasm.get('changed_decisions') == 0 and wasm.get('model_sha256') == model_digest else 'not_verified',
                   'evidence': ['wasm-parity.json'], 'recorded_timestamp_utc': wasm.get('timestamp_utc'),
                   'limitations': 'Canonical tensors are shared across runtimes; native browser decoding, layout and physical cameras are outside this parity test.'})
    matrix.append({'area': 'Recorded strict PyTorch upgrade diagnostic',
                   'status': 'fail' if runtime.get('status') == 'failed' and runtime.get('checkpoint_sha256') == checkpoint_digest else ('pass' if runtime.get('status') == 'passed' else 'not_verified'),
                   'evidence': ['runtime-upgrade-validation.json'], 'recorded_timestamp_utc': runtime.get('timestamp_utc'),
                   'changed_decisions_by_split': runtime.get('changed_decisions_by_split'),
                   'limitations': 'The preserved diagnostic has one calibration threshold-tie crossing and zero official-test changes. It is not relabeled as a strict pass; no threshold is retuned.'})
    clean, installation = read_json('verification-clean-checkout.json'), read_json('clean-installation.json')
    matrix.append({'area': 'Fresh pinned dependency installation and raw-absent source checkout',
                   'status': 'pass' if clean.get('status') == 'passed' and clean.get('raw_dataset_inventory', {}).get('status') == 'absent' and installation.get('status') == 'passed' else 'not_verified',
                   'evidence': ['clean-installation.json', 'verification-clean-checkout.json'],
                   'python_summary': clean.get('python_test_summary'), 'node_summary': clean.get('node_test_summary'),
                   'limitations': 'Only the complete raw-data audit is skipped. Real bundled checkpoint/ONNX/18-image tests remain mandatory.'})
    security, npm = read_json('security-audit-summary.json'), read_json('npm-audit.json')
    scopes = security.get('scopes', {})
    matrix.append({'area': 'Named shipped/development/npm advisory scans',
                   'status': 'pass' if scopes.get('runtime', {}).get('status') == scopes.get('development', {}).get('status') == 'passed' and npm.get('metadata', {}).get('vulnerabilities', {}).get('total') == 0 else 'not_verified',
                   'evidence': ['security-audit-summary.json', 'npm-audit.json'],
                   'python_timestamp_utc': security.get('timestamp_utc'), 'npm_timestamp_utc': npm.get('timestamp_utc'),
                   'limitations': 'These scans cover the named locks and current known advisories. The historical training lock retains its separately documented findings; this is not a security certification.'})
    metrics = read_json('metrics.json')
    measured = metrics.get('model', {})
    matrix.append({'area': 'Standalone factory acceptance or rejection qualification', 'status': 'fail',
                   'evidence': ['metrics.json'], 'true_positive': measured.get('true_positive'), 'false_negative': measured.get('false_negative'), 'recall': measured.get('recall'),
                   'limitations': 'The frozen research demo flags only 11 of 57 known benchmark defects and misses 46. It is unsuitable as a standalone production acceptance/rejection system.'})
    for area, limitation in [
        ('Physical camera and target-line real-time performance', 'Camera stubs verify lifecycle/cadence/single-flight logic, not camera drivers, reconnect behavior on every device, exposure, motion blur, sustained throughput or target hardware latency.'),
        ('Cross-browser native decoding, layout and assistive technology', 'The VM harness cannot replace a browser rendering/decoding engine or an assistive-technology review. Separate interactive browser evidence must state its own scope.'),
        ('Unseen factory data, illumination/viewpoint/scale drift and operating threshold', 'The benchmark split and synthetic brightness tests do not establish performance on new production lines. The operating threshold remains frozen.'),
        ('Hosted CI and every unknown edge case', 'Local CI-command installation and tests do not prove a future hosted workflow run. No finite regression suite proves all possible inputs, failures or environments.')]:
        matrix.append({'area': area, 'status': 'not_verified', 'evidence': [], 'limitations': limitation})
    software_ok = verification.get('status') == 'passed' and source_matches
    report = {'schema_version': 1, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'status': 'completed_with_limitations' if software_ok else 'failed_software_checks',
              'software_verification_status': verification.get('status'), 'source_matches_tested_snapshot': source_matches,
              'python_test_summary': verification.get('python_test_summary'), 'node_test_summary': verification.get('node_test_summary'),
              'model_sha256': model_digest, 'checkpoint_sha256': checkpoint_digest,
              'scope': 'Named unit, adversarial, integration, build/server and model checks. Physical industrial qualification and unknown edges are explicitly not guaranteed.',
              'baseline_defects_reproduced_then_fixed': ['stale inference result after source replacement', 'replay fetch resolved after stop', 'camera play completion after stop', 'stale camera denial stopped a newer stream', 'empty camera stream accepted', 'ended camera track ignored', 'model bytes were not digest checked', 'session tensor-name mismatch accepted', 'sample bytes were not digest checked'],
              'matrix': matrix}
    (ROOT / 'reports/audit-validation.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({key: report[key] for key in ['status', 'source_matches_tested_snapshot', 'python_test_summary', 'node_test_summary']}, indent=2))
    return 0 if software_ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
