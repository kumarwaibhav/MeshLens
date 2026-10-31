"""Independent score mathematics, preprocessing and frozen-normal calibration."""
import math

import numpy as np
from PIL import Image
import pytest

from meshlens.core import calibrate_threshold, preprocess_image, residual_score


def test_preprocess_outputs_rgb_chw_float32_unit_interval():
    source = Image.new('RGB', (57, 103), (0, 128, 255))
    values = preprocess_image(source, size=64)
    assert values.shape == (3, 64, 64)
    assert values.dtype == np.float32
    np.testing.assert_array_equal(values[0], 0.0)
    np.testing.assert_allclose(values[1], 128 / 255, atol=1e-7)
    np.testing.assert_array_equal(values[2], 1.0)


@pytest.mark.parametrize('mode,color', [('L', 127), ('RGBA', (17, 39, 71, 0))])
def test_non_rgb_images_have_explicit_three_channel_conversion(mode, color):
    image = Image.new(mode, (32, 32), color)
    values = preprocess_image(image, size=32)
    expected = (np.ones((3, 32, 32), dtype=np.float32) if mode == 'RGBA'
                else np.asarray(image.convert('RGB'), dtype=np.float32).transpose(2, 0, 1) / 255)
    np.testing.assert_allclose(values, expected, atol=1e-7)


def test_residual_uses_rgb_mean_square_and_upper_tail_mean():
    image = np.zeros((3, 2, 2), dtype=np.float32)
    reconstruction = np.array([[[0, .5], [1, .25]]] * 3, dtype=np.float32)
    score, residual = residual_score(image, reconstruction, top_fraction=.5)
    np.testing.assert_allclose(residual, [[0, .25], [1, .0625]], atol=1e-8)
    assert score == pytest.approx(.625)
    all_score, _ = residual_score(image, reconstruction, top_fraction=1)
    assert all_score == pytest.approx(.328125)


def test_score_uses_ceiling_for_small_upper_tail():
    image = np.zeros((3, 3, 3), dtype=np.float32)
    reconstruction = np.zeros_like(image)
    reconstruction[:, 0, 0] = 1
    score, _ = residual_score(image, reconstruction, top_fraction=.01)
    assert score == pytest.approx(1.0)


def test_rgb_channels_are_averaged_not_summed():
    image = np.zeros((3, 2, 2), dtype=np.float32)
    reconstruction = np.zeros_like(image)
    reconstruction[0] = 1
    score, heatmap = residual_score(image, reconstruction, top_fraction=1)
    np.testing.assert_allclose(heatmap, 1 / 3)
    assert score == pytest.approx(1 / 3)


@pytest.mark.parametrize('fraction', [0, -0.1, 1.1, math.nan, math.inf])
def test_score_rejects_invalid_tail_fraction(fraction):
    image = np.zeros((3, 4, 4), dtype=np.float32)
    with pytest.raises(ValueError):
        residual_score(image, image, top_fraction=fraction)


@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_score_rejects_nonfinite_model_outputs(bad):
    image = np.zeros((3, 4, 4), dtype=np.float32)
    output = image.copy()
    output[0, 0, 0] = bad
    with pytest.raises(ValueError):
        residual_score(image, output)


def test_score_rejects_mismatched_shapes():
    with pytest.raises(ValueError):
        residual_score(np.zeros((3, 4, 4)), np.zeros((3, 4, 5)))


@pytest.mark.parametrize('bad', [-.01, 1.01])
def test_score_rejects_unscaled_or_out_of_range_images(bad):
    image = np.zeros((3, 4, 4), dtype=np.float32)
    output = image.copy()
    output[0, 0, 0] = bad
    with pytest.raises(ValueError):
        residual_score(image, output)


def test_calibration_is_the_finite_sample_upper_order_statistic():
    scores = np.arange(1, 53, dtype=np.float64)
    rank = math.ceil((len(scores) + 1) * .95)
    assert rank == 51
    threshold = calibrate_threshold(scores, alpha=.05)
    assert threshold == scores[rank - 1]
    assert sum(scores > threshold) == 1
    assert calibrate_threshold(scores[::-1], alpha=.05) == threshold


def test_insufficient_calibration_cannot_claim_an_unsupported_tail_level():
    with pytest.raises(ValueError, match='[Ii]nsufficient|[Cc]alibration|[Ss]cores|[Ss]amples'):
        calibrate_threshold([.2, .7, .4], alpha=.05)


def test_tied_normal_calibration_has_no_strict_threshold_exceedance():
    assert calibrate_threshold([.3] * 52, alpha=.05) == .3


@pytest.mark.parametrize('scores,alpha', [([], .05), ([-.1], .05), ([float('nan')], .05), ([float('inf')], .05),
                                          ([1, 2], 0), ([1, 2], 1), ([1, 2], -.5), ([1, 2], math.nan)])
def test_calibration_rejects_invalid_inputs(scores, alpha):
    with pytest.raises(ValueError):
        calibrate_threshold(scores, alpha=alpha)
