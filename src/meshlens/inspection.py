"""Offline frozen detector decisions with explicit abstention.

Local digests detect mismatched releases; they are not digital signatures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time
from typing import Literal
import warnings

import numpy as np
from PIL import Image, UnidentifiedImageError

from meshlens.core import MAX_IMAGE_PIXELS, MAX_IMAGE_SIDE, MIN_IMAGE_SIDE
from meshlens.inspection_input import PREPROCESSING_ID, inspection_rgb8

MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_MODEL_BYTES = 128 * 1024 * 1024
_UNSPECIFIED_DIGEST = object()


class InputIssue(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class InspectionResult:
    status: Literal["scored", "inconclusive"]
    reason: str | None
    message: str
    model_version: str | None = None
    model_sha256: str | None = None
    metadata_sha256: str | None = None
    source_sha256: str | None = None
    threshold: float | None = None
    score: float | None = None
    is_anomaly: bool | None = None
    decision: Literal["review", "within_range"] | None = None
    score_is_probability: bool = False
    input_size: int | None = None
    inference_ms: float | None = None
    canonical_input: np.ndarray | None = field(default=None, repr=False, compare=False)
    anomaly_map: np.ndarray | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        return {key: value for key, value in self.__dict__.items() if key not in {"canonical_input", "anomaly_map"}}


def _json_bytes(content: bytes, name: str):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON field in {name}: {key}")
            result[key] = value
        return result

    def reject(value):
        raise ValueError(f"Non-finite JSON number in {name}: {value}")

    return json.loads(content.decode("utf-8-sig"), object_pairs_hook=unique, parse_constant=reject)


def _read(path: Path, limit: int) -> bytes:
    if not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError(f"Missing, empty or oversized file: {path.name}")
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if not content or len(content) > limit:
        raise ValueError(f"Empty or oversized file: {path.name}")
    return content


def _digest(content: bytes, expected=_UNSPECIFIED_DIGEST) -> str:
    actual = hashlib.sha256(content).hexdigest()
    if expected is not _UNSPECIFIED_DIGEST and (not isinstance(expected, str) or actual != expected):
        raise ValueError("Frozen release SHA256 mismatch")
    return actual


def _number(value, name: str, *, positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite nonnegative number")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"Invalid {name}") from error
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(f"Invalid {name}")
    return number


def _reject_animation(content: bytes) -> None:
    """Match historical CLI container guards without importing its ORT dependency."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        offset = 8
        while offset + 12 <= len(content):
            length = int.from_bytes(content[offset:offset + 4], "big")
            kind = content[offset + 4:offset + 8]
            if offset + length + 12 > len(content):
                break
            if kind in {b"acTL", b"fcTL", b"fdAT"}:
                raise InputIssue("animated-image", "Choose one still PNG frame; animation containers are unsupported")
            if kind == b"IEND":
                break
            offset += length + 12
    elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        offset = 12
        while offset + 8 <= len(content):
            kind = content[offset:offset + 4]
            length = int.from_bytes(content[offset + 4:offset + 8], "little")
            if offset + length + 8 > len(content):
                break
            if kind in {b"ANIM", b"ANMF"} or (kind == b"VP8X" and length >= 1 and content[offset + 8] & 2):
                raise InputIssue("animated-image", "Choose one still WebP frame; animation containers are unsupported")
            offset += 8 + length + length % 2


def _geometry(image: Image.Image, size: int) -> None:
    width, height = image.size
    if not MIN_IMAGE_SIDE <= width <= MAX_IMAGE_SIDE or not MIN_IMAGE_SIDE <= height <= MAX_IMAGE_SIDE or width * height > MAX_IMAGE_PIXELS:
        raise InputIssue("image-dimensions", "Image must be 32..4096 pixels per side and at most 16 megapixels")
    if getattr(image, "n_frames", 1) != 1:
        raise InputIssue("animated-image", "Inspection requires one still image")
    if min(width, height) < size:
        raise InputIssue("input-low-resolution", f"Use a close-up at least {size} pixels on its shorter side")
    if max(width, height) / min(width, height) > 1.5:
        raise InputIssue("input-aspect-ratio", "Use a near-square mesh close-up with aspect ratio no greater than 1.5")


