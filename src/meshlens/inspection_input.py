"""Deterministic RGB input for the inspection detector.

The area filter uses integer pixel overlaps in both axes. The browser uses
the same rounding and alpha compositing on its decoded pixels.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageOps

from meshlens.core import MAX_IMAGE_PIXELS, MAX_IMAGE_SIDE, MIN_IMAGE_SIDE

PREPROCESSING_ID = "area-rgb8-v1"


def _area_windows(source_size: int, output_size: int):
    for index in range(output_size):
        start = index * source_size
        end = start + source_size
        first = start // output_size
        stop = (end + output_size - 1) // output_size
        edges = np.arange(first, stop, dtype=np.int64) * output_size
        weights = np.minimum(end, edges + output_size) - np.maximum(start, edges)
        yield first, stop, weights.astype(np.uint32)


def inspection_rgb8(image: Image.Image, size: int) -> np.ndarray:
    """Return a square, uint8 HWC RGB image from a bounded still image."""
    if not isinstance(image, Image.Image) or type(size) is not int or not 8 <= size <= 1024:
        raise ValueError("Expected a decoded image and an inspection size of 8..1024")
    width, height = image.size
    if (
        not MIN_IMAGE_SIDE <= width <= MAX_IMAGE_SIDE
        or not MIN_IMAGE_SIDE <= height <= MAX_IMAGE_SIDE
        or width * height > MAX_IMAGE_PIXELS
    ):
        raise ValueError("Inspection input must be 32..4096 pixels per side and at most 16 megapixels")
    if getattr(image, "n_frames", 1) != 1:
        raise ValueError("Inspection requires a single still image")

    oriented = ImageOps.exif_transpose(image)
    if "A" in oriented.getbands() or "transparency" in oriented.info:
        rgba = np.asarray(oriented.convert("RGBA"), dtype=np.uint16)
        alpha = rgba[..., 3:4]
        rgb = ((rgba[..., :3] * alpha + 255 * (255 - alpha) + 127) // 255).astype(np.uint8)
    else:
        rgb = np.asarray(oriented.convert("RGB"), dtype=np.uint8)

    height, width, _ = rgb.shape
    if height == size and width == size:
        return np.ascontiguousarray(rgb)

    horizontal = np.empty((height, size, 3), dtype=np.uint32)
    for x, (first, stop, weights) in enumerate(_area_windows(width, size)):
        horizontal[:, x, :] = np.sum(
            rgb[:, first:stop, :] * weights[None, :, None], axis=1, dtype=np.uint32
        )
    result = np.empty((size, size, 3), dtype=np.uint8)
    area = width * height
    for y, (first, stop, weights) in enumerate(_area_windows(height, size)):
        sums = np.sum(
            horizontal[first:stop, :, :] * weights[:, None, None], axis=0, dtype=np.uint64
        )
        result[y, :, :] = (sums + area // 2) // area
    return result
