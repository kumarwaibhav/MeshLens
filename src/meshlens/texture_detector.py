"""Normal-fitted mesh anomaly scoring from neighboring lattice repeats.

The first step estimates repeat vectors independently for each image. Small
patches are then compared with their neighbors across those vectors. One
translation is allowed per patch to absorb minor normal registration changes.
The image score measures unusually poor repeat matches in the largest errors.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


IMAGE_SIZE = 256
WINDOW_RADII = (3, 9)
MODEL_KIND = "normal-lattice-v1"
VARIANTS = ("local", "cell", "relative", "mixed", "joint")
SCORE_DECIMALS = 8


class TextureQualityError(ValueError):
    """An image has no reliable repeating-grid reference for this detector."""

    code = "mesh-pattern-unavailable"


@dataclass(frozen=True)
class TextureEvidence:
    local: np.ndarray
    cell: np.ndarray
    periodicity: float
    repeat_count: int = 0


def _box_sum(image: np.ndarray, radius: int) -> np.ndarray:
    return _box_sum_from_integral(_integral(image), radius)


def _integral(image: np.ndarray) -> np.ndarray:
    return np.pad(image.cumsum(axis=1).cumsum(axis=0), ((1, 0), (1, 0)))


def _box_sum_from_integral(integral: np.ndarray, radius: int) -> np.ndarray:
    height, width = (dimension - 1 for dimension in integral.shape)
    rows = np.arange(height)
    cols = np.arange(width)
    top = np.maximum(rows - radius, 0)
    bottom = np.minimum(rows + radius + 1, height)
    left = np.maximum(cols - radius, 0)
    right = np.minimum(cols + radius + 1, width)
    return (
        integral[bottom[:, None], right[None, :]]
        - integral[top[:, None], right[None, :]]
        - integral[bottom[:, None], left[None, :]]
        + integral[top[:, None], left[None, :]]
    )


def _box_mean(image: np.ndarray, radius: int) -> np.ndarray:
    height, width = image.shape
    rows = np.arange(height)
    cols = np.arange(width)
    row_count = np.minimum(rows + radius + 1, height) - np.maximum(rows - radius, 0)
    col_count = np.minimum(cols + radius + 1, width) - np.maximum(cols - radius, 0)
    return _box_sum(image, radius) / (row_count[:, None] * col_count[None, :])


def _lattice(structure: np.ndarray) -> tuple[list[tuple[float, float]], float]:
    size = structure.shape[0]
    spectrum = np.fft.rfft2(structure)
    correlation = np.fft.irfft2(np.square(np.abs(spectrum)), s=structure.shape)
    if correlation[0, 0] < 1e-9:
        return [], 0.0
    correlation /= correlation[0, 0]
    radius = round(0.19 * size)
    minimum = 0.055 * size
    ys, xs = np.mgrid[-radius : radius + 1, 0 : radius + 1]
    length = np.hypot(ys, xs)
    peak = correlation[ys % size, xs]
    allowed = (length >= minimum) & (length <= radius) & ((xs > 0) | (ys > 0))
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
        allowed &= peak >= correlation[(ys + dy) % size, (xs + dx) % size]
    candidates = sorted(
        ((float(value), int(y), int(x)) for value, y, x in zip(peak[allowed], ys[allowed], xs[allowed])),
        key=lambda p: (-(p[0] - 0.003 * math.hypot(p[1], p[2])), p[1], p[2]),
    )
    if not candidates:
        return [], 0.0
    periodicity = max(0.0, min(1.0, max(p[0] for p in candidates)))
    selected: list[tuple[int, int]] = []
    for strength, y, x in candidates:
        if strength < max(0.1, periodicity * 0.55):
            continue
        if any(
            abs(y * px - x * py) < 0.24 * math.hypot(y, x) * math.hypot(py, px)
            for py, px in selected
        ):
            continue
        selected.append((y, x))
        if len(selected) == 3:
            break

    def interpolate(before: float, center: float, after: float) -> float:
        curvature = before - 2 * center + after
        if curvature >= -1e-12:
            return 0.0
        return float(np.clip(0.5 * (before - after) / curvature, -0.5, 0.5))

    result: list[tuple[float, float]] = []
    for y, x in selected:
        center = correlation[y % size, x]
        offset_y = interpolate(correlation[(y - 1) % size, x], center, correlation[(y + 1) % size, x])
        offset_x = interpolate(correlation[y % size, (x - 1) % size], center, correlation[y % size, (x + 1) % size])
        result.append((y + offset_y, x + offset_x))
        result.append((-y - offset_y, -x - offset_x))
    return result, periodicity


def _errors_at_shift(
    structure: np.ndarray, detail: np.ndarray, shift_y: float, shift_x: float
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    size = structure.shape[0]
    dy, dx = math.floor(shift_y), math.floor(shift_x)
    ay, ax = shift_y - dy, shift_x - dx
    y0, y1 = max(0, -dy), min(size, size - dy - 1)
    x0, x1 = max(0, -dx), min(size, size - dx - 1)
    source = np.s_[y0:y1, x0:x1]
    sy, ey, sx, ex = y0 + dy, y1 + dy, x0 + dx, x1 + dx

    def shifted(image: np.ndarray) -> np.ndarray:
        top = image[sy:ey, sx:ex] * (1 - ax) + image[sy:ey, sx + 1 : ex + 1] * ax
        bottom = image[sy + 1 : ey + 1, sx:ex] * (1 - ax) + image[sy + 1 : ey + 1, sx + 1 : ex + 1] * ax
        return top * (1 - ay) + bottom * ay

    error = np.zeros_like(structure)
    error[source] = np.square(structure[source] - shifted(structure))
    error[source] += 0.5 * np.square(detail[source] - shifted(detail))
    return error, (y0, y1, x0, x1)


def analyze_texture(tensor: np.ndarray) -> TextureEvidence:
    """Analyze a canonical RGB CHW input in [0, 1]."""
    source = np.asarray(tensor, dtype=np.float64)
    if source.shape != (3, IMAGE_SIZE, IMAGE_SIZE) or not np.isfinite(source).all():
        raise ValueError(f"Expected a finite RGB 3×{IMAGE_SIZE}×{IMAGE_SIZE} tensor")
    if source.min() < 0 or source.max() > 1:
        raise ValueError("Texture input channels must lie in [0,1]")
    gray = (source[0] + source[1] + source[2]) / 3
    smooth = _box_mean(gray, 1)
    structure = smooth - _box_mean(smooth, 15)
    scale = np.sqrt(_box_mean(np.square(structure), 15) + 0.002)
    structure = structure / scale
    detail = (gray - smooth) / scale
    shifts, periodicity = _lattice(structure)
    if not shifts:
        blank = np.zeros_like(structure)
        return TextureEvidence(blank, blank.copy(), periodicity)

    indices = np.arange(IMAGE_SIZE)
    best = [np.full_like(structure, np.inf) for _ in WINDOW_RADII]
    second = [np.full_like(structure, np.inf) for _ in WINDOW_RADII]
    for shift_y, shift_x in shifts:
        neighbor = [np.full_like(structure, np.inf) for _ in WINDOW_RADII]
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                errors, (y0, y1, x0, x1) = _errors_at_shift(structure, detail, shift_y + dy, shift_x + dx)
                integral = _integral(errors)
                for i, radius in enumerate(WINDOW_RADII):
                    count_y = np.maximum(0, np.minimum(indices + radius + 1, y1) - np.maximum(indices - radius, y0))
                    count_x = np.maximum(0, np.minimum(indices + radius + 1, x1) - np.maximum(indices - radius, x0))
                    count = count_y[:, None] * count_x[None, :]
                    mean = _box_sum_from_integral(integral, radius) / np.maximum(count, 1)
                    minimum_count = math.ceil((radius + 1) * (2 * radius + 1) * 0.5)
                    mean[count < minimum_count] = np.inf
                    np.minimum(neighbor[i], mean, out=neighbor[i])
        for i, distances in enumerate(neighbor):
            np.minimum(second[i], np.maximum(best[i], distances), out=second[i])
            np.minimum(best[i], distances, out=best[i])
    maps = []
    for closest, next_closest in zip(best, second):
        next_closest = np.where(np.isfinite(next_closest), next_closest, closest)
        evidence = np.maximum(0, np.where(np.isfinite(closest), (closest + next_closest) / 2, 0.0))
        maps.append(evidence)
    return TextureEvidence(maps[0], maps[1], periodicity, len(shifts) // 2)


def texture_map(evidence: TextureEvidence, variant: str) -> np.ndarray:
    """Apply one of the fixed development configurations."""
    local = evidence.local
    cell = evidence.cell
    if variant == "local":
        return local
    if variant == "cell":
        return cell
    if variant == "relative":
        return local / (float(np.median(local)) + 0.012)
    if variant == "mixed":
        return local / math.sqrt(float(np.median(local)) + 0.012)
    if variant == "joint":
        local_component = local / math.sqrt(float(np.median(local)) + 0.012)
        cell_component = cell / math.sqrt(float(np.median(cell)) + 0.012)
        return 0.6 * local_component + 0.4 * cell_component
    raise ValueError(f"Unknown texture variant: {variant}")


def score_map(anomaly: np.ndarray, tail_fraction: float = 0.005) -> float:
    """Average the largest local scores in a fixed fraction of the image."""
    if isinstance(tail_fraction, (bool, np.bool_)) or not 0 < tail_fraction <= 1:
        raise ValueError("Texture tail fraction must lie in (0,1]")
    flat = np.asarray(anomaly, dtype=np.float64).reshape(-1)
    if not flat.size or not np.isfinite(flat).all() or np.any(flat < 0):
        raise ValueError("Expected a nonempty, finite, nonnegative texture map")
    count = max(1, math.ceil(flat.size * tail_fraction))
    return float(np.mean(np.partition(flat, flat.size - count)[-count:]))


def score_texture(tensor: np.ndarray, model: dict) -> tuple[float, np.ndarray, float]:
    """Return the fit-normalized score, local anomaly map, and repeat strength."""
    if not isinstance(model, dict) or model.get("kind") != MODEL_KIND or model.get("image_size") != IMAGE_SIZE:
        raise ValueError("Unexpected texture detector artifact contract")
    scale = model.get("fit_scale")
    if type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0:
        raise ValueError("The normal reference score must be finite and positive")
    if model.get("variant") not in VARIANTS:
        raise ValueError("Unexpected texture detector variant")
    tail = model.get("tail_fraction")
    if type(tail) not in (int, float) or not math.isfinite(tail) or not 0 < tail <= 1:
        raise ValueError("Texture tail fraction must lie in (0,1]")
    if model.get("score_decimals", SCORE_DECIMALS) != SCORE_DECIMALS:
        raise ValueError("Unexpected texture score quantization")
    evidence = analyze_texture(tensor)
    if evidence.repeat_count < 2:
        raise TextureQualityError("A repeating mesh pattern could not be established. Use a sharp, evenly lit close-up of the trained grid material.")
    anomaly = texture_map(evidence, model["variant"]) / scale
    raw_score = score_map(anomaly, tail)
    quantizer = 10 ** SCORE_DECIMALS
    score = math.floor(raw_score * quantizer + 0.5) / quantizer
    return score, anomaly, evidence.periodicity
