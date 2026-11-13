#!/usr/bin/env python3
"""Build a deterministic, paired synthetic development suite from tuning normals.

Run ``python scripts/download_data.py --verify-only`` for the complete source
audit. This generator reads the manifest and opens only the frozen tune images.
The resulting examples are model-selection proxies, with synthetic labels.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, __version__ as pillow_version

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from meshlens.core import read_manifest  # noqa: E402

SCHEMA_VERSION = 1
DEFAULT_SEED = 20261109
FIELDS = (
    "sample_id", "path", "label", "defect_type", "source_path", "source_sha256",
    "sha256", "seed", "width", "height", "source_split",
)


def _radius(y: np.ndarray, x: np.ndarray, ry: float, rx: float, angle: float) -> np.ndarray:
    along = x * np.cos(angle) + y * np.sin(angle)
    across = y * np.cos(angle) - x * np.sin(angle)
    return np.hypot(along / rx, across / ry)


def _bend(patch, y, x, scale, rng):
    # Move the wires continuously, with the displacement tapering to zero.
    angle = rng.uniform(0, np.pi)
    radius = _radius(y, x, scale * rng.uniform(40, 75), scale * rng.uniform(65, 112), angle)
    shift = scale * rng.uniform(12, 38) * np.maximum(1 - radius * radius, 0) ** 2
    center = patch.shape[0] // 2
    yy = np.clip(y + center + shift * np.cos(angle), 0, patch.shape[0] - 1)
    xx = np.clip(x + center - shift * np.sin(angle), 0, patch.shape[1] - 1)
    y0 = yy.astype(np.intp)
    x0 = xx.astype(np.intp)
    y1 = np.minimum(y0 + 1, patch.shape[0] - 1)
    x1 = np.minimum(x0 + 1, patch.shape[1] - 1)
    wy, wx = yy - y0, xx - x0
    top = patch[y0, x0] * (1 - wx) + patch[y0, x1] * wx
    bottom = patch[y1, x0] * (1 - wx) + patch[y1, x1] * wx
    return top * (1 - wy) + bottom * wy


def _gap(patch, y, x, scale, rng):
    # A short wire section is replaced by a softly blended local background.
    radius = _radius(
        y, x, scale * rng.uniform(11, 24), scale * rng.uniform(18, 41), rng.uniform(0, np.pi)
    )
    alpha = np.clip((1 - radius) * 6, 0, 1) * rng.uniform(0.83, 1.0)
    background = np.percentile(patch, 83) + 4 * np.sin((x + y * 0.4) / (17 * scale))
    return (1 - alpha) * patch + alpha * background


def _fibre(patch, y, x, scale, rng):
    # A gently curved, thin foreign strand crosses the regular grid.
    angle = rng.uniform(0, np.pi)
    length = scale * rng.uniform(56, 174)
    curve = scale * rng.uniform(-27, 27)
    center = patch.shape[0] // 2
    t = np.linspace(-1, 1, 41)
    along = t * length / 2
    across = curve * (1 - t * t)
    px = center + along * np.cos(angle) - across * np.sin(angle)
    py = center + along * np.sin(angle) + across * np.cos(angle)
    mask = Image.new("L", (patch.shape[1], patch.shape[0]))
    ImageDraw.Draw(mask).line(
        list(zip(px.tolist(), py.tolist())),
        fill=255,
        width=max(1, round(scale * rng.uniform(3, 11))),
    )
    mask = mask.filter(ImageFilter.GaussianBlur(max(0.35, 0.85 * scale)))
    alpha = np.asarray(mask, dtype=np.float32) * (rng.uniform(0.62, 0.96) / 255)
    light = np.clip(np.median(patch) + rng.choice((-1, 1)) * rng.uniform(36, 88), 12, 244)
    return (1 - alpha) * patch + alpha * light


def _glue(patch, y, x, scale, rng):
    # A translucent smear retains wire details while softening their contrast.
    radius = _radius(
        y, x, scale * rng.uniform(24, 56), scale * rng.uniform(30, 74), rng.uniform(0, np.pi)
    )
    theta = np.arctan2(y, x)
    edge = radius / (1 + 0.16 * np.sin(3 * theta + rng.uniform(0, 2 * np.pi)))
    alpha = np.clip((1 - edge) * 5, 0, 1) * rng.uniform(0.38, 0.72)
    soft = Image.fromarray(patch.astype(np.uint8)).filter(ImageFilter.GaussianBlur(6 * scale))
    tint = rng.choice((-1, 1)) * rng.uniform(12, 39)
    rim = 8 * np.exp(-((edge - 0.82) / 0.12) ** 2) * np.clip(1 - edge, 0, 1)
    return (1 - alpha) * patch + alpha * (np.asarray(soft, dtype=np.float32) + tint) + rim


def _contamination(patch, y, x, scale, rng):
    # An irregular opaque flake has a directional highlight and a faint shadow.
    ry, rx = scale * rng.uniform(9, 30, size=2)
    angle = rng.uniform(0, np.pi)
    theta = np.arctan2(y, x)
    outline = 1 + 0.14 * np.sin(5 * theta + angle) + 0.11 * np.sin(3 * theta - angle)
    radius = _radius(y, x, ry, rx, angle) / outline
    alpha = np.clip((1 - radius) * 8, 0, 1) * rng.uniform(0.83, 1)
    shadow = 16 * np.clip(1 - _radius(y - 3 * scale, x - 4 * scale, ry, rx, angle) / 1.25, 0, 1)
    surface = np.median(patch) + rng.choice((-1, 1)) * rng.uniform(28, 76)
    surface = surface + 21 * (x * np.cos(angle) + y * np.sin(angle)) / max(rx, ry)
    return (1 - alpha) * (patch - shadow) + alpha * surface


DEFECTS = {
    "bend": _bend,
    "gap": _gap,
    "fibre": _fibre,
    "glue": _glue,
    "contamination": _contamination,
}


def simulate_defect(image: np.ndarray, defect_type: str, seed: int) -> np.ndarray:
    if image.ndim != 2 or image.dtype != np.uint8 or min(image.shape) < 128:
        raise ValueError("Expected a grayscale uint8 image with sides of at least 128 pixels.")
    if defect_type not in DEFECTS:
        raise ValueError(f"Unknown synthetic defect {defect_type!r}")

    rng = np.random.default_rng(seed)
    scale = min(image.shape) / 1024
    radius = round(135 * scale)
    search = max(2, round(20 * scale))
    margin = radius + search + 1
    cy = int(rng.integers(margin, image.shape[0] - margin))
    cx = int(rng.integers(margin, image.shape[1] - margin))
    if defect_type in {"bend", "gap"}:
        nearby = image[cy - search : cy + search + 1, cx - search : cx + search + 1]
        # Dark pixels anchor defects to a wire in the known-good source.
        wire_y, wire_x = np.where(nearby <= np.percentile(nearby, 27))
        anchor = rng.integers(len(wire_y))
        cy += int(wire_y[anchor]) - search
        cx += int(wire_x[anchor]) - search

    region = (slice(cy - radius, cy + radius + 1), slice(cx - radius, cx + radius + 1))
    y, x = np.mgrid[-radius : radius + 1, -radius : radius + 1].astype(np.float32)
    patch = image[region].astype(np.float32)
    changed = DEFECTS[defect_type](patch, y, x, scale, rng)
    result = image.copy()
    result[region] = np.clip(np.rint(changed), 0, 255).astype(np.uint8)
    if np.array_equal(result[region], image[region]):
        raise ValueError(f"Synthetic {defect_type} produced no visible change.")
    return result


def _sample_seed(master_seed: int, source_sha: str, variant: str) -> int:
    identity = f"{SCHEMA_VERSION}:{master_seed}:{source_sha}:{variant}".encode("ascii")
    return int.from_bytes(hashlib.sha256(identity).digest()[:4], "big")


def make_suite(root: Path, output: Path, seed: int = DEFAULT_SEED) -> dict:
    root = root.resolve()
    output = output.absolute()
    if output.resolve().is_relative_to(root):
        raise ValueError("Write generated development data outside the source repository.")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Choose a new output directory: {output}")

    source_manifest = root / "data/manifest.csv"
    manifest_sha = hashlib.sha256(source_manifest.read_bytes()).hexdigest()
    source_provenance = json.loads((root / "data/provenance.json").read_text(encoding="utf-8"))
    if manifest_sha != source_provenance["manifest_sha256"]:
        raise ValueError("Source manifest does not match its pinned provenance.")
    roles = read_manifest(root)
    if Counter(row["split"] for row in roles) != source_provenance["split_counts"]:
        raise ValueError("Source partition counts do not match provenance.")
    tune = sorted((row for row in roles if row["split"] == "tune"), key=lambda row: row["path"])
    if len(tune) != 52 or any(row["label"] for row in tune):
        raise ValueError("Expected the 52 pinned, clean tuning images.")

    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory(prefix=".development-", dir=output.parent) as temporary:
        stage = Path(temporary) / "suite"
        (stage / "samples").mkdir(parents=True)
        for row in tune:
            source = root / row["path"]
            raw = source.read_bytes()
            if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise ValueError(f"Tuning image checksum mismatch: {row['path']}")
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != "PNG" or image.mode != "L" or image.size != (1024, 1024):
                    raise ValueError(f"Unexpected tuning image format: {row['path']}")
                pixels = np.asarray(image, dtype=np.uint8).copy()
            for variant in ("clean", *DEFECTS):
                sample_id = f"tune-{source.stem}-{variant}"
                relative = f"samples/{sample_id}.png"
                label = int(variant != "clean")
                sample_seed = _sample_seed(seed, row["sha256"], variant)
                content = raw
                if label:
                    stream = io.BytesIO()
                    result = simulate_defect(pixels, variant, sample_seed)
                    Image.fromarray(result).save(stream, format="PNG", compress_level=1)
                    content = stream.getvalue()
                (stage / relative).write_bytes(content)
                rows.append({
                    "sample_id": sample_id,
                    "path": relative,
                    "label": label,
                    "defect_type": variant,
                    "source_path": row["path"],
                    "source_sha256": row["sha256"],
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "seed": sample_seed,
                    "width": pixels.shape[1],
                    "height": pixels.shape[0],
                    "source_split": "tune",
                })

        with (stage / "manifest.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        provenance = {
            "schema_version": SCHEMA_VERSION,
            "purpose": "Development-only paired controls and synthetic defects for model selection",
            "source_role": "tune",
            "source_manifest_sha256": manifest_sha,
            "manifest_sha256": hashlib.sha256((stage / "manifest.csv").read_bytes()).hexdigest(),
            "source_count": len(tune),
            "samples_by_type": dict(Counter(row["defect_type"] for row in rows)),
            "generator_seed": seed,
            "runtime": {"numpy": np.__version__, "pillow": pillow_version},
            "dataset": {key: source_provenance[key] for key in (
                "dataset", "category", "official_source", "license", "license_url", "copyright",
                "mirror_revision", "archive_sha256",
            )},
        }
        (stage / "provenance.json").write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        stage.rename(output)
    return provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory outside the repository")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    try:
        provenance = make_suite(ROOT, args.output, args.seed)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
