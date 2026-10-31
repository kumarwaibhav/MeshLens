#!/usr/bin/env python3
"""Calibrate the development winner, then evaluate fixed held-out defects."""

from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import time
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from sklearn.decomposition import PCA
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
import torch
from meshlens.core import (
    calibrate_threshold,
    load_images,
    read_manifest,
    residual_score,
)
from meshlens.model import load_checkpoint
from meshlens.artifacts import load_development_selection

ROOT = Path(__file__).resolve().parents[1]


def json_write(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def rebuild(model, images: np.ndarray) -> np.ndarray:
    results = []
    with torch.inference_mode():
        for image in images:
            results.append(model(torch.from_numpy(image[None])).numpy()[0])
    return np.stack(results)


def compute_metrics(labels, scores, threshold: float) -> dict:
    labels, scores = np.asarray(labels), np.asarray(scores)
    predictions = scores > threshold
    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
    return {
        "auroc": float(roc_auc_score(labels, scores)),
        "average_precision": float(average_precision_score(labels, scores)),
        "precision": float(precision_score(labels, predictions, zero_division=0)),
        "recall": float(recall_score(labels, predictions, zero_division=0)),
        "f1": float(f1_score(labels, predictions, zero_division=0)),
        "accuracy": float(accuracy_score(labels, predictions)),
        "true_negative": int(tn),
        "false_positive": int(fp),
        "false_negative": int(fn),
        "true_positive": int(tp),
        "threshold": float(threshold),
        "samples": len(labels),
    }


def confidence_intervals(
    labels, scores, threshold: float, iterations: int = 2000
) -> dict:
    rng = np.random.default_rng(2026)
    labels, scores = np.asarray(labels), np.asarray(scores)
    zero, one = np.flatnonzero(labels == 0), np.flatnonzero(labels == 1)
    values = {
        name: [] for name in ["auroc", "average_precision", "precision", "recall", "f1"]
    }
    for _ in range(iterations):
        index = np.r_[
            rng.choice(zero, len(zero), replace=True),
            rng.choice(one, len(one), replace=True),
        ]
        measured = compute_metrics(labels[index], scores[index], threshold)
        for name in values:
            values[name].append(measured[name])
    return {
        name: {
            "lower": float(np.quantile(measured, 0.025)),
            "upper": float(np.quantile(measured, 0.975)),
        }
        for name, measured in values.items()
    }


def wilson_interval(successes: int, trials: int) -> dict:
    z = 1.959963984540054
    if trials <= 0:
        return {"lower": 0.0, "upper": 1.0}
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    half = (
        z
        * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
        / denominator
    )
    return {"lower": max(0.0, center - half), "upper": min(1.0, center + half)}


def patch_vectors(image: np.ndarray, patch: int = 16) -> np.ndarray:
    channels, height, width = image.shape
    return (
        image.reshape(channels, height // patch, patch, width // patch, patch)
        .transpose(1, 3, 0, 2, 4)
        .reshape(-1, channels * patch * patch)
    )


def pca_rebuild(pca: PCA, images: np.ndarray) -> np.ndarray:
    results = []
    for image in images:
        patches = patch_vectors(image)
        values = pca.inverse_transform(pca.transform(patches))
        results.append(
            np.clip(
                values.reshape(16, 16, 3, 16, 16)
                .transpose(2, 0, 3, 1, 4)
                .reshape(3, 256, 256),
                0,
                1,
            )
        )
    return np.stack(results).astype(np.float32)


def evaluate() -> None:
    torch.set_num_threads(4)
    reports, artifacts = ROOT / "reports", ROOT / "artifacts"
    figures = reports / "figures"
    figures.mkdir(exist_ok=True)
    selection = load_development_selection(ROOT)
    winner = selection["selected"]
    checkpoint_hash = hashlib.sha256(
        (artifacts / "checkpoint.pt").read_bytes()
    ).hexdigest()
    model, config = load_checkpoint(
        artifacts / "checkpoint.pt", expected_sha256=checkpoint_hash
    )
    candidate_model, _ = load_checkpoint(ROOT / winner["checkpoint"])
    if any(
        config.get(key) != winner[key]
        for key in (
            "name",
            "latent_channels",
            "noise_std",
            "seed",
            "epochs",
            "best_epoch",
            "top_fraction",
        )
    ) or any(
        not torch.equal(value, candidate_model.state_dict()[key])
        for key, value in model.state_dict().items()
    ):
        raise ValueError(
            "Frozen checkpoint does not match development-selected candidate"
        )
    del candidate_model
    rows = read_manifest(ROOT)
    calibration_rows = [row for row in rows if row["split"] == "calibration"]
    calibration = load_images(ROOT, calibration_rows)
    top_fraction = winner["top_fraction"]
    calibration_rebuilt = rebuild(model, calibration)
    calibration_scores = [
        residual_score(image, reconstructed, top_fraction)[0]
        for image, reconstructed in zip(calibration, calibration_rebuilt)
    ]
    threshold = calibrate_threshold(calibration_scores, alpha=0.05)
    with (reports / "calibration_scores.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["path", "split", "label", "score"], lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(
            {"path": row["path"], "split": "calibration", "label": 0, "score": score}
            for row, score in zip(calibration_rows, calibration_scores)
        )
    freeze = {
        "candidate": winner,
        "threshold": threshold,
        "top_fraction": top_fraction,
        "calibration_alpha": 0.05,
        "calibration_count": len(calibration_scores),
        "calibration_order_rank": math.ceil((len(calibration_scores) + 1) * 0.95),
        "calibration_score_sha256": hashlib.sha256(
            (reports / "calibration_scores.csv").read_bytes()
        ).hexdigest(),
        "checkpoint_sha256": checkpoint_hash,
        "policy": "Model, score aggregation and threshold fixed before loading official test images.",
    }
    json_write(reports / "frozen_configuration.json", freeze)
    print("FROZEN BEFORE TEST", json.dumps(freeze), flush=True)
    fit_rows = [row for row in rows if row["split"] == "fit"]
    fit = load_images(ROOT, fit_rows)
    all_patches = np.concatenate([patch_vectors(image) for image in fit])
    rng = np.random.default_rng(42)
    selected = all_patches[rng.choice(len(all_patches), 4096, replace=False)]
    pca = PCA(n_components=32, svd_solver="randomized", random_state=42)
    pca.fit(selected)
    np.savez_compressed(
        artifacts / "baseline_pca.npz", mean=pca.mean_, components=pca.components_
    )
    pca_calibration = pca_rebuild(pca, calibration)
    pca_cal_scores = [
        residual_score(image, reconstructed, top_fraction)[0]
        for image, reconstructed in zip(calibration, pca_calibration)
    ]
    pca_threshold = calibrate_threshold(pca_cal_scores, 0.05)
    with (reports / "baseline_calibration_scores.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["path", "split", "label", "score"], lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(
            {"path": row["path"], "split": "calibration", "label": 0, "score": score}
            for row, score in zip(calibration_rows, pca_cal_scores)
        )
    test_rows = [row for row in rows if row["split"] == "test"]
    test = load_images(ROOT, test_rows)
    started = time.perf_counter()
    rebuilt = rebuild(model, test)
    elapsed = time.perf_counter() - started
    score_maps = [
        residual_score(image, reconstructed, top_fraction)
        for image, reconstructed in zip(test, rebuilt)
    ]
    scores = np.array([value[0] for value in score_maps])
    labels = np.array([row["label"] for row in test_rows])
    metrics = compute_metrics(labels, scores, threshold)
    pca_test = pca_rebuild(pca, test)
    pca_scores = [
        residual_score(image, reconstructed, top_fraction)[0]
        for image, reconstructed in zip(test, pca_test)
    ]
    baseline = compute_metrics(labels, pca_scores, pca_threshold)
    predictions = scores > threshold
    test_records = []
    for row, score, predicted, base_score in zip(
        test_rows, scores, predictions, pca_scores
    ):
        test_records.append(
            {
                "path": row["path"],
                "split": "test",
                "label": row["label"],
                "defect_type": row["defect_type"],
                "score": float(score),
                "prediction": int(predicted),
                "threshold": threshold,
                "pca_score": base_score,
            }
        )
    with (reports / "test_scores.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(test_records[0]), lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(test_records)
    defects = {}
    for defect in sorted({row["defect_type"] for row in test_rows}):
        index = np.array([row["defect_type"] == defect for row in test_rows])
        defects[defect] = {
            "count": int(index.sum()),
            "flagged": int(predictions[index].sum()),
            "mean_score": float(scores[index].mean()),
            "flag_rate": float(predictions[index].mean()),
        }
    stress = {}
    normals = test[labels == 0]
    for name, transformed in [
        ("original", normals),
        ("dim_70_percent", normals * 0.7),
        ("bright_130_percent", np.clip(normals * 1.3, 0, 1)),
        ("circular_shift_8_pixels", np.roll(normals, 8, axis=(2, 3))),
    ]:
        predictions_stress = rebuild(model, transformed)
        measured = [
            residual_score(image, reconstructed, top_fraction)[0]
            for image, reconstructed in zip(transformed, predictions_stress)
        ]
        stress[name] = {
            "normal_samples": len(normals),
            "false_alarms": int(np.sum(np.array(measured) > threshold)),
            "false_alarm_rate": float(np.mean(np.array(measured) > threshold)),
            "mean_score": float(np.mean(measured)),
        }
    ci = confidence_intervals(labels, scores, threshold)
    result = {
        "model": metrics,
        "baseline_patch_pca": baseline,
        "baseline_configuration": {
            "patch_size": 16,
            "components": 32,
            "fit_patches": 4096,
            "same_preprocessing_and_top_fraction": True,
        },
        "confidence_intervals_95": ci,
        "binomial_wilson_intervals_95": {
            "precision": wilson_interval(
                metrics["true_positive"],
                metrics["true_positive"] + metrics["false_positive"],
            ),
            "recall": wilson_interval(
                metrics["true_positive"],
                metrics["true_positive"] + metrics["false_negative"],
            ),
            "specificity": wilson_interval(
                metrics["true_negative"],
                metrics["true_negative"] + metrics["false_positive"],
            ),
            "false_alarm_rate": wilson_interval(
                metrics["false_positive"],
                metrics["true_negative"] + metrics["false_positive"],
            ),
        },
        "uncertainty_notes": "Bootstrap intervals condition on observed samples and fixed class counts. If no false positives are observed, the precision bootstrap can degenerate at1; Wilson finite-count intervals remain informative. Neither method covers dataset shift or model-selection uncertainty.",
        "bootstrap": {
            "iterations": 2000,
            "seed": 2026,
            "sampling": "stratified with replacement; fixed model and threshold",
        },
        "per_defect": defects,
        "stress_tests": stress,
        "torch_test_inference": {
            "total_seconds": elapsed,
            "mean_ms": elapsed / len(test) * 1000,
            "threads": 4,
        },
        "evaluation_policy": "Official test evaluated after selection and calibration. No tuning on test results.",
        "test_count": len(test_rows),
        "test_normal": int(np.sum(labels == 0)),
        "test_defect": int(np.sum(labels == 1)),
    }
    json_write(reports / "metrics.json", result)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), constrained_layout=True)
    for name, values in [("Autoencoder", scores), ("Patch PCA", pca_scores)]:
        fpr, tpr, _ = roc_curve(labels, values)
        precision, recall, _ = precision_recall_curve(labels, values)
        axes[0].plot(fpr, tpr, label=f"{name} AUC={roc_auc_score(labels, values):.3f}")
        axes[1].plot(
            recall,
            precision,
            label=f"{name} AP={average_precision_score(labels, values):.3f}",
        )
    axes[0].plot([0, 1], [0, 1], "--", color="gray", alpha=0.5)
    axes[0].scatter(
        [metrics["false_positive"] / 21],
        [metrics["recall"]],
        color="#16a085",
        zorder=5,
        label="Frozen threshold",
    )
    axes[1].axhline(
        labels.mean(), linestyle="--", color="gray", alpha=0.5, label="Test prevalence"
    )
    axes[0].set(
        xlabel="False positive rate", ylabel="Defect recall", title="Held-out ROC"
    )
    axes[1].set(xlabel="Recall", ylabel="Precision", title="Held-out precision–recall")
    for axis in axes:
        axis.legend(fontsize=8)
        axis.grid(alpha=0.2)
    fig.savefig(figures / "roc_pr.png", dpi=180)
    plt.close(fig)
    fig, axis = plt.subplots(figsize=(5, 4), constrained_layout=True)
    matrix = confusion_matrix(labels, predictions, labels=[0, 1])
    axis.imshow(matrix, cmap="Blues")
    for i in range(2):
        for j in range(2):
            axis.text(
                j,
                i,
                str(matrix[i, j]),
                ha="center",
                va="center",
                fontsize=22,
                color="white" if matrix[i, j] > matrix.max() / 2 else "#10233d",
            )
    axis.set(
        xticks=[0, 1],
        yticks=[0, 1],
        xticklabels=["Within range", "Review"],
        yticklabels=["Normal", "Defect"],
        xlabel="Model decision",
        ylabel="Known label",
        title="Frozen-threshold confusion matrix",
    )
    fig.savefig(figures / "confusion_matrix.png", dpi=180)
    plt.close(fig)
    fig, axis = plt.subplots(figsize=(8, 4), constrained_layout=True)
    for label, name, color in [(0, "Normal", "#159f8c"), (1, "Defective", "#e67e4b")]:
        axis.hist(scores[labels == label], bins=16, alpha=0.65, label=name, color=color)
    axis.axvline(threshold, color="#17273c", linestyle="--", label="Frozen threshold")
    axis.set(
        xlabel="Top-pixel mean squared error",
        ylabel="Images",
        title="Held-out anomaly scores",
    )
    axis.legend()
    fig.savefig(figures / "score_distribution.png", dpi=180)
    plt.close(fig)
    fig, axis = plt.subplots(figsize=(8, 3.5), constrained_layout=True)
    counts = {
        role: sum(row["split"] == role for row in rows)
        for role in ["fit", "tune", "calibration", "test"]
    }
    bars = axis.bar(
        list(counts),
        list(counts.values()),
        color=["#167d8d", "#4b9ba7", "#96c9c9", "#d5a05b"],
    )
    axis.bar_label(bars)
    axis.set(ylabel="Source images", title="Image-level data separation")
    fig.savefig(figures / "split_distribution.png", dpi=180)
    plt.close(fig)
    fig, axis = plt.subplots(figsize=(8, 3.8), constrained_layout=True)
    bars = axis.bar(
        [name.replace("_", "\n") for name in stress],
        [value["false_alarm_rate"] for value in stress.values()],
        color="#e67e4b",
    )
    axis.bar_label(
        bars,
        labels=[f"{v['false_alarms']}/{v['normal_samples']}" for v in stress.values()],
    )
    axis.set(
        ylim=(0, 1.18),
        ylabel="False alarm rate",
        title="Normal-image stress test, fixed threshold",
    )
    fig.savefig(figures / "stress_test.png", dpi=180)
    plt.close(fig)
    chosen = [
        next(i for i, row in enumerate(test_rows) if row["defect_type"] == defect)
        for defect in sorted(defects)
    ]
    missed = np.flatnonzero((labels == 1) & (~predictions))
    if len(missed):
        chosen.append(int(missed[0]))
    fig, axes = plt.subplots(
        len(chosen), 4, figsize=(10, 2.2 * len(chosen)), constrained_layout=True
    )
    for index, test_index in enumerate(chosen):
        row = test_rows[test_index]
        axes[index, 0].imshow(test[test_index].transpose(1, 2, 0))
        axes[index, 0].set_ylabel(row["defect_type"], fontsize=9)
        axes[index, 1].imshow(rebuilt[test_index].transpose(1, 2, 0))
        axes[index, 2].imshow(
            score_maps[test_index][1],
            cmap="inferno",
            vmin=0,
            vmax=max(threshold, 0.001),
        )
        if row["mask_path"]:
            with Image.open(ROOT / row["mask_path"]) as mask:
                axes[index, 3].imshow(
                    mask.resize((256, 256), Image.Resampling.NEAREST),
                    cmap="gray",
                    vmin=0,
                    vmax=255,
                )
        else:
            axes[index, 3].imshow(np.zeros((256, 256)), cmap="gray", vmin=0, vmax=255)
        for axis in axes[index]:
            axis.set_xticks([])
            axis.set_yticks([])
        axes[index, 0].set_title(
            f"{'REVIEW' if predictions[test_index] else 'WITHIN RANGE'} · {scores[test_index]:.4f}",
            fontsize=9,
        )
    for axis, title in zip(
        axes[0],
        ["Observed", "Reconstruction", "Residual evidence", "Ground-truth annotation"],
    ):
        axis.set_title(title, fontsize=10)
    fig.savefig(figures / "reconstruction_examples.png", dpi=150)
    plt.close(fig)
    gallery = []
    for defect in sorted(defects):
        gallery.extend(
            [i for i, row in enumerate(test_rows) if row["defect_type"] == defect][:3]
        )
    if len(missed) and int(missed[0]) not in gallery:
        gallery[-1] = int(missed[0])
    first_normal = next(index for index in gallery if test_rows[index]["label"] == 0)
    first_defect = next(index for index in gallery if test_rows[index]["label"] == 1)
    gallery = [first_normal, first_defect] + [
        index for index in gallery if index not in {first_normal, first_defect}
    ]
    sample_dir = artifacts / "samples"
    sample_dir.mkdir(exist_ok=True)
    samples = []
    for index in gallery:
        row = test_rows[index]
        stem = Path(row["path"]).stem
        name = f"{row['defect_type']}-{stem}.png"
        image = np.rint(test[index].transpose(1, 2, 0) * 255).astype(np.uint8)
        Image.fromarray(image).save(sample_dir / name)
        samples.append(
            {
                "id": f"{row['defect_type']}-{stem}",
                "filename": name,
                "label": row["label"],
                "defect_type": row["defect_type"],
                "expected_score": float(scores[index]),
                "expected_anomaly": bool(predictions[index]),
                "source_path": row["path"],
                "sha256": hashlib.sha256((sample_dir / name).read_bytes()).hexdigest(),
            }
        )
    json_write(
        artifacts / "samples.json",
        {
            "samples": samples,
            "count": len(samples),
            "purpose": "Labeled held-out examples, not independent user uploads; includes a missed defect if available.",
            "license": "CC-BY-NC-SA-4.0",
        },
    )
    metadata = {
        "schema_version": 1,
        "name": "MeshLens convolutional autoencoder",
        "model_version": "meshlens-ae-" + freeze["checkpoint_sha256"][:12],
        "owner": {"name": "Kumar Waibhav AKshat", "email": "kwa.waibhav@gmail.com"},
        "image_size": 256,
        "input_name": "image",
        "output_name": "reconstruction",
        "input_shape": [1, 3, 256, 256],
        "input": {
            "color": "RGB",
            "layout": "NCHW",
            "dtype": "float32",
            "range": [0, 1],
            "resize": "Pillow BILINEAR to256x256 for benchmark; browser canvas resampling can differ for arbitrary uploads.",
            "exif_orientation": "transpose before resize",
            "alpha_compositing": "opaque white before resize",
            "supported_upload_formats": ["PNG", "JPEG", "WEBP"],
            "animation": "unsupported; inspect one still frame",
            "min_side": 32,
            "max_side": 4096,
            "max_pixels": 16_000_000,
            "max_file_bytes": 12 * 1024 * 1024,
        },
        "threshold": threshold,
        "top_fraction": top_fraction,
        "score_top_fraction": top_fraction,
        "score": {
            "pixel_error": "mean squared RGB reconstruction error",
            "aggregation": "mean of largest ceil(H*W*top_fraction) pixel errors",
            "top_fraction": top_fraction,
            "pixel_count": math.ceil(256 * 256 * top_fraction),
            "is_probability": False,
            "smoothing": None,
        },
        "calibration": {
            "count": 52,
            "alpha": 0.05,
            "order_statistic_rank": freeze["calibration_order_rank"],
            "method": "Finite-sample upper normal order statistic; defects never used for calibration",
            "strict_greater_than": True,
        },
        "decision": {
            "above_threshold": "review",
            "at_or_below_threshold": "within_range",
            "caveat": "Research decision support; reconstruction residual is not proof or a calibrated defect probability.",
        },
        "architecture": {
            "type": "convolutional denoising autoencoder"
            if config["noise_std"]
            else "convolutional autoencoder",
            "activation": "LeakyReLU0.1 hidden, linear bottleneck, sigmoid output",
            "latent_channels": config["latent_channels"],
            "patch_size": 64,
            "reflection_padding": 16,
            "parameters": config["parameters"],
            "epochs": config["epochs"],
            "best_epoch": config["best_epoch"],
            "noise_std": config["noise_std"],
            "training_seed": config["seed"],
        },
        "training_framework": {
            "name": "PyTorch",
            "version": torch.__version__,
            "python": platform.python_version(),
            "numpy": np.__version__,
            "device": "CPU",
            "threads": 4,
        },
        "dataset": {
            "name": "MVTec AD",
            "category": "grid",
            "license": "CC-BY-NC-SA-4.0",
            "fit": 160,
            "tune": 52,
            "calibration": 52,
            "test": 78,
        },
        "metrics": metrics,
        "limitations": [
            "Single grid category and fixed benchmark distribution.",
            "52 calibration normals and78 test images yield substantial sampling uncertainty.",
            "Reconstruction may reproduce defects and miss them; residual maps are not segmentation predictions.",
            "Lighting, viewpoint, material and camera changes require local validation.",
            "Browser benchmark samples are preprocessed identically; arbitrary image resizing differs across runtimes.",
        ],
        "history_mode": "browser-local",
        "qualification": {
            "status": "research_prototype",
            "automated_line_inspection_qualified": False,
            "physical_camera_validation_completed": False,
            "reason": f"Frozen benchmark recall{metrics['true_positive']}/{int(labels.sum())};{metrics['false_negative']} defects missed. No factory camera, deadline or process qualification.",
        },
    }
    json_write(artifacts / "metadata.json", metadata)
    print("FINAL METRICS", json.dumps(result), flush=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        evaluate()
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
