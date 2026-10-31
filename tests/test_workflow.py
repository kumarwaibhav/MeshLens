"""Acquisition/recovery regressions use isolated fixtures and a tiny network."""
from copy import deepcopy
import hashlib
import io
from pathlib import Path
import random
import sys
import tarfile

import numpy as np
import pytest
import torch
from torch import nn

from scripts import download_data, train


@pytest.fixture(autouse=True)
def preserve_random_state():
    torch_state, numpy_state, python_state = torch.get_rng_state().clone(), np.random.get_state(), random.getstate()
    threads, deterministic = torch.get_num_threads(), torch.are_deterministic_algorithms_enabled()
    yield
    torch.set_rng_state(torch_state)
    np.random.set_state(numpy_state)
    random.setstate(python_state)
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(deterministic)


@pytest.mark.parametrize('names', [['grid/a.png', 'grid/a.png'], ['C:/outside.png'], [r'grid\..\outside.png']])
def test_duplicate_and_windows_escape_archive_members_are_rejected_before_extraction(tmp_path, names):
    archive = tmp_path / 'unsafe.tar.xz'
    with tarfile.open(archive, 'w:xz') as stream:
        for name in names:
            info = tarfile.TarInfo(name)
            info.size = 1
            stream.addfile(info, io.BytesIO(b'x'))
    output = tmp_path / 'output'
    output.mkdir()
    with pytest.raises(ValueError, match='Unsafe'):
        download_data.extract_checked(archive, output)
    assert list(output.iterdir()) == []


@pytest.mark.parametrize('filename', ['manifest.csv', 'mask_checksums.json'])
def test_audit_never_rewrites_tampered_reference_metadata(tmp_path, project_root, filename):
    data = tmp_path / 'data'
    data.mkdir()
    content = (project_root / 'data' / filename).read_bytes() + b'tampered'
    (data / filename).write_bytes(content)
    with pytest.raises(ValueError, match='Pinned reference'):
        download_data.audit_dataset(tmp_path)
    assert (data / filename).read_bytes() == content
    assert not (data / 'provenance.json').exists()


