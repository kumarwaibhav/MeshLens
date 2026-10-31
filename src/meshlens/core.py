"""Dataset contracts and runtime-independent anomaly scoring."""

from __future__ import annotations
import csv
import hashlib
import io
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Sequence
import numpy as np
from PIL import Image, ImageOps

IMAGE_SIZE = 256
TOP_FRACTION = 0.01
MIN_IMAGE_SIDE = 32
MAX_IMAGE_SIDE = 4096
MAX_IMAGE_PIXELS = 16_000_000


def read_manifest(root: Path) -> list[dict]:
    root = Path(root).resolve()
    with (root / "data/manifest.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != [
            "path",
            "split",
            "label",
            "defect_type",
            "sha256",
            "mask_path",
        ]:
            raise ValueError("Manifest columns do not match the dataset contract")
        rows = list(reader)
    if not rows:
        raise ValueError("Manifest must contain images")
    paths, hashes = set(), set()
    for row in rows:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("Malformed manifest row")
        if row.get("split") not in {"fit", "tune", "calibration", "test"}:
            raise ValueError("Unknown dataset role")
        if row.get("label") not in {"0", "1"}:
            raise ValueError("Dataset label must be 0 or 1")
        row["label"] = int(row["label"])
        if row["split"] != "test" and row["label"] != 0:
            raise ValueError("Development roles must contain only normal images")
        for key in ["path", "mask_path"]:
            value = row.get(key, "")
            if key == "path" and not value:
                raise ValueError("Image path is required")
            if value and (
                Path(value).is_absolute()
                or PureWindowsPath(value).is_absolute()
                or "\\" in value
                or PurePosixPath(value).as_posix() != value
                or ".." in PurePosixPath(value).parts
                or not (root / value).resolve().is_relative_to(root)
            ):
                raise ValueError("Manifest path escapes dataset root")
        path = PurePosixPath(row["path"])
        defect = row["defect_type"]
        if defect not in {
            "good",
            "bent",
            "broken",
            "glue",
            "metal_contamination",
            "thread",
        }:
            raise ValueError("Unknown grid defect type")
        if row["label"] != int(defect != "good"):
            raise ValueError("Manifest label and defect type disagree")
        category = "test" if row["split"] == "test" else "train"
        if (
            path.parent != PurePosixPath("data/raw/grid") / category / defect
            or path.suffix != ".png"
        ):
            raise ValueError("Manifest path and image role disagree")
        expected_mask = (
            PurePosixPath("data/raw/grid/ground_truth")
            / defect
            / f"{path.stem}_mask.png"
        ).as_posix()
        if row["mask_path"] != (expected_mask if row["label"] else ""):
            raise ValueError("Manifest annotation and label disagree")
        digest = row.get("sha256", "")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("Image digest must be lowercase SHA256")
        if row["path"] in paths or digest in hashes:
            raise ValueError("Duplicate image path or digest in manifest")
        paths.add(row["path"])
        hashes.add(digest)
    return rows


def preprocess_image(image: Image.Image, size: int = IMAGE_SIZE) -> np.ndarray:
    if (
        not isinstance(image, Image.Image)
        or type(size) is not int
        or size < 8
        or size > 1024
    ):
        raise ValueError("Expected a decoded Pillow image and a bounded output size")
    if (
        image.width < MIN_IMAGE_SIDE
        or image.height < MIN_IMAGE_SIDE
        or image.width > MAX_IMAGE_SIDE
        or image.height > MAX_IMAGE_SIDE
        or image.width * image.height > MAX_IMAGE_PIXELS
    ):
        raise ValueError(
            "Input dimensions must be32..4096 pixels per side and at most16 megapixels"
        )
    if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) > 1:
        raise ValueError(
            "Animated images are unsupported; choose one still PNG, JPEG or WebP frame"
        )
    oriented = ImageOps.exif_transpose(image)
    if "A" in oriented.getbands() or "transparency" in oriented.info:
        rgba = oriented.convert("RGBA")
        oriented = Image.alpha_composite(
            Image.new("RGBA", rgba.size, "white"), rgba
        ).convert("RGB")
    else:
        oriented = oriented.convert("RGB")
    resized = oriented.resize((size, size), Image.Resampling.BILINEAR)
    return np.asarray(resized, dtype=np.float32).transpose(2, 0, 1).copy() / np.float32(
        255.0
    )


def residual_score(
    image: np.ndarray, reconstruction: np.ndarray, top_fraction: float = TOP_FRACTION
) -> tuple[float, np.ndarray]:
    source = np.asarray(image, dtype=np.float32)
    rebuilt = np.asarray(reconstruction, dtype=np.float32)
    if (
        source.shape != rebuilt.shape
        or source.ndim != 3
        or source.shape[0] != 3
        or min(source.shape[1:]) < 1
    ):
        raise ValueError("Expected matching nonempty RGB CHW tensors")
    if not (np.isfinite(source).all() and np.isfinite(rebuilt).all()):
        raise ValueError("Image tensors must be finite")
    if (
        np.min(source) < 0
        or np.max(source) > 1
        or np.min(rebuilt) < 0
        or np.max(rebuilt) > 1
    ):
        raise ValueError("Image tensors must be in [0,1]")
    if not np.isfinite(top_fraction) or not 0 < top_fraction <= 1:
        raise ValueError("top_fraction must lie in (0,1]")
    pixel = np.mean(np.square(source - rebuilt), axis=0)
    flat = pixel.reshape(-1)
    count = max(1, math.ceil(len(flat) * top_fraction))
    top = np.partition(flat, len(flat) - count)[-count:]
    return float(np.mean(top, dtype=np.float64)), pixel


def calibrate_threshold(scores: Sequence[float], alpha: float = 0.05) -> float:
    values = np.asarray(scores, dtype=np.float64)
    if (
        values.ndim != 1
        or values.size == 0
        or not np.isfinite(values).all()
        or np.any(values < 0)
    ):
        raise ValueError("Calibration requires nonempty, finite, nonnegative scores")
    if not np.isfinite(alpha) or not 0 < alpha < 1:
        raise ValueError("alpha must lie in (0,1)")
    rank = math.ceil((len(values) + 1) * (1 - alpha))
    if rank > len(values):
        raise ValueError("Insufficient normal calibration scores for requested alpha")
    return float(np.sort(values)[rank - 1])


def load_images(root: Path, rows: list[dict]) -> np.ndarray:
    if not rows:
        raise ValueError("At least one manifest image is required")
    root = Path(root).resolve()
    images = []
    for row in rows:
        path = (root / row["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Image path escapes dataset root")
        try:
            content = path.read_bytes()
        except OSError as error:
            raise ValueError(
                f"Dataset image unavailable: {row['path']}; run scripts/download_data.py"
            ) from error
        if hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise ValueError(
                f"Dataset image checksum mismatch: {row['path']}; restore the pinned dataset"
            )
        with Image.open(io.BytesIO(content)) as image:
            images.append(preprocess_image(image))
    return np.stack(images)
