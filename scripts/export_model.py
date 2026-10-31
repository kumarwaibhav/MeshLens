#!/usr/bin/env python3
"""Export the frozen network and prove ONNX parity without changing its scores."""

from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import onnx
import onnxruntime as ort
from PIL import Image
import torch
from meshlens.core import preprocess_image, read_manifest, residual_score
from meshlens.model import load_checkpoint
from meshlens.artifacts import load_frozen_metadata

ROOT = Path(__file__).resolve().parents[1]


def export_model() -> None:
    torch.set_num_threads(4)
    artifacts = ROOT / "artifacts"
    metadata = load_frozen_metadata(ROOT, verify_model=False)
    freeze = json.loads((ROOT / "reports/frozen_configuration.json").read_text())
    model, _ = load_checkpoint(
        artifacts / "checkpoint.pt", expected_sha256=freeze["checkpoint_sha256"]
    )
    exported = artifacts / "model.onnx.tmp"
    dummy = torch.zeros((1, 3, 256, 256), dtype=torch.float32)
    torch.onnx.export(
        model,
        dummy,
        str(exported),
        input_names=["image"],
        output_names=["reconstruction"],
        opset_version=17,
        dynamo=False,
        external_data=False,
    )
    graph = onnx.load(str(exported))
    # The legacy exporter leaves Slice output dimensions symbolic even with a
    # fixed input. Publish the exact single-image browser contract explicitly.
    for dimension, value in zip(
        graph.graph.output[0].type.tensor_type.shape.dim, (1, 3, 256, 256)
    ):
        dimension.ClearField("dim_param")
        dimension.dim_value = value
    onnx.checker.check_model(graph)
    onnx.save(graph, str(exported))
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(exported), sess_options=options, providers=["CPUExecutionProvider"]
    )
    rows = [row for row in read_manifest(ROOT) if row["split"] == "test"]
    max_tensor_error = max_score_error = 0.0
    disagreements = 0
    for row in rows:
        with Image.open(ROOT / row["path"]) as image:
            source = preprocess_image(image)
        with torch.inference_mode():
            native = model(torch.from_numpy(source[None])).numpy()[0]
        portable = session.run(["reconstruction"], {"image": source[None]})[0][0]
        max_tensor_error = max(
            max_tensor_error, float(np.max(np.abs(native - portable)))
        )
        score_native = residual_score(source, native, metadata["top_fraction"])[0]
        score_portable = residual_score(source, portable, metadata["top_fraction"])[0]
        max_score_error = max(max_score_error, abs(score_native - score_portable))
        disagreements += int(
            (score_native > metadata["threshold"])
            != (score_portable > metadata["threshold"])
        )
    if max_tensor_error > 1e-5 or max_score_error > 1e-6 or disagreements:
        raise SystemExit(
            f"ONNX parity failed: tensor={max_tensor_error}; score={max_score_error}; decisions={disagreements}"
        )
    probe = (np.arange(3 * 256 * 256, dtype=np.float32) % np.float32(257)) / np.float32(
        256
    )
    output = session.run(["reconstruction"], {"image": probe.reshape(1, 3, 256, 256)})[
        0
    ]
    flat = output.reshape(-1)
    indices = [0, 1, 17, 255, 256, 4096, 16384, 65535, 65536, 81920, 131072, 196607]
    probe_score = residual_score(
        probe.reshape(3, 256, 256), output[0], metadata["top_fraction"]
    )[0]
    validation = {
        "schema_version": 1,
        "input_name": "image",
        "output_name": "reconstruction",
        "shape": [1, 3, 256, 256],
        "formula": "Float32Array[i] = (i % 257) / 256",
        "output_indices": indices,
        "expected_output": [float(flat[i]) for i in indices],
        "expected_score": probe_score,
        "absolute_tolerance": 1e-5,
        "score_tolerance": 1e-6,
        "top_fraction": metadata["top_fraction"],
        "source": "Deterministic synthetic arithmetic probe; not an accuracy example",
    }
    (artifacts / "browser-validation.json").write_text(
        json.dumps(validation, indent=2) + "\n"
    )
    times = []
    for _ in range(23):
        start = time.perf_counter()
        session.run(["reconstruction"], {"image": probe.reshape(1, 3, 256, 256)})
        times.append((time.perf_counter() - start) * 1000)
    parity = {
        "export": "PyTorch legacy ONNX exporter; browser-compatible opset17",
        "onnx_version": onnx.__version__,
        "onnxruntime_version": ort.__version__,
        "opset": 17,
        "ir_version": graph.ir_version,
        "model_bytes": exported.stat().st_size,
        "model_sha256": hashlib.sha256(exported.read_bytes()).hexdigest(),
        "test_images_checked": len(rows),
        "max_tensor_absolute_difference": max_tensor_error,
        "max_score_absolute_difference": max_score_error,
        "decision_disagreements": disagreements,
        "native_ort_warm_latency_ms": {
            "median": float(np.median(times[3:])),
            "p95": float(np.quantile(times[3:], 0.95)),
            "threads": 2,
        },
        "browser_verification": "Native ORT parity here; actual browser WASM verification is a separate required check.",
    }
    exported.replace(artifacts / "model.onnx")
    (ROOT / "reports/onnx_parity.json").write_text(json.dumps(parity, indent=2) + "\n")
    metadata["export"] = parity
    metadata["model_path"] = "model.onnx"
    (artifacts / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(parity, indent=2), flush=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        export_model()
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
