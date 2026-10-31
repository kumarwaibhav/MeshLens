"""Frozen trained model checks that remain mandatory without raw dataset files."""
from pathlib import Path
import json

import numpy as np
import onnxruntime as ort
from PIL import Image
import pytest
import torch

from meshlens.core import preprocess_image, residual_score
from meshlens.model import ConvAutoencoder, load_checkpoint


@pytest.fixture(scope='module')
def frozen_model():
    root = Path(__file__).resolve().parents[1]
    checkpoint = root / 'artifacts/checkpoint.pt'
    assert checkpoint.is_file(), 'The trained checkpoint must be bundled in a source checkout.'
    model, config = load_checkpoint(checkpoint)
    assert not model.training
    return root, model, config


@pytest.fixture(scope='module')
def tracked_images(frozen_model):
    root, _, _ = frozen_model
    images = sorted((root / 'artifacts/samples').glob('*.png'))
    assert len(images) == 18, 'All 18 tracked real samples are required for clean-checkout inference.'
    values = {}
    for path in images:
        with Image.open(path) as source:
            values[path.name] = preprocess_image(source)
    return values


def test_trained_checkpoint_can_reconstruct_a_tracked_real_image(frozen_model, tracked_images):
    root, model, config = frozen_model
    metadata = json.loads((root / 'artifacts/metadata.json').read_text())
    published = {item['filename']: item for item in json.loads((root / 'artifacts/samples.json').read_text())['samples']}
    assert set(published) == set(tracked_images)
    for filename, image in tracked_images.items():
        with torch.inference_mode():
            output = model(torch.from_numpy(image[None])).numpy()
        assert output.shape == (1, 3, 256, 256)
        assert np.isfinite(output).all()
        assert 0 <= output.min() <= output.max() <= 1
        score, heatmap = residual_score(image, output[0], config.get('top_fraction', .01))
        assert np.isfinite(score) and 0 <= score <= 1
        assert heatmap.shape == (256, 256)
        assert score == pytest.approx(published[filename]['expected_score'], abs=2e-6)
        assert (score > metadata['threshold']) == bool(published[filename]['expected_anomaly'])
    assert config['epochs'] == 26


def test_onnx_matches_pytorch_reconstruction_and_decision_score(frozen_model, tracked_images):
    root, model, config = frozen_model
    export = root / 'artifacts/model.onnx'
    assert export.is_file(), 'The exact deployed ONNX graph must be committed.'
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(export), sess_options=options, providers=['CPUExecutionProvider'])
    fraction = config.get('top_fraction', .01)
    threshold = json.loads((root / 'artifacts/metadata.json').read_text())['threshold']
    for image in tracked_images.values():
        with torch.inference_mode():
            expected = model(torch.from_numpy(image[None])).numpy()
        actual = session.run(None, {session.get_inputs()[0].name: image[None]})[0]
        np.testing.assert_allclose(actual, expected, atol=2e-5, rtol=2e-5)
        expected_score, expected_heatmap = residual_score(image, expected[0], fraction)
        actual_score, actual_heatmap = residual_score(image, actual[0], fraction)
        assert actual_score == pytest.approx(expected_score, abs=2e-6)
        assert (actual_score > threshold) == (expected_score > threshold)
        np.testing.assert_allclose(actual_heatmap, expected_heatmap, atol=2e-6)


@pytest.mark.parametrize('latent_channels', [4, 8])
def test_autoencoder_preserves_patch_shape_and_sigmoid_range(latent_channels):
    model = ConvAutoencoder(latent_channels).eval()
    with torch.inference_mode():
        result = model(torch.zeros((2, 3, 64, 64)))
    assert result.shape == (2, 3, 64, 64)
    assert torch.isfinite(result).all()
    assert torch.all((result >= 0) & (result <= 1))