class InspectionDetector:
    """Load once and inspect offline; invalid bundles yield inconclusive results.

    inspect(path) checks upload bytes and computes their original SHA256.
    inspect_image(PIL.Image) accepts trusted in-memory images; the caller must
    supply original-byte provenance if required.
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.metadata: dict = {}
        self.metadata_sha256: str | None = None
        self._model = None
        self._session = None
        self._error = None
        try:
            self._load()
        except Exception as error:
            self.metadata = {}
            self._error = str(error)

    @property
    def available(self) -> bool:
        return self._error is None

    def _load(self) -> None:
        directory = self.root / "artifacts/inspection"
        metadata_bytes = _read(directory / "detector.json", 1_000_000)
        metadata = _json_bytes(metadata_bytes, "detector metadata")
        freeze = _json_bytes(_read(self.root / "reports/inspection/frozen_configuration.json", 1_000_000), "frozen configuration")
        if not isinstance(metadata, dict) or not isinstance(freeze, dict):
            raise ValueError("Frozen metadata/configuration must be objects")
        if type(freeze.get("schema_version")) is not int or freeze["schema_version"] != 1:
            raise ValueError("Unsupported frozen configuration version")
        # Current releases pin every source/artifact in one file manifest. Keep
        # compatibility with the earlier explicit digest fields used by tests.
        if "files" in freeze:
            files = freeze["files"]
            if not isinstance(files, dict) or not files:
                raise ValueError("Frozen file manifest must be nonempty")
            model_relative = "artifacts/inspection/" + metadata["export"]["model_file"]
            required = {model_relative, "artifacts/inspection/detector.json", "artifacts/inspection/calibration.json",
                        "reports/inspection/selection.json", "reports/inspection/protocol.json", "data/manifest.csv",
                        "src/meshlens/inspection_input.py", "web/inspection_input.js"}
            if metadata.get("runtime") == "texture-js":
                required |= {"src/meshlens/texture_detector.py", "web/texture_detector.js"}
            if not required.issubset(files):
                raise ValueError("Frozen file manifest omits required release files")
            for relative, record in files.items():
                path = (self.root / relative).resolve()
                if not path.is_relative_to(self.root) or not isinstance(record, dict) or type(record.get("bytes")) is not int or not 0 < record["bytes"] <= MAX_MODEL_BYTES:
                    raise ValueError("Invalid frozen file path/size")
                content = _read(path, MAX_MODEL_BYTES)
                if len(content) != record["bytes"]:
                    raise ValueError("Frozen file byte count mismatch")
                _digest(content, record["sha256"])
            if freeze.get("decision_rule") != "score > threshold" or freeze.get("score_decimals") != 8 or freeze.get("selection_used_test") is not False or freeze.get("calibration") != metadata.get("calibration"):
                raise ValueError("Frozen selection/decision/calibration contract differs")
            freeze = {**freeze, "metadata_sha256": files["artifacts/inspection/detector.json"]["sha256"],
                      "model_bytes": files[model_relative]["bytes"], "preprocessing": metadata["preprocessing"],
                      "calibration_sha256": files["artifacts/inspection/calibration.json"]["sha256"]}
        metadata_sha = _digest(metadata_bytes, freeze["metadata_sha256"])
        if type(metadata.get("schema_version")) is not int or metadata["schema_version"] != 1:
            raise ValueError("Unsupported inspection metadata version")
        version = metadata["model_version"]
        if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", version):
            raise ValueError("Invalid inspection model version")
        runtime, size = metadata["runtime"], metadata["image_size"]
        if runtime not in {"texture-js", "onnx"} or type(size) is not int or not 32 <= size <= 1024:
            raise ValueError("Unsupported inspection runtime/input size")
        if metadata["preprocessing"] != PREPROCESSING_ID or metadata["decision"] != "strict-greater-than" or metadata["score_is_probability"] is not False:
            raise ValueError("Unsupported inspection preprocessing/decision contract")
        quality = metadata["input_quality"]
        if not isinstance(quality, dict) or type(quality.get("min_side")) is not int or quality["min_side"] != size or quality.get("max_aspect_ratio") != 1.5:
            raise ValueError("Unsupported inspection input-quality contract")
        threshold = _number(metadata["threshold"], "threshold")
        output = metadata["outputs"]
        if not isinstance(output, dict) or output.get("score_name") != "score" or output.get("map_name") != "anomaly_map" or type(output.get("map_size")) is not int or not 1 <= output["map_size"] <= size:
            raise ValueError("Invalid inspection output contract")
        exported = metadata["export"]
        expected_name = "detector-model.json" if runtime == "texture-js" else "detector.onnx"
        if exported["model_file"] != expected_name or type(exported["model_bytes"]) is not int or not 0 < exported["model_bytes"] <= MAX_MODEL_BYTES:
            raise ValueError("Invalid frozen detector model path/size")
        model_bytes = _read(directory / expected_name, MAX_MODEL_BYTES)
        model_sha = _digest(model_bytes, exported["model_sha256"])
        if len(model_bytes) != exported["model_bytes"]:
            raise ValueError("Frozen model size mismatch")
        for key, expected in {"model_version": version, "model_sha256": model_sha, "model_bytes": len(model_bytes), "threshold": threshold, "preprocessing": PREPROCESSING_ID}.items():
            if freeze.get(key) != expected:
                raise ValueError(f"Frozen configuration differs in {key}")
        _number(freeze.get("threshold"), "frozen threshold")
        if type(freeze.get("model_bytes")) is not int:
            raise ValueError("Invalid frozen model byte count")
        calibration_bytes = _read(directory / "calibration.json", 4_000_000)
        calibration_sha = _digest(calibration_bytes, metadata["calibration"]["scores_sha256"])
        if freeze.get("calibration_sha256") != calibration_sha:
            raise ValueError("Frozen calibration digest differs")
        calibration = metadata["calibration"]
        if calibration.get("count") != 52 or type(calibration.get("count")) is not int or calibration.get("alpha") != 0.05 or calibration.get("order_statistic_rank") != 51 or type(calibration.get("order_statistic_rank")) is not int:
            raise ValueError("Unexpected normal calibration count/rank/alpha")
        rows = _json_bytes(calibration_bytes, "normal calibration")
        if not isinstance(rows, list) or len(rows) != 52 or any(not isinstance(row, dict) for row in rows):
            raise ValueError("Expected 52 distinct normal calibration records")
        paths, digests, scores = set(), set(), []
        for row in rows:
            path, digest = row.get("path"), row.get("sha256")
            if not isinstance(path, str) or not path or path in paths or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or digest in digests:
                raise ValueError("Invalid/duplicate normal calibration provenance")
            if row.get("label", 0) != 0 or row.get("split", "calibration") != "calibration":
                raise ValueError("Calibration must contain only normal calibration images")
            paths.add(path)
            digests.add(digest)
            scores.append(_number(row.get("score"), "normal calibration score"))
        if sorted(scores)[50] != threshold:
            raise ValueError("Threshold does not match the frozen normal order statistic")
        for relative, expected in freeze.get("source_code", {}).items():
            source = (self.root / relative).resolve()
            if not source.is_relative_to(self.root):
                raise ValueError("Frozen source path escapes bundle")
            _digest(_read(source, 4_000_000), expected)
        if runtime == "texture-js":
            from meshlens.texture_detector import IMAGE_SIZE, MODEL_KIND, SCORE_DECIMALS, VARIANTS

            model = _json_bytes(model_bytes, "texture model")
            if not isinstance(model, dict) or model.get("kind") != MODEL_KIND or size != IMAGE_SIZE or model.get("image_size") != size or model.get("preprocessing") != PREPROCESSING_ID or model.get("threshold") != threshold or model.get("variant") not in VARIANTS or model.get("score_decimals", SCORE_DECIMALS) != SCORE_DECIMALS or output["map_size"] != size:
                raise ValueError("Texture model differs from its frozen contract")
            _number(model.get("threshold"), "texture threshold")
            _number(model.get("fit_scale"), "texture fit scale", positive=True)
            if not 0 < _number(model.get("tail_fraction"), "texture tail fraction") <= 1:
                raise ValueError("Invalid texture tail fraction")
            self._model = model
        else:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
            session = ort.InferenceSession(model_bytes, sess_options=options, providers=["CPUExecutionProvider"])
            inputs, outputs = session.get_inputs(), {item.name: item for item in session.get_outputs()}
            if len(inputs) != 1 or inputs[0].name != "image" or inputs[0].type != "tensor(float)" or inputs[0].shape != [1, 3, size, size] or set(outputs) != {"score", "anomaly_map"}:
                raise ValueError("ONNX input/output contract differs")
            if outputs["score"].type != "tensor(float)" or outputs["score"].shape != [1] or outputs["anomaly_map"].type != "tensor(float)" or outputs["anomaly_map"].shape != [1, 1, output["map_size"], output["map_size"]]:
                raise ValueError("ONNX score/map contract differs")
            self._session = session
        self.metadata, self.metadata_sha256 = metadata, metadata_sha

    def _result(self, source_sha256=None, **values) -> InspectionResult:
        return InspectionResult(model_version=self.metadata.get("model_version"), model_sha256=self.metadata.get("export", {}).get("model_sha256"),
                                metadata_sha256=self.metadata_sha256, source_sha256=source_sha256,
                                threshold=self.metadata.get("threshold"), input_size=self.metadata.get("image_size"), **values)

    def inspect(self, path: Path) -> InspectionResult:
        source_sha = None
        try:
            path = Path(path)
            if not path.is_file():
                raise InputIssue("input-missing", "Image file does not exist")
            if not 0 < path.stat().st_size <= MAX_FILE_BYTES:
                raise InputIssue("input-file-size", "Choose a nonempty image no larger than 12 MiB")
            with path.open("rb") as stream:
                content = stream.read(MAX_FILE_BYTES + 1)
            if not content or len(content) > MAX_FILE_BYTES:
                raise InputIssue("input-file-size", "Choose a nonempty image no larger than 12 MiB")
            source_sha = _digest(content)
            _reject_animation(content)
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    if image.format not in {"PNG", "JPEG", "WEBP"}:
                        raise InputIssue("unsupported-format", "Choose a still PNG, JPEG or WebP image")
                    # Pillow parses headers lazily: check geometry before decode.
                    _geometry(image, self.metadata.get("image_size", MIN_IMAGE_SIDE))
                    return self.inspect_image(image, source_sha256=source_sha)
        except InputIssue as error:
            return self._result(source_sha, status="inconclusive", reason=error.code, message=str(error))
        except (OSError, TypeError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            return self._result(source_sha, status="inconclusive", reason="invalid-image", message=f"Image cannot be decoded safely: {error}")

    def inspect_image(self, image: Image.Image, *, source_sha256: str | None = None) -> InspectionResult:
        if not self.available:
            return self._result(source_sha256, status="inconclusive", reason="model-unavailable", message=f"Frozen detector unavailable: {self._error}")
        source = None
        try:
            if source_sha256 is not None and (not isinstance(source_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", source_sha256)):
                raise InputIssue("invalid-provenance", "source_sha256 must identify original image bytes")
            if not isinstance(image, Image.Image):
                raise InputIssue("invalid-image", "Expected a decoded Pillow image")
            _geometry(image, self.metadata["image_size"])
            source = inspection_rgb8(image, self.metadata["image_size"])
            tensor = np.ascontiguousarray(source.transpose(2, 0, 1), dtype=np.float32) / np.float32(255)
            started = time.perf_counter()
            if self.metadata["runtime"] == "texture-js":
                from meshlens.texture_detector import score_texture

                score, anomaly, _ = score_texture(tensor, self._model)
            else:
                values, maps = self._session.run(["score", "anomaly_map"], {"image": tensor[None]})
                if values.shape != (1,) or values.dtype != np.float32 or maps.shape != (1, 1, self.metadata["outputs"]["map_size"], self.metadata["outputs"]["map_size"]) or maps.dtype != np.float32:
                    raise ValueError("Detector returned an invalid score/map tensor")
                score, anomaly = float(values[0]), maps[0, 0]
            elapsed = (time.perf_counter() - started) * 1000
            score = _number(score, "detector score")
            anomaly = np.asarray(anomaly)
            map_size = self.metadata["outputs"]["map_size"]
            if anomaly.shape != (map_size, map_size) or not np.isfinite(anomaly).all() or np.any(anomaly < 0):
                raise ValueError("Detector returned a non-finite, negative or incorrectly shaped anomaly map")
            flagged = score > self.metadata["threshold"]
            return self._result(source_sha256, status="scored", reason=None,
                                message="Review the highlighted differences." if flagged else "Within the learned score range; this does not establish defect-free material.",
                                score=score, is_anomaly=flagged, decision="review" if flagged else "within_range", inference_ms=elapsed,
                                canonical_input=source, anomaly_map=anomaly)
        except Exception as error:
            return self._result(source_sha256, status="inconclusive", reason=getattr(error, "code", "inference-failed"), message=str(error), canonical_input=source)
