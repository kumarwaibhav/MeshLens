"""Adversarial inference/manifest/CLI fixtures never modify published artifacts."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import struct
import sys
import zlib

import numpy as np
from PIL import Image
import pytest
import torch

from meshlens.artifacts import load_frozen_metadata, verified_model_bytes
from meshlens.core import load_images, preprocess_image, read_manifest
from meshlens.model import load_checkpoint
from scripts import predict
from test_data import row, write_manifest


@pytest.fixture
def frozen_bundle(tmp_path, project_root):
    for folder in ['artifacts', 'reports']:
        (tmp_path / folder).mkdir()
    for name in ['artifacts/model.onnx', 'artifacts/metadata.json', 'reports/frozen_configuration.json', 'reports/calibration_scores.csv']:
        shutil.copy2(project_root / name, tmp_path / name)
    return tmp_path


def change_json(path, mutation):
    value = json.loads(path.read_text())
    mutation(value)
    path.write_text(json.dumps(value, allow_nan=True) + '\n')


def test_real_bundle_returns_exact_verified_model_bytes(frozen_bundle):
    metadata = load_frozen_metadata(frozen_bundle)
    content = verified_model_bytes(frozen_bundle, metadata)
    assert isinstance(content, bytes)
    assert hashlib.sha256(content).hexdigest() == metadata['export']['model_sha256']
    assert content == (frozen_bundle / 'artifacts/model.onnx').read_bytes()


@pytest.mark.parametrize('field,value', [('threshold', -1), ('threshold', float('nan')), ('threshold', True),
    ('image_size', 64), ('input_name', 'untrusted'), ('output_name', 'untrusted'), ('top_fraction', 0),
    ('score_top_fraction', .5), ('model_path', '../model.onnx'), ('model_version', 'wrong-checkpoint')])
def test_metadata_tampering_cannot_redefine_contract(frozen_bundle, field, value):
    change_json(frozen_bundle / 'artifacts/metadata.json', lambda data: data.update({field: value}))
    with pytest.raises(ValueError):
        load_frozen_metadata(frozen_bundle)


@pytest.mark.parametrize('field,value', [('threshold', .2), ('calibration_order_rank', 52), ('checkpoint_sha256', 'bad')])
def test_frozen_configuration_mismatch_is_rejected(frozen_bundle, field, value):
    change_json(frozen_bundle / 'reports/frozen_configuration.json', lambda data: data.update({field: value}))
    with pytest.raises(ValueError):
        load_frozen_metadata(frozen_bundle)


@pytest.mark.parametrize('filename', ['artifacts/model.onnx', 'artifacts/metadata.json', 'reports/frozen_configuration.json', 'reports/calibration_scores.csv'])
def test_missing_frozen_artifacts_raise_validation_error(frozen_bundle, filename):
    (frozen_bundle / filename).unlink()
    with pytest.raises(ValueError):
        load_frozen_metadata(frozen_bundle)


def test_model_and_calibration_byte_tampering_are_detected(frozen_bundle):
    path = frozen_bundle / 'artifacts/model.onnx'
    content = path.read_bytes()
    path.write_bytes(content[:-1] + bytes([content[-1] ^ 1]))
    with pytest.raises(ValueError, match='SHA256|mismatch'):
        load_frozen_metadata(frozen_bundle)
    path.write_bytes(content)
    scores = frozen_bundle / 'reports/calibration_scores.csv'
    scores.write_bytes(scores.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='SHA256|mismatch'):
        load_frozen_metadata(frozen_bundle)


def test_checkpoint_present_in_bundle_must_match_frozen_digest(frozen_bundle, project_root):
    path = frozen_bundle / 'artifacts/checkpoint.pt'
    shutil.copy2(project_root / 'artifacts/checkpoint.pt', path)
    load_frozen_metadata(frozen_bundle)
    path.write_bytes(b'replaced checkpoint')
    with pytest.raises(ValueError, match='[Cc]heckpoint|SHA256|mismatch'):
        load_frozen_metadata(frozen_bundle)


@pytest.mark.parametrize('chunk', ['acTL', 'fcTL', 'fdAT', 'ANIM', 'ANMF'])
def test_singleton_animation_chunks_are_rejected_before_decoding(chunk):
    stream = io.BytesIO()
    if chunk in {'acTL', 'fcTL', 'fdAT'}:
        Image.new('RGB', (32, 32), 'red').save(stream, format='PNG')
        image = stream.getvalue()
        data = struct.pack('>II', 1, 0) if chunk == 'acTL' else bytes(26 if chunk == 'fcTL' else 4)
        kind = chunk.encode()
        encoded = struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        image = image[:33] + encoded + image[33:]
    else:
        Image.new('RGB', (32, 32), 'red').save(stream, format='WEBP')
        image = stream.getvalue() + chunk.encode() + struct.pack('<I', 0)
        image = image[:4] + struct.pack('<I', len(image) - 8) + image[8:]
    with pytest.raises(ValueError, match='[Aa]nimat'):
        predict.reject_animation_container(image)


@pytest.mark.parametrize('size', [True, 0, -1, 1025, 32.0])
def test_preprocessing_rejects_invalid_output_dimension_types(size):
    with pytest.raises(ValueError):
        preprocess_image(Image.new('RGB', (64, 64)), size)


@pytest.mark.parametrize('size', [(0, 32), (31, 32), (32, 31), (4097, 32), (4096, 4096)])
def test_preprocessing_bounds_dimensions_before_resizing(size):
    with pytest.raises(ValueError):
        preprocess_image(Image.new('RGB', size))


def test_alpha_and_palette_transparency_have_white_background():
    values = preprocess_image(Image.new('RGBA', (32, 32), (0, 128, 255, 128)), 32)
    np.testing.assert_allclose(values[:, 0, 0], np.array([127, 191, 255]) / 255, atol=1e-7)
    palette = Image.new('P', (32, 32), 0)
    palette.putpalette([0, 0, 0] + [0] * 765)
    palette.info['transparency'] = 0
    np.testing.assert_array_equal(preprocess_image(palette, 32), 1)


def test_animated_png_is_not_silently_reduced_to_one_frame():
    stream = io.BytesIO()
    Image.new('RGB', (32, 32), 'red').save(stream, format='PNG', save_all=True,
        append_images=[Image.new('RGB', (32, 32), 'blue')], duration=100)
    stream.seek(0)
    with Image.open(stream) as image, pytest.raises(ValueError, match='[Aa]nimat'):
        preprocess_image(image)


@pytest.mark.parametrize('mutation', [
    lambda item: item.update(path='data/raw/grid/train/good/../good/000.png'),
    lambda item: item.update(path='data//raw/grid/train/good/000.png'), lambda item: item.update(label=1),
    lambda item: item.update(defect_type='broken'), lambda item: item.update(mask_path='data/raw/grid/ground_truth/broken/000_mask.png'),
    lambda item: item.update(path='data/raw/grid/test/good/000.png'), lambda item: item.update(defect_type='unrecognized')])
def test_manifest_rejects_noncanonical_and_contradictory_rows(tmp_path, mutation):
    item = row()
    mutation(item)
    write_manifest(tmp_path, [item])
    with pytest.raises(ValueError):
        read_manifest(tmp_path)


def test_manifest_rejects_missing_or_wrong_defect_mask(tmp_path):
    for mask in ['', 'data/raw/grid/ground_truth/bent/000_mask.png']:
        item = row(0, 'test', 1)
        item['mask_path'] = mask
        write_manifest(tmp_path, [item])
        with pytest.raises(ValueError):
            read_manifest(tmp_path)


def test_load_images_hashes_the_same_bytes_it_decodes(tmp_path):
    image = tmp_path / 'image.png'
    Image.new('RGB', (32, 32), (10, 20, 30)).save(image)
    rows = [{'path': 'image.png', 'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}]
    assert load_images(tmp_path, rows).shape == (1, 3, 256, 256)
    image.write_bytes(b'not an image anymore')
    with pytest.raises(ValueError, match='checksum'):
        load_images(tmp_path, rows)


def test_load_images_rejects_empty_missing_and_escaped_inputs(tmp_path):
    for rows in [[], [{'path': 'missing.png', 'sha256': '0' * 64}], [{'path': '../outside.png', 'sha256': '0' * 64}]]:
        with pytest.raises(ValueError):
            load_images(tmp_path, rows)


def test_checkpoint_digest_is_checked_before_deserialization(project_root):
    with pytest.raises(ValueError, match='SHA256'):
        load_checkpoint(project_root / 'artifacts/checkpoint.pt', expected_sha256='0' * 64)


@pytest.mark.parametrize('poison', ['nan', 'shape', 'missing', 'config'])
def test_poisoned_checkpoint_is_rejected(tmp_path, project_root, poison):
    saved = deepcopy(torch.load(project_root / 'artifacts/checkpoint.pt', map_location='cpu', weights_only=True))
    key = next(iter(saved['state_dict']))
    if poison == 'nan':
        saved['state_dict'][key].flatten()[0] = float('nan')
    elif poison == 'shape':
        saved['state_dict'][key] = saved['state_dict'][key].flatten()[:1]
    elif poison == 'missing':
        del saved['state_dict'][key]
    else:
        saved['config']['parameters'] = 1
    path = tmp_path / 'poisoned.pt'
    torch.save(saved, path)
    with pytest.raises(ValueError):
        load_checkpoint(path)


def test_checkpoint_loader_never_executes_pickle_payload(tmp_path):
    sentinel = tmp_path / 'pickle-executed.txt'

    class Payload:
        def __reduce__(self):
            return eval, (f"open({str(sentinel)!r}, 'w').write('unexpected')",)

    path = tmp_path / 'untrusted.pt'
    torch.save({'config': Payload()}, path)
    with pytest.raises(ValueError):
        load_checkpoint(path)
    assert not sentinel.exists()


@pytest.mark.parametrize('kind', ['missing', 'empty', 'corrupt', 'unsupported', 'oversize', 'dimensions', 'animated'])
def test_cli_invalid_inputs_are_friendly_errors(tmp_path, project_root, capsys, kind):
    path = tmp_path / 'input.png'
    if kind == 'empty':
        path.touch()
    elif kind == 'corrupt':
        path.write_bytes(b'\x89PNG\r\n\x1a\ncorrupt')
    elif kind == 'unsupported':
        Image.new('RGB', (32, 32)).save(path, format='BMP')
    elif kind == 'oversize':
        with path.open('wb') as stream:
            stream.truncate(12 * 1024 * 1024 + 1)
    elif kind == 'dimensions':
        Image.new('RGB', (4097, 32)).save(path)
    elif kind == 'animated':
        Image.new('RGB', (32, 32), 'red').save(path, save_all=True, append_images=[Image.new('RGB', (32, 32), 'blue')], duration=100)
    with pytest.raises(SystemExit) as error:
        predict.main([str(path), '--bundle', str(project_root)])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert 'error:' in captured.err and 'Traceback' not in captured.err


def test_cli_real_inference_writes_json_and_three_evidence_images(tmp_path, project_root):
    sample = json.loads((project_root / 'artifacts/samples.json').read_text())['samples'][0]
    source = project_root / 'artifacts/samples' / sample['filename']
    output, evidence = tmp_path / 'result.json', tmp_path / 'evidence'
    result = subprocess.run([sys.executable, str(project_root / 'scripts/predict.py'), str(source), '--output', str(output), '--evidence', str(evidence)], text=True, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    record = json.loads(output.read_text())
    assert record['score'] == pytest.approx(sample['expected_score'], abs=2e-6)
    assert record['is_anomaly'] == sample['expected_anomaly']
    assert record['decision'] == ('review' if sample['expected_anomaly'] else 'within_range')
    assert record['score_is_probability'] is False
    assert json.loads((evidence / 'result.json').read_text()) == record
    for filename in ['observed.png', 'reconstruction.png', 'residual.png']:
        with Image.open(evidence / filename) as image:
            assert image.size == (256, 256)


def test_cli_tampered_bundle_error_has_no_traceback(frozen_bundle, project_root, capsys):
    (frozen_bundle / 'artifacts/model.onnx').write_bytes(b'tampered')
    sample = next((project_root / 'artifacts/samples').glob('*.png'))
    with pytest.raises(SystemExit) as error:
        predict.main([str(sample), '--bundle', str(frozen_bundle)])
    assert error.value.code == 2
    assert 'Traceback' not in capsys.readouterr().err


@pytest.mark.parametrize('destination', ['input', 'metadata', 'evidence_input'])
def test_cli_cannot_overwrite_input_or_frozen_artifacts(frozen_bundle, project_root, tmp_path, capsys, destination):
    upload = tmp_path / 'uploads/observed.png'
    upload.parent.mkdir()
    shutil.copy2(next((project_root / 'artifacts/samples').glob('*.png')), upload)
    before = upload.read_bytes()
    metadata = frozen_bundle / 'artifacts/metadata.json'
    metadata_before = metadata.read_bytes()
    arguments = [str(upload), '--bundle', str(frozen_bundle)]
    arguments += ['--output', str(upload if destination == 'input' else metadata)] if destination != 'evidence_input' else ['--evidence', str(upload.parent)]
    with pytest.raises(SystemExit) as error:
        predict.main(arguments)
    assert error.value.code == 2
    assert upload.read_bytes() == before and metadata.read_bytes() == metadata_before
    assert 'Traceback' not in capsys.readouterr().err


def test_onnx_session_uses_verified_bytes_when_file_changes_after_check(frozen_bundle, project_root, monkeypatch):
    original = predict.verified_model_bytes
    constructor = predict.ort.InferenceSession
    seen = []

    def verified_then_changed(root, metadata):
        content = original(root, metadata)
        (Path(root) / 'artifacts/model.onnx').write_bytes(b'replaced after check')
        return content

    def session(content, *args, **kwargs):
        seen.append(type(content))
        return constructor(content, *args, **kwargs)

    monkeypatch.setattr(predict, 'verified_model_bytes', verified_then_changed)
    monkeypatch.setattr(predict.ort, 'InferenceSession', session)
    result, *_ = predict.inspect_image(next((project_root / 'artifacts/samples').glob('*.png')), frozen_bundle)
    assert np.isfinite(result['score']) and seen == [bytes]
