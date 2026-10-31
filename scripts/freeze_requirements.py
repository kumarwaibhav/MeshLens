#!/usr/bin/env python3
"""Resolve exact installed dependency closures without querying package indexes.

Locks describe the observed CPython 3.12 Linux environment. The browser bundle
runs without Python; requirements-inference.lock is for the local ONNX CLI.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib import metadata
import json
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
TRAINING = ['numpy', 'scipy', 'scikit-learn', 'Pillow', 'torch', 'matplotlib', 'onnx', 'onnxscript', 'onnxruntime']
DEVELOPMENT = ['pytest', 'ruff', 'pip-audit', 'nbformat', 'nbclient', 'ipykernel', 'reportlab']
INFERENCE = ['numpy', 'Pillow', 'onnxruntime']


def installed(paths: list[Path]) -> dict:
    packages = {}
    for path in paths:
        for distribution in metadata.distributions(path=[str(path.resolve())]):
            name = distribution.metadata.get('Name')
            if name:
                packages[canonicalize_name(name)] = distribution
    return packages


def closure(seeds: list[str], packages: dict) -> dict:
    environment = default_environment()
    environment['extra'] = ''
    pending = [canonicalize_name(name) for name in seeds]
    selected = {}
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        if name not in packages:
            raise ValueError(f'Installed dependency missing from provided package directories: {name}')
        distribution = packages[name]
        selected[name] = distribution.version
        for specification in distribution.requires or []:
            requirement = Requirement(specification)
            if requirement.marker and not requirement.marker.evaluate(environment):
                continue
            dependency = canonicalize_name(requirement.name)
            if dependency not in packages:
                raise ValueError(f'{name} requires {requirement}; dependency is absent from the observed environment.')
            if requirement.specifier and not requirement.specifier.contains(packages[dependency].version, prereleases=True):
                raise ValueError(f'Installed version conflict: {name} requires {requirement}, found {packages[dependency].version}')
            pending.append(dependency)
    return selected


def write_lock(filename: str, versions: dict, include: str | None = None, cpu=False) -> None:
    lines = ['# Exact observed dependency closure; CPython 3.12 Linux x86_64.',
             '# Owner: Kumar Waibhav AKshat <kwa.waibhav@gmail.com>.']
    if cpu:
        lines.append('--extra-index-url https://download.pytorch.org/whl/cpu')
    if filename == 'requirements-training-original.lock':
        lines.insert(1, '# Historical training record only; use requirements.lock for the recommended patched environment.')
    if include:
        lines.append(f'-r {include}')
    lines.extend(f'{name}=={version}' for name, version in sorted(versions.items()))
    (ROOT / filename).write_text('\n'.join(lines) + '\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deps', type=Path, required=True)
    parser.add_argument('--patched', type=Path, required=True)
    args = parser.parse_args()
    original = installed([args.deps])
    shipped = installed([args.deps, args.patched])
    runtime = closure(TRAINING, shipped)
    development = closure(DEVELOPMENT, shipped)
    extra_development = {name: version for name, version in development.items() if name not in runtime}
    inference = closure(INFERENCE, shipped)
    original_training = closure(TRAINING, original)
    write_lock('requirements.lock', runtime, cpu=True)
    write_lock('requirements-dev.lock', extra_development, include='requirements.lock')
    write_lock('requirements-inference.lock', inference)
    write_lock('requirements-training-original.lock', original_training, cpu=True)
    report = {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'platform_scope': 'Exact installed CPython 3.12 Linux dependency closure; other platforms may require separately resolved conditional dependencies.',
              'shipped': runtime, 'development_additions': extra_development,
              'onnx_cli': inference, 'original_training': original_training,
              'torch_policy': 'Training used its recorded original version. The default shipped environment selects the separately installed patched runtime after frozen-checkpoint compatibility verification.'}
    (ROOT / 'reports').mkdir(exist_ok=True)
    (ROOT / 'reports/dependency-locks.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: len(report[key]) for key in ['shipped', 'development_additions', 'onnx_cli', 'original_training']}, indent=2))


if __name__ == '__main__':
    main()
