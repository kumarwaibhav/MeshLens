#!/usr/bin/env python3
"""Audit exact shipped package closures; preserve scanner failures and findings.

CPU local version suffixes are normalized to the upstream public PyTorch version
for vulnerability lookup. No vulnerability IDs are suppressed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-original', action='store_true', help='Also audit the separately recorded historical training runtime.')
    args = parser.parse_args()
    locks = json.loads((ROOT / 'reports/dependency-locks.json').read_text())
    scopes = [('runtime', locks['shipped'], 'dependency-audit.json'),
              ('development', dict(locks['shipped'], **locks['development_additions']), 'dependency-audit-development.json')]
    if args.include_original:
        scopes.append(('original_training', locks['original_training'], 'dependency-audit-training-original.json'))
    summary = {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
               'service': 'pip-audit default PyPI vulnerability service',
               'version_normalization': 'Official CPU torch local suffix +cpu removed for public upstream-version advisory matching; all other versions audited unchanged.',
               'ignored_vulnerability_ids': [], 'scopes': {}}
    success = True
    with tempfile.TemporaryDirectory(prefix='meshlens-audit-') as directory:
        for name, versions, output_name in scopes:
            requirements = Path(directory) / f'{name}.txt'
            requirements.write_text('\n'.join(f'{package}=={version.split("+", 1)[0] if package == "torch" else version}'
                                               for package, version in sorted(versions.items())) + '\n')
            output = ROOT / 'reports' / output_name
            output.unlink(missing_ok=True)
            command = [sys.executable, '-m', 'pip_audit', '--disable-pip', '--no-deps', '--strict',
                       '--progress-spinner', 'off', '--timeout', '20',
                       '-r', str(requirements), '-f', 'json', '-o', str(output)]
            try:
                result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True,
                                        timeout=300, check=False)
            except (OSError, subprocess.TimeoutExpired) as error:
                result = subprocess.CompletedProcess(command, 2, stdout='', stderr=str(error))
            try:
                parsed = json.loads(output.read_text()) if output.is_file() and output.stat().st_size else {}
            except json.JSONDecodeError:
                parsed = {}
            packages = parsed.get('dependencies', [])
            findings = [(package.get('name'), item.get('id')) for package in packages for item in package.get('vulns', [])]
            skipped = [package for package in packages if package.get('skip_reason')]
            audited_count = len(packages) - len(skipped)
            status = 'passed' if result.returncode == 0 and audited_count == len(versions) and not findings else ('findings' if findings else 'incomplete')
            summary['scopes'][name] = {'status': status, 'exit_code': result.returncode,
                                       'expected_packages': len(versions), 'audited_packages': audited_count,
                                       'vulnerability_count': len(findings), 'findings': findings,
                                       'skipped_packages': skipped, 'report': output_name,
                                       'scanner_stdout': result.stdout, 'scanner_stderr': result.stderr}
            success = success and status == 'passed'
            print(f'{name}: {status}; {audited_count}/{len(versions)} packages, {len(findings)} vulnerability findings.', flush=True)
    (ROOT / 'reports/security-audit-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
