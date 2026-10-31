#!/usr/bin/env python3
"""Inspect one still image using the frozen MeshLens ONNX model locally.

Owner: Kumar Waibhav Akshat <kwa.waibhav@gmail.com>.
"""

from __future__ import annotations
import argparse
import io
import json
from pathlib import Path
import time
import numpy as np
import onnxruntime as ort
from PIL import Image, UnidentifiedImageError
from meshlens.artifacts import load_frozen_metadata, verified_model_bytes
from meshlens.core import preprocess_image, residual_score

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 12 * 1024 * 1024


def reject_animation_container(content: bytes) -> None:
    """Reject all APNG/WebP animation containers, including singleton frames."""
    if content.startswith(bytes([137, 80, 78, 71, 13, 10, 26, 10])):
        offset = 8
        while offset + 12 <= len(content):
            length = int.from_bytes(content[offset : offset + 4], "big")
            kind = content[offset + 4 : offset + 8]
            if offset + length + 12 > len(content):
                break
            if kind in {b"acTL", b"fcTL", b"fdAT"}:
                raise ValueError(
                    "Animated PNG images are unsupported; select one still frame"
                )
            if kind == b"IEND":
                break
            offset += length + 12
    elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        offset = 12
        while offset + 8 <= len(content):
            kind = content[offset : offset + 4]
            length = int.from_bytes(content[offset + 4 : offset + 8], "little")
            if offset + length + 8 > len(content):
                break
            if kind in {b"ANIM", b"ANMF"} or (
                kind == b"VP8X" and length >= 1 and content[offset + 8] & 2
            ):
                raise ValueError(
                    "Animated WebP containers are unsupported; select one still frame"
                )
            offset += 8 + length + length % 2


def inspect_image(
    image_path: Path, root: Path = ROOT
) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray]:
    """Return result, observation, reconstruction and pixel residual."""
    metadata = load_frozen_metadata(root)
    path = Path(image_path)
    if not path.is_file():
        raise ValueError(f"Image file does not exist: {path}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Image file exceeds the12MiB limit")
    content = path.read_bytes()
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError("Choose a nonempty image file no larger than12MiB")
    reject_animation_container(content)
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError(
                    "Unsupported image format; choose a still PNG, JPEG or WebP"
                )
            source = preprocess_image(image, metadata["image_size"])
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError(
            "Image cannot be decoded safely; choose a valid still PNG, JPEG or WebP"
        ) from error
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    try:
        session = ort.InferenceSession(
            verified_model_bytes(root, metadata),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        inputs, outputs = session.get_inputs(), session.get_outputs()
        if (
            len(inputs) != 1
            or len(outputs) != 1
            or inputs[0].name != metadata["input_name"]
            or outputs[0].name != metadata["output_name"]
            or inputs[0].type != "tensor(float)"
            or outputs[0].type != "tensor(float)"
            or inputs[0].shape != [1, 3, 256, 256]
            or outputs[0].shape != [1, 3, 256, 256]
        ):
            raise ValueError(
                "ONNX graph does not match the frozen input/output contract"
            )
        started = time.perf_counter()
        output = session.run(
            [metadata["output_name"]], {metadata["input_name"]: source[None]}
        )[0]
        inference_ms = (time.perf_counter() - started) * 1000
    except Exception as error:
        raise ValueError(f"Frozen model inference failed: {error}") from error
    if output.shape != (1, 3, 256, 256) or output.dtype != np.float32:
        raise ValueError("Model returned an invalid reconstruction tensor")
    rebuilt = output[0]
    score, pixel = residual_score(source, rebuilt, metadata["score_top_fraction"])
    anomaly = score > metadata["threshold"]
    result = {
        "filename": path.name,
        "model_version": metadata["model_version"],
        "score": score,
        "threshold": metadata["threshold"],
        "is_anomaly": anomaly,
        "decision": "review" if anomaly else "within_range",
        "score_is_probability": False,
        "inference_ms": inference_ms,
        "input_size": metadata["image_size"],
        "caveat": "Research prototype; a low reconstruction error does not establish defect-free material.",
    }
    return result, source, rebuilt, pixel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument(
        "--bundle",
        type=Path,
        default=ROOT,
        help="Root containing frozen artifacts and calibration reports",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON result file")
    parser.add_argument(
        "--evidence",
        type=Path,
        help="Optional directory for observation, reconstruction and residual PNGs",
    )
    args = parser.parse_args(argv)
    destinations = [args.output] if args.output else []
    if args.evidence:
        destinations.extend(
            args.evidence / name
            for name in (
                "observed.png",
                "reconstruction.png",
                "residual.png",
                "result.json",
            )
        )
    protected = [
        args.bundle.resolve() / directory
        for directory in ("artifacts", "data", "reports")
    ]
    if any(
        path.resolve() == args.image.resolve()
        or any(path.resolve().is_relative_to(base) for base in protected)
        for path in destinations
    ):
        parser.error(
            "Inspection outputs must not overwrite input or frozen bundle artifacts/data/reports"
        )
    try:
        result, source, rebuilt, pixel = inspect_image(args.image, args.bundle)
        text = json.dumps(result, indent=2, allow_nan=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + chr(10))
        if args.evidence:
            args.evidence.mkdir(parents=True, exist_ok=True)
            Image.fromarray(
                np.rint(source.transpose(1, 2, 0) * 255).astype(np.uint8)
            ).save(args.evidence / "observed.png")
            Image.fromarray(
                np.rint(np.clip(rebuilt.transpose(1, 2, 0), 0, 1) * 255).astype(
                    np.uint8
                )
            ).save(args.evidence / "reconstruction.png")
            scale = max(result["threshold"], np.finfo(np.float32).eps)
            Image.fromarray(
                np.rint(np.clip(pixel / scale, 0, 1) * 255).astype(np.uint8)
            ).save(args.evidence / "residual.png")
            (args.evidence / "result.json").write_text(text + chr(10))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
