"""Fit and export a normal-only patch memory for MeshLens.

This script builds an ONNX feature extractor from a pinned ResNet-18 checkpoint.
It selects a representation on the tune-only development suite and calibrates
the exported detector on the independent clean calibration split.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path, PurePosixPath
from time import perf_counter

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper
import onnxruntime as ort
from PIL import Image
from safetensors.numpy import load_file
from sklearn.metrics import roc_auc_score
from threadpoolctl import threadpool_limits

from meshlens.inspection_input import inspection_rgb8


IMAGE_SIZE = 384
GRID_SIZE = IMAGE_SIZE // 8
SEED = 20261109
ALPHA = 0.05
WEIGHTS_REVISION = "491b427b45c94c7fb0e78b5474cc919aff584bbf"
WEIGHTS_SHA256 = "80c49dee3da4822c009c5a7fe591e9223c5a2cfcf95a4067ca4dfb5a7b89c612"
WEIGHTS_URL = (
    f"https://huggingface.co/timm/resnet18.a1_in1k/resolve/{WEIGHTS_REVISION}/model.safetensors"
)
WEIGHTS_LICENSE = "Apache-2.0"
FEATURE_CHANNELS = (64, 128, 256)
SYNTHETIC_KINDS = frozenset({"bend", "gap", "fibre", "glue", "contamination"})


@dataclass(frozen=True)
class FeatureChoice:
    name: str
    stages: tuple[int, ...]
    dimensions: int
    bank_size: int = 1536


FEATURE_CHOICES = (
    FeatureChoice("local", (1, 2), 48),
    FeatureChoice("context", (2, 3), 48),
    FeatureChoice("combined", (1, 2, 3), 64),
)
TOP_FRACTIONS = (0.005, 0.015)


class Graph:
    def __init__(self, weights: dict[str, np.ndarray]):
        self.weights = weights
        self.nodes: list[onnx.NodeProto] = []
        self.initializers: list[onnx.TensorProto] = []

    def constant(self, name: str, value: np.ndarray) -> str:
        self.initializers.append(numpy_helper.from_array(np.asarray(value), name=name))
        return name

    def op(self, kind: str, name: str, *inputs: str, **attributes) -> str:
        self.nodes.append(helper.make_node(kind, list(inputs), [name], name=name, **attributes))
        return name

    def convolution(
        self,
        value: str,
        weight_name: str,
        batch_norm: str,
        stride: int,
        padding: int,
    ) -> str:
        weight = self.weights[f"{weight_name}.weight"]
        bn_variance = self.weights[f"{batch_norm}.running_var"]
        factor = self.weights[f"{batch_norm}.weight"] / np.sqrt(bn_variance + np.float32(1e-5))
        bias = (
            self.weights[f"{batch_norm}.bias"]
            - self.weights[f"{batch_norm}.running_mean"] * factor
        )
        folded = weight * factor[:, None, None, None]
        return self.op(
            "Conv",
            weight_name,
            value,
            self.constant(f"{weight_name}.weight", folded),
            self.constant(f"{weight_name}.bias", bias),
            strides=[stride, stride],
            pads=[padding] * 4,
        )

    def block(self, value: str, name: str, stride: int) -> str:
        residual = self.convolution(value, f"{name}.conv1", f"{name}.bn1", stride, 1)
        residual = self.op("Relu", f"{name}.activation", residual)
        residual = self.convolution(residual, f"{name}.conv2", f"{name}.bn2", 1, 1)
        identity = value
        if stride != 1:
            identity = self.convolution(value, f"{name}.downsample.0", f"{name}.downsample.1", stride, 0)
        summed = self.op("Add", f"{name}.sum", residual, identity)
        return self.op("Relu", f"{name}.output", summed)

    def features(self, stages: tuple[int, ...]) -> str:
        mean = self.op("ReduceMean", "input.mean", "image", axes=[2, 3], keepdims=1)
        centered = self.op("Sub", "input.centered", "image", mean)
        squared = self.op("Mul", "input.squared", centered, centered)
        variance = self.op("ReduceMean", "input.variance", squared, axes=[2, 3], keepdims=1)
        floored = self.op(
            "Max", "input.bounded_variance", variance,
            self.constant("input.variance_floor", np.float32(0.0004)),
        )
        scale = self.op("Sqrt", "input.scale", floored)
        contrast = self.op("Div", "input.contrast", centered, scale)
        clipped = self.op(
            "Clip", "input.clipped", contrast,
            self.constant("input.clip_low", np.float32(-3.0)),
            self.constant("input.clip_high", np.float32(3.0)),
        )
        scaled = self.op(
            "Mul", "input.scaled", clipped,
            self.constant("input.contrast_factor", np.float32(0.2)),
        )
        imagenet_mean = np.asarray([0.485, 0.456, 0.406], dtype=np.float32).reshape(1, 3, 1, 1)
        imagenet_std = np.asarray([0.229, 0.224, 0.225], dtype=np.float32).reshape(1, 3, 1, 1)
        shifted = self.op(
            "Add", "input.shifted", scaled,
            self.constant("input.mean_shift", np.float32(0.45) - imagenet_mean),
        )
        normalized = self.op(
            "Div", "input.normalized", shifted, self.constant("input.imagenet_std", imagenet_std),
        )
        stem = self.convolution(normalized, "conv1", "bn1", 2, 3)
        stem = self.op("Relu", "stem.relu", stem)
        value = self.op(
            "MaxPool", "stem.pool", stem, kernel_shape=[3, 3], strides=[2, 2], pads=[1] * 4,
        )
        aligned: list[str] = []
        for stage in range(1, max(stages) + 1):
            value = self.block(value, f"layer{stage}.0", 1 if stage == 1 else 2)
            value = self.block(value, f"layer{stage}.1", 1)
            if stage not in stages:
                continue
            patch = self.op(
                "AveragePool", f"layer{stage}.patch", value,
                kernel_shape=[3, 3], strides=[1, 1], pads=[1] * 4, count_include_pad=0,
            )
            if stage == 1:
                patch = self.op(
                    "AveragePool", "layer1.aligned", patch, kernel_shape=[2, 2], strides=[2, 2],
                )
            if stage == 3:
                patch = self.op(
                    "Resize", "layer3.aligned", patch,
                    self.constant("layer3.roi", np.empty(0, dtype=np.float32)),
                    self.constant("layer3.scale", np.asarray([1, 1, 2, 2], dtype=np.float32)),
                    mode="linear", coordinate_transformation_mode="half_pixel",
                )
            aligned.append(patch)
        merged = self.op("Concat", "feature_map", *aligned, axis=1)
        transposed = self.op("Transpose", "feature_hwc", merged, perm=[0, 2, 3, 1])
        return self.op("Flatten", "patch_features", transposed, axis=3)

    def score_graph(
        self, features: str, basis: np.ndarray, bias: np.ndarray, bank: np.ndarray, fraction: float,
    ) -> None:
        projection = self.op(
            "MatMul", "projection.linear", features, self.constant("projection.basis", basis),
        )
        embedding = self.op(
            "Add", "projection.embedding", projection, self.constant("projection.bias", bias),
        )
        product = self.op(
            "MatMul", "memory.dot_product", embedding, self.constant("memory.bank", bank.T.copy()),
        )
        cross = self.op(
            "Mul", "memory.cross_term", product, self.constant("memory.neg_two", np.float32(-2.0)),
        )
        squared = self.op("Mul", "memory.embedding_squared", embedding, embedding)
        norm = self.op(
            "ReduceSum", "memory.embedding_norm", squared,
            self.constant("memory.channel_axis", np.asarray([1], dtype=np.int64)), keepdims=1,
        )
        offset = self.op("Add", "memory.offset", cross, norm)
        distances = self.op(
            "Add", "memory.distances_squared", offset,
            self.constant("memory.bank_norm", np.sum(bank * bank, axis=1, dtype=np.float32)),
        )
        nearest = self.op("ReduceMin", "memory.nearest", distances, axes=[1], keepdims=0)
        nonnegative = self.op(
            "Max", "memory.nonnegative", nearest, self.constant("memory.zero", np.float32(0.0)),
        )
        distance = self.op("Sqrt", "patch_distance", nonnegative)
        self.op(
            "Reshape", "anomaly_map", distance,
            self.constant("map.shape", np.asarray([1, 1, GRID_SIZE, GRID_SIZE], dtype=np.int64)),
        )
        tail = math.ceil(GRID_SIZE * GRID_SIZE * fraction)
        self.nodes.append(helper.make_node(
            "TopK", [distance, self.constant("score.top_k", np.asarray([tail], dtype=np.int64))],
            ["top_patch_distances", "top_patch_indices"], axis=0, largest=1, sorted=0,
        ))
        self.op("ReduceMean", "score", "top_patch_distances", axes=[0], keepdims=1)

    def save(self, name: str, destination: Path, outputs: list[onnx.ValueInfoProto]) -> None:
        inputs = [helper.make_tensor_value_info("image", TensorProto.FLOAT, [1, 3, IMAGE_SIZE, IMAGE_SIZE])]
        graph = helper.make_graph(self.nodes, name, inputs, outputs, self.initializers)
        model = helper.make_model(
            graph, producer_name="MeshLens", opset_imports=[helper.make_opsetid("", 13)], ir_version=10,
        )
        helper.set_model_props(model, {
            "upstream_checkpoint": WEIGHTS_URL,
            "upstream_sha256": WEIGHTS_SHA256,
            "upstream_license": WEIGHTS_LICENSE,
        })
        onnx.checker.check_model(model)
        temporary = destination.with_suffix(".onnx.tmp")
        onnx.save(model, temporary)
        temporary.replace(destination)


def read_partition(root: Path, split: str) -> list[dict[str, str]]:
    expected_counts = {"fit": 160, "tune": 52, "calibration": 52}
    if split not in expected_counts:
        raise ValueError("Only fit, tune and clean calibration partitions are available to training")
    with (root / "data/manifest.csv").open(newline="", encoding="utf-8") as stream:
        rows = []
        for row in csv.DictReader(stream):
            if row["split"] != split:
                continue
            if (
                row["label"] != "0" or row["defect_type"] != "good"
                or row["mask_path"] or not row["path"].startswith("data/raw/grid/train/good/")
            ):
                raise ValueError(f"Expected clean training data for {split}")
            rows.append(row)
    if len(rows) != expected_counts[split] or len({r["sha256"] for r in rows}) != len(rows):
        raise ValueError(f"Unexpected or duplicate {split} entries")
    return rows


def read_tune_suite(root: Path, manifest: Path) -> list[dict[str, str]]:
    sources = {r["path"]: r["sha256"] for r in read_partition(root, "tune")}
    with manifest.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    expected = {(name, kind) for name in sources for kind in SYNTHETIC_KINDS | {"clean"}}
    seen = set()
    for row in rows:
        key = row["source_path"], row["defect_type"]
        clean = row["defect_type"] == "clean"
        if (
            key not in expected or key in seen or row["source_split"] != "tune"
            or row["source_sha256"] != sources[row["source_path"]]
            or row["label"] != ("0" if clean else "1")
            or (row["sha256"] == row["source_sha256"]) != clean
        ):
            raise ValueError("Development suite contains a malformed or out-of-partition image")
        seen.add(key)
    if seen != expected or len({row["sample_id"] for row in rows}) != len(rows):
        raise ValueError("Development suite has missing or repeated source and defect combinations")
    return rows


def load_image(root: Path, row: dict[str, str]) -> np.ndarray:
    relative = PurePosixPath(row["path"])
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".png":
        raise ValueError("Expected a relative PNG path within the declared partition")
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Dataset entry escaped its root")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != row["sha256"]:
        raise ValueError(f"Image hash mismatch for {row['path']}")
    with Image.open(BytesIO(raw)) as image:
        pixels = inspection_rgb8(image, IMAGE_SIZE)
    return np.ascontiguousarray(pixels.transpose(2, 0, 1)[None], dtype=np.float32) / np.float32(255)


def session(path: Path, threads: int) -> ort.InferenceSession:
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    return ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])


def features_for_choice(features: np.ndarray, choice: FeatureChoice) -> np.ndarray:
    if choice.stages == (1, 2):
        return features[:, :192]
    if choice.stages == (2, 3):
        return features[:, 64:]
    return features


def fit_memory(
    features: np.ndarray, choice: FeatureChoice, rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    matrix = np.ascontiguousarray(features_for_choice(features, choice), dtype=np.float32)
    mean = matrix.mean(axis=0, dtype=np.float64).astype(np.float32)
    scale = np.maximum(matrix.std(axis=0, dtype=np.float64).astype(np.float32), np.float32(0.05))
    centered = (matrix - mean) / scale
    covariance = (centered.T @ centered) / np.float32(len(centered) - 1)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    chosen = eigenvectors[:, -choice.dimensions:].copy()
    # A fixed sign convention prevents arbitrary eigenvector flips in export.
    dominant = np.argmax(np.abs(chosen), axis=0)
    chosen *= np.where(chosen[dominant, np.arange(choice.dimensions)] < 0, -1, 1)
    shrink = np.maximum(eigenvalues[-choice.dimensions:], np.float32(0)) + np.float32(0.1)
    basis = np.ascontiguousarray((chosen * shrink ** np.float32(-0.25)) / scale[:, None], dtype=np.float32)
    bias = np.asarray(-(mean @ basis), dtype=np.float32)
    candidates = rng.choice(len(matrix), size=min(8192, len(matrix)), replace=False)
    pool = np.ascontiguousarray(matrix[candidates] @ basis + bias, dtype=np.float32)
    selected = np.empty(choice.bank_size, dtype=np.int64)
    nearest = np.full(len(pool), np.inf, dtype=np.float32)
    next_index = int(np.argmin(np.sum(pool * pool, axis=1)))
    for slot in range(choice.bank_size):
        selected[slot] = next_index
        difference = pool - pool[next_index]
        nearest = np.minimum(nearest, np.sum(difference * difference, axis=1, dtype=np.float32))
        nearest[selected[:slot + 1]] = -1
        next_index = int(np.argmax(nearest))
    return basis, bias, pool[selected].copy()


def nearest_map(
    features: np.ndarray, memory: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> np.ndarray:
    basis, bias, bank = memory
    embedding = features @ basis + bias
    distances = embedding @ bank.T
    distances *= np.float32(-2)
    distances += np.sum(embedding * embedding, axis=1, dtype=np.float32)[:, None]
    distances += np.sum(bank * bank, axis=1, dtype=np.float32)[None]
    return np.sqrt(np.maximum(np.min(distances, axis=1), np.float32(0)))


def upper_clean_limit(scores: np.ndarray) -> tuple[int, float]:
    if scores.shape != (52,) or not np.isfinite(scores).all():
        raise ValueError("Expected exactly 52 finite clean scores")
    rank = math.ceil((len(scores) + 1) * (1 - ALPHA))
    return rank, float(np.sort(scores)[rank - 1])


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def fit(root: Path, output: Path, weights: dict[str, np.ndarray], threads: int) -> None:
    start = perf_counter()
    encoder_path = output / "feature_encoder.onnx"
    graph = Graph(weights)
    graph.features((1, 2, 3))
    graph.save("meshlens-fit-encoder", encoder_path, [
        helper.make_tensor_value_info("patch_features", TensorProto.FLOAT, [GRID_SIZE ** 2, sum(FEATURE_CHANNELS)]),
    ])
    runtime = session(encoder_path, threads)
    rng = np.random.default_rng(SEED)
    rows = read_partition(root, "fit")
    patches = []
    for index, row in enumerate(rows, 1):
        feature_map = runtime.run(["patch_features"], {"image": load_image(root, row)})[0]
        indices = rng.choice(len(feature_map), 256, replace=False)
        patches.append(feature_map[indices])
        if index % 40 == 0:
            print(f"Encoded {index} of {len(rows)} fit images", flush=True)
    matrix = np.concatenate(patches, axis=0)
    memory_hashes = {}
    for choice in FEATURE_CHOICES:
        basis, bias, bank = fit_memory(matrix, choice, np.random.default_rng(SEED))
        bank_path = output / f"{choice.name}.npz"
        np.savez(bank_path, basis=basis, bias=bias, bank=bank)
        memory_hashes[choice.name] = sha256(bank_path.read_bytes()).hexdigest()
        print(f"Fit {choice.name} clean patch memory with {len(bank)} anchors", flush=True)
    write_json(output / "fit.json", {
        "clean_fit_images": len(rows),
        "fit_images_sha256": sha256("\n".join(row["sha256"] for row in rows).encode()).hexdigest(),
        "fit_seconds": perf_counter() - start,
        "encoder_sha256": sha256(encoder_path.read_bytes()).hexdigest(),
        "memory_sha256": memory_hashes,
        "seed": SEED,
        "checkpoint": {"url": WEIGHTS_URL, "sha256": WEIGHTS_SHA256, "license": WEIGHTS_LICENSE},
        "image_size": IMAGE_SIZE,
    })


def select(root: Path, output: Path, suite: Path, weights: dict[str, np.ndarray], threads: int) -> None:
    start = perf_counter()
    rows = read_tune_suite(root, suite)
    fit_report = json.loads((output / "fit.json").read_text(encoding="utf-8"))
    encoder = output / "feature_encoder.onnx"
    fit_digest = sha256("\n".join(row["sha256"] for row in read_partition(root, "fit")).encode()).hexdigest()
    if (
        fit_digest != fit_report["fit_images_sha256"]
        or sha256(encoder.read_bytes()).hexdigest() != fit_report["encoder_sha256"]
    ):
        raise ValueError("Fit inputs or encoder changed before development selection")
    runtime = session(encoder, threads)
    memories = {}
    for choice in FEATURE_CHOICES:
        bank_path = output / f"{choice.name}.npz"
        if sha256(bank_path.read_bytes()).hexdigest() != fit_report["memory_sha256"][choice.name]:
            raise ValueError("Fit patch memory changed before development selection")
        with np.load(bank_path, allow_pickle=False) as archive:
            memories[choice.name] = (archive["basis"], archive["bias"], archive["bank"])
    values = {(c.name, f): [] for c in FEATURE_CHOICES for f in TOP_FRACTIONS}
    memory_timings = {c.name: [] for c in FEATURE_CHOICES}
    for index, row in enumerate(rows, 1):
        features = runtime.run(["patch_features"], {"image": load_image(suite.parent, row)})[0]
        for choice in FEATURE_CHOICES:
            before = perf_counter()
            distance = nearest_map(features_for_choice(features, choice), memories[choice.name])
            memory_timings[choice.name].append(1000 * (perf_counter() - before))
            for fraction in TOP_FRACTIONS:
                count = math.ceil(len(distance) * fraction)
                values[choice.name, fraction].append(float(np.partition(distance, -count)[-count:].mean()))
        if index % 52 == 0:
            print(f"Scored {index} of {len(rows)} tune-only examples", flush=True)
    labels = np.asarray([int(row["label"]) for row in rows])
    kinds = np.asarray([row["defect_type"] for row in rows])
    reports = []
    for (name, fraction), measurements in values.items():
        scores = np.asarray(measurements, dtype=np.float32)
        clean = scores[labels == 0]
        limit = float(np.sort(clean)[len(clean) - 3])
        by_kind = {kind: float(np.mean(scores[kinds == kind] > limit)) for kind in sorted(SYNTHETIC_KINDS)}
        reports.append({
            "representation": name, "top_fraction": fraction, "clean_reference_cutoff": limit,
            "tune_clean_alerts": int(np.sum(clean > limit)),
            "macro_synthetic_recall": float(np.mean(list(by_kind.values()))),
            "synthetic_auroc": float(roc_auc_score(labels, scores)), "recall_by_synthetic_kind": by_kind,
            "median_memory_score_ms": float(np.median(memory_timings[name])),
        })
    with (output / "development_scores.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["representation", "top_fraction", "sample_id", "source_path", "label", "defect_type", "score"])
        for (name, fraction), measurements in values.items():
            for row, score in zip(rows, measurements, strict=True):
                writer.writerow([name, fraction, row["sample_id"], row["source_path"], row["label"], row["defect_type"], score])
    winner = max(reports, key=lambda row: (
        row["macro_synthetic_recall"],
        -max(next(c.stages for c in FEATURE_CHOICES if c.name == row["representation"])),
        row["synthetic_auroc"],
    ))
    choice = next(c for c in FEATURE_CHOICES if c.name == winner["representation"])
    graph = Graph(weights)
    feature_map = graph.features(choice.stages)
    graph.score_graph(feature_map, *memories[choice.name], winner["top_fraction"])
    model_path = output / "candidate.onnx"
    graph.save("meshlens-patch-memory", model_path, [
        helper.make_tensor_value_info("score", TensorProto.FLOAT, [1]),
        helper.make_tensor_value_info("anomaly_map", TensorProto.FLOAT, [1, 1, GRID_SIZE, GRID_SIZE]),
    ])
    model = session(model_path, threads)
    differences, timings = [], []
    for index in range(0, len(rows), max(1, len(rows) // 16)):
        pixels = load_image(suite.parent, rows[index])
        before = perf_counter()
        score = model.run(["score"], {"image": pixels})[0].item()
        timings.append(1000 * (perf_counter() - before))
        differences.append(abs(score - values[choice.name, winner["top_fraction"]][index]))
    if max(differences) > 2e-4:
        raise ValueError(f"ONNX score drifted from development implementation: {max(differences)}")
    write_json(output / "selection.json", {
        "selected": winner,
        "configuration": asdict(choice),
        "development_results": reports,
        "development_manifest_sha256": sha256(suite.read_bytes()).hexdigest(),
        "selection_rule": (
            "Highest macro synthetic recall with at most 2/52 tune clean alerts, "
            "then shallower backbone, then AUROC"
        ),
        "model_sha256": sha256(model_path.read_bytes()).hexdigest(),
        "model_bytes": model_path.stat().st_size,
        "dev_onnx_parity_max_abs_error": max(differences),
        "dev_onnx_inference_median_ms": float(np.median(timings)),
        "selection_seconds": perf_counter() - start,
    })
    print(json.dumps(winner, indent=2), flush=True)


def calibrate(root: Path, output: Path, threads: int) -> None:
    selected = json.loads((output / "selection.json").read_text(encoding="utf-8"))
    model_path = output / "candidate.onnx"
    if sha256(model_path.read_bytes()).hexdigest() != selected["model_sha256"]:
        raise ValueError("The selected ONNX graph changed before calibration")
    runtime = session(model_path, threads)
    rows = read_partition(root, "calibration")
    results = []
    for row in rows:
        score = runtime.run(["score"], {"image": load_image(root, row)})[0].item()
        results.append({"path": row["path"], "image_sha256": row["sha256"], "score": score})
    rank, threshold = upper_clean_limit(np.asarray([r["score"] for r in results], dtype=np.float32))
    write_json(output / "calibration.json", {
        "model_sha256": selected["model_sha256"],
        "alpha": ALPHA,
        "calibration_count": len(results),
        "threshold_rank": rank,
        "threshold": threshold,
        "strict_comparison": "score > threshold",
        "scores": results,
    })
    print(f"Frozen cutoff {threshold:.9g} from clean calibration rank {rank}/{len(results)}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["fit", "select", "calibrate"])
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--suite", type=Path)
    parser.add_argument("--threads", type=int, choices=[1, 2, 3], default=3)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with threadpool_limits(limits=args.threads):
        if args.phase == "calibrate":
            calibrate(args.project_root, args.output, args.threads)
            return
        if args.weights is None or sha256(args.weights.read_bytes()).hexdigest() != WEIGHTS_SHA256:
            parser.error(f"Supply the exact published safetensors checkpoint from {WEIGHTS_URL}")
        weights = load_file(args.weights)
        if args.phase == "fit":
            fit(args.project_root, args.output, weights, args.threads)
        else:
            if args.suite is None:
                parser.error("Select a configuration using the tune-only development suite")
            select(args.project_root, args.output, args.suite, weights, args.threads)


if __name__ == "__main__":
    main()