def test_download_retries_transient_error_and_commits_only_verified_bytes(tmp_path, monkeypatch):
    expected = b'pinned test archive'
    monkeypatch.setattr(download_data, 'ARCHIVE_BYTES', len(expected))
    monkeypatch.setattr(download_data, 'ARCHIVE_SHA256', hashlib.sha256(expected).hexdigest())
    calls, delays = [], []

    def request(*_args, **_kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise OSError('transient failure')
        return io.BytesIO(expected)

    monkeypatch.setattr(download_data.urllib.request, 'urlopen', request)
    monkeypatch.setattr(download_data.time, 'sleep', delays.append)
    archive = tmp_path / 'grid.tar.xz'
    download_data.download_archive(archive)
    assert archive.read_bytes() == expected
    assert len(calls) == 2 and delays == [1]
    assert not archive.with_suffix('.xz.part').exists()


def test_download_size_and_digest_mismatch_leave_no_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(download_data, 'ARCHIVE_BYTES', 4)
    monkeypatch.setattr(download_data, 'ARCHIVE_SHA256', hashlib.sha256(b'good').hexdigest())
    monkeypatch.setattr(download_data.time, 'sleep', lambda _delay: None)
    for payload in [b'evil', b'far too large']:
        monkeypatch.setattr(download_data.urllib.request, 'urlopen', lambda *_args, **_kwargs: io.BytesIO(payload))
        archive = tmp_path / 'grid.tar.xz'
        with pytest.raises(ValueError, match='after.*3.*attempts'):
            download_data.download_archive(archive)
        assert not archive.exists() and not archive.with_suffix('.xz.part').exists()


@pytest.mark.parametrize('fail_after_replace', [False, True])
def test_repair_stages_and_restores_old_dataset_on_failed_final_validation(tmp_path, monkeypatch, fail_after_replace):
    raw = tmp_path / 'data/raw/grid'
    (raw / 'train/good').mkdir(parents=True)
    (raw / 'train/good/old.txt').write_text('previous dataset')
    monkeypatch.setattr(download_data, 'ROOT', tmp_path)
    monkeypatch.setattr(download_data, 'verify_reference_metadata', lambda _root: None)
    monkeypatch.setattr(download_data, 'download_archive', lambda _archive: None)

    def extract(_archive, destination):
        target = destination / 'grid/train/good'
        target.mkdir(parents=True)
        (target / 'new.txt').write_text('staged dataset')

    calls = []

    def audit(*args, **_kwargs):
        current = args[0] if args else tmp_path
        calls.append(current)
        if current == tmp_path and fail_after_replace:
            raise ValueError('final validation failure')
        return {}

    monkeypatch.setattr(download_data, 'extract_checked', extract)
    monkeypatch.setattr(download_data, 'audit_dataset', audit)
    monkeypatch.setattr(sys, 'argv', ['download_data.py', '--repair'])
    if fail_after_replace:
        with pytest.raises(SystemExit) as error:
            download_data.main()
        assert error.value.code == 2
        assert (raw / 'train/good/old.txt').read_text() == 'previous dataset'
        assert not (raw / 'train/good/new.txt').exists()
    else:
        download_data.main()
        assert (raw / 'train/good/new.txt').read_text() == 'staged dataset'
        assert not (raw / 'train/good/old.txt').exists()
    assert len(calls) == 2
    assert not list(raw.parent.glob('.grid-stage-*'))


@pytest.fixture(scope='module')
def real_resume():
    saved = torch.load(Path(__file__).resolve().parents[1] / 'artifacts/training-resume-denoising.pt', map_location='cpu', weights_only=True)
    return saved, train.ConvAutoencoder(saved['candidate']['latent_channels'])


def test_actual_resume_payload_validates_without_changing_global_rng(real_resume):
    saved, model = real_resume
    before = torch.get_rng_state().clone()
    train.validate_resume(saved, saved['candidate'], saved['target_epochs'], saved['manifest_sha256'], model)
    assert torch.equal(torch.get_rng_state(), before)


@pytest.mark.parametrize('poison', ['epoch', 'history', 'nonfinite_loss', 'best_error', 'model_nan', 'lr', 'optimizer_step', 'negative_moment', 'torch_rng', 'manifest'])
def test_poisoned_resume_is_rejected_before_restoring_rng(real_resume, poison):
    original, model = real_resume
    saved = deepcopy(original)
    if poison == 'epoch':
        saved['epoch'] = saved['target_epochs'] + 1
    elif poison == 'history':
        saved['history'][0]['epoch'] = 2
    elif poison == 'nonfinite_loss':
        saved['history'][0]['fit_patch_mse'] = float('nan')
    elif poison == 'best_error':
        saved['best_tune_mse'] += 1
    elif poison == 'model_nan':
        next(iter(saved['state_dict'].values())).flatten()[0] = float('nan')
    elif poison == 'lr':
        saved['optimizer_state_dict']['param_groups'][0]['lr'] = .1
    elif poison == 'optimizer_step':
        saved['optimizer_state_dict']['state'][0]['step'] += 1
    elif poison == 'negative_moment':
        saved['optimizer_state_dict']['state'][0]['exp_avg_sq'].flatten()[0] = -1
    elif poison == 'torch_rng':
        saved['torch_rng_state'] = torch.zeros(1, dtype=torch.uint8)
    else:
        saved['manifest_sha256'] = '0' * 64
    before = torch.get_rng_state().clone()
    with pytest.raises(ValueError):
        train.validate_resume(saved, original['candidate'], original['target_epochs'], original['manifest_sha256'], model)
    assert torch.equal(torch.get_rng_state(), before)


def test_interrupted_training_resumes_identical_optimizer_and_rng_streams(tmp_path, monkeypatch):
    class TinyNetwork(nn.Module):
        def __init__(self, _latent):
            super().__init__()
            self.layers = nn.Sequential(nn.Conv2d(3, 3, 1), nn.Sigmoid())

        def forward(self, values):
            return self.layers(values)

    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/manifest.csv').write_text('stable miniature fixture\n')
    monkeypatch.setattr(train, 'ROOT', tmp_path)
    monkeypatch.setattr(train, 'ConvAutoencoder', TinyNetwork)
    images = np.random.default_rng(10).random((2, 3, 64, 64), dtype=np.float32)
    config = {'name': 'miniature', 'latent_channels': 4, 'noise_std': .035, 'seed': 42}
    full_dir, resume_dir = tmp_path / 'full', tmp_path / 'resume'
    full_dir.mkdir()
    resume_dir.mkdir()
    expected, expected_history = train.train_candidate(images, images[:1], config, 2, full_dir / 'candidate.pt')
    replace = Path.replace
    interrupted = False

    def interrupt_after_atomic_save(path, target):
        nonlocal interrupted
        result = replace(path, target)
        if path.name == 'training-resume-miniature.pt.tmp' and not interrupted:
            interrupted = True
            raise RuntimeError('simulated process interruption after atomic epoch save')
        return result

    monkeypatch.setattr(Path, 'replace', interrupt_after_atomic_save)
    with pytest.raises(RuntimeError, match='simulated process'):
        train.train_candidate(images, images[:1], config, 2, resume_dir / 'candidate.pt')
    monkeypatch.setattr(Path, 'replace', replace)
    actual, actual_history = train.train_candidate(images, images[:1], config, 2, resume_dir / 'candidate.pt')
    for key, value in expected.state_dict().items():
        assert torch.equal(value, actual.state_dict()[key]), key
    for expected_row, actual_row in zip(expected_history, actual_history, strict=True):
        for key in ['epoch', 'fit_patch_mse', 'tune_image_mse']:
            assert expected_row[key] == actual_row[key]
    assert not list(resume_dir.glob('*.tmp'))
