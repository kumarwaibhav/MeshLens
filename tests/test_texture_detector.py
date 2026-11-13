"""Behavioral checks for the normal-lattice detector's public entry point."""

import unittest

import numpy as np

from meshlens.texture_detector import TextureQualityError, score_texture


MODEL = {
    "kind": "normal-lattice-v1", "image_size": 256, "variant": "joint",
    "tail_fraction": 0.005, "fit_scale": 1.0, "score_decimals": 8,
}


def periodic_mesh():
    y, x = np.mgrid[:256, :256]
    gray = 128 + 42 * np.sin(2 * np.pi * (x + 0.4 * y) / 24)
    gray += 36 * np.cos(2 * np.pi * (0.2 * x - y) / 23)
    rgb = np.repeat(np.floor(gray + 0.5).astype(np.uint8)[..., None], 3, axis=2)
    return rgb.astype(np.float32).transpose(2, 0, 1) / np.float32(255)


class TextureDetectorTests(unittest.TestCase):
    def test_flat_frames_require_a_quality_review(self):
        for level in (0.0, 0.5, 1.0):
            with self.subTest(level=level):
                with self.assertRaises(TextureQualityError) as error:
                    score_texture(np.full((3, 256, 256), level, np.float32), MODEL)
                self.assertEqual(error.exception.code, "mesh-pattern-unavailable")

    def test_invalid_input_and_model_never_return_a_decision_score(self):
        image = periodic_mesh()
        bad_models = [
            {**MODEL, "kind": "another-model"}, {**MODEL, "variant": "unknown"},
            *({**MODEL, "fit_scale": value} for value in (0, -1, True, float("inf"), float("nan"))),
            *({**MODEL, "tail_fraction": value} for value in (0, 2, True, float("nan"))),
            {**MODEL, "score_decimals": 4},
        ]
        for bad in bad_models:
            with self.subTest(model=bad):
                with self.assertRaises(ValueError):
                    score_texture(image, bad)
        for bad_image in (image[:, :-1, :], image * float("nan"), image + 1):
            with self.assertRaises(ValueError):
                score_texture(bad_image, MODEL)

    def test_a_local_texture_change_has_a_localized_stronger_signal(self):
        clean = periodic_mesh()
        before = clean.copy()
        damaged = clean.copy()
        damaged[:, 112:144, 112:144] = 0.9
        clean_score, _, clean_periodicity = score_texture(clean, MODEL)
        damaged_score, anomaly, damaged_periodicity = score_texture(damaged, MODEL)
        self.assertGreater(damaged_score, clean_score * 2)
        location = np.unravel_index(int(np.argmax(anomaly)), anomaly.shape)
        self.assertTrue(all(96 <= coordinate < 160 for coordinate in location))
        self.assertTrue(np.isfinite(anomaly).all())
        self.assertGreaterEqual(float(anomaly.min()), 0)
        self.assertTrue(0 <= clean_periodicity <= 1 and 0 <= damaged_periodicity <= 1)
        np.testing.assert_array_equal(clean, before)


if __name__ == "__main__":
    unittest.main()
