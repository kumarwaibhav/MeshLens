#!/usr/bin/env python3
"""Fit from-scratch normal-only autoencoders and freeze a development winner."""

from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import random
import time

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import roc_auc_score
import torch
from torch import nn
from meshlens.core import load_images, read_manifest, residual_score
from meshlens.model import ConvAutoencoder, load_checkpoint, validate_state_dict

ROOT = Path(__file__).resolve().parents[1]
RECOVERED_COMPACT_SHA256 = (
    "1c1dd61431d666deb3e9ba9b0555939cd4ac1ff7ed3a2f332865851d2db7feb4"
)
RECOVERED_MANIFEST_SHA256 = (
    "178b4090f2486c820f3be2df9580e60be643d7cf7817eb8cd1cb3024a950708f"
)


def validate_history(history: list, candidate: str, epochs: int) -> None:
    if not isinstance(history, list) or len(history) != epochs:
        raise ValueError("Training history length does not match completed epochs")
    for epoch, record in enumerate(history, 1):
        if (
            not isinstance(record, dict)
            or record.get("candidate") != candidate
            or record.get("epoch") != epoch
        ):
            raise ValueError(
                "Training history must contain consecutive candidate epochs"
            )
        for key in ("fit_patch_mse", "tune_image_mse", "elapsed_seconds"):
            value = record.get(key)
            if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid training history value: {key}")


def validate_resume(
    saved: dict, config: dict, epochs: int, manifest_hash: str, model: ConvAutoencoder
) -> None:
    """Check progress before restoring weights, optimizer or global RNG state."""
    try:
        if (
            saved["candidate"] != config
            or saved["target_epochs"] != epochs
            or saved["manifest_sha256"] != manifest_hash
        ):
            raise ValueError("Resume experiment/data contract differs")
        epoch = saved["epoch"]
        if type(epoch) is not int or not 1 <= epoch <= epochs:
            raise ValueError("Resume completed epoch is outside experiment budget")
        validate_history(saved["history"], config["name"], epoch)
        if saved["best_tune_mse"] != min(
            row["tune_image_mse"] for row in saved["history"]
        ):
            raise ValueError(
                "Resume best checkpoint error disagrees with epoch history"
            )
        if not math.isfinite(saved["elapsed_seconds"]) or saved["elapsed_seconds"] < 0:
            raise ValueError("Resume elapsed time is invalid")
        validate_state_dict(saved["state_dict"], model)
        validate_state_dict(saved["best_state_dict"], model)
        optimizer = saved["optimizer_state_dict"]
        groups, parameters = optimizer["param_groups"], list(model.parameters())
        identifiers = list(range(len(parameters)))
        expected_lr = 0.0015 * (0.4 ** (int(epoch >= 15) + int(epoch >= 22)))
        if (
            len(groups) != 1
            or groups[0]["params"] != identifiers
            or not math.isclose(groups[0]["lr"], expected_lr, rel_tol=1e-12)
            or groups[0]["weight_decay"] != 1e-5
            or tuple(groups[0]["betas"]) != (0.9, 0.999)
            or groups[0]["eps"] != 1e-8
            or set(optimizer["state"]) != set(identifiers)
            or any(
                groups[0].get(key, False) is not False
                for key in ("amsgrad", "maximize", "capturable", "differentiable")
            )
        ):
            raise ValueError("Resume AdamW settings/state do not match epoch schedule")
        for index, parameter in enumerate(parameters):
            state = optimizer["state"][index]
            if float(state["step"]) != epoch * 20:
                raise ValueError(
                    "Resume AdamW step count disagrees with completed epochs"
                )
            for key in ("exp_avg", "exp_avg_sq"):
                tensor = state[key]
                if (
                    not isinstance(tensor, torch.Tensor)
                    or tensor.shape != parameter.shape
                    or tensor.dtype != parameter.dtype
                    or not torch.isfinite(tensor).all()
                    or (key == "exp_avg_sq" and torch.any(tensor < 0))
                ):
                    raise ValueError("Resume AdamW moment tensor is invalid")
        np.random.default_rng().bit_generator.state = saved["patch_rng_state"]
        torch.Generator().set_state(saved["torch_rng_state"])
        random.Random().setstate(saved["python_rng_state"])
        state = saved["numpy_rng_state"]
        np.random.RandomState().set_state(
            (
                state[0],
                np.array(state[1], dtype=np.uint32),
                state[2],
                state[3],
                state[4],
            )
        )
    except (KeyError, TypeError, RuntimeError, IndexError, OverflowError) as error:
        raise ValueError("Resume checkpoint is incomplete or invalid") from error


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)


def synthetic_defects(images: np.ndarray, seed: int = 4201) -> np.ndarray:
    """Development-only stress examples; never claimed to be real defects."""
    rng = np.random.default_rng(seed)
    result = images.copy()
    for index, image in enumerate(result):
        y, x = rng.integers(28, 204, size=2)
        if index % 3 == 0:
            image[:, y : y + 16, x : x + 24] = rng.random((3, 1, 1), dtype=np.float32)
        elif index % 3 == 1:
            image[:, y : y + 5, x : x + 45] = 0.03
        else:
            image[:, y : y + 32, x : x + 9] = 0.95
    return result


def reconstruct(
    model: nn.Module, images: np.ndarray, batch_size: int = 8
) -> np.ndarray:
    model.eval()
    chunks = []
    with torch.inference_mode():
        for start in range(0, len(images), batch_size):
            tensor = torch.from_numpy(images[start : start + batch_size])
            chunks.append(model(tensor).cpu().numpy())
    return np.concatenate(chunks)


def train_candidate(
    images: np.ndarray, tune: np.ndarray, config: dict, epochs: int, output: Path
) -> tuple[ConvAutoencoder, list[dict]]:
    seed_everything(config["seed"])
    model = ConvAutoencoder(config["latent_channels"])
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.0015, weight_decay=1e-5)
    rng = np.random.default_rng(config["seed"])
    history, best, best_state = [], float("inf"), None
    patches_per_epoch, batch_size, patch = 1280, 64, 64
    resume_path = output.with_name(f"training-resume-{config['name']}.pt")
    manifest_hash = hashlib.sha256(
        (ROOT / "data/manifest.csv").read_bytes()
    ).hexdigest()
    elapsed_before, first_epoch = 0.0, 1
    if resume_path.is_file():
        saved = torch.load(resume_path, map_location="cpu", weights_only=True)
        validate_resume(saved, config, epochs, manifest_hash, model)
        model.load_state_dict(saved["state_dict"])
        optimizer.load_state_dict(saved["optimizer_state_dict"])
        rng.bit_generator.state = saved["patch_rng_state"]
        torch.set_rng_state(saved["torch_rng_state"])
        random.setstate(saved["python_rng_state"])
        numpy_state = saved["numpy_rng_state"]
        np.random.set_state(
            (
                numpy_state[0],
                np.array(numpy_state[1], dtype=np.uint32),
                numpy_state[2],
                numpy_state[3],
                numpy_state[4],
            )
        )
        history, best, best_state = (
            saved["history"],
            saved["best_tune_mse"],
            saved["best_state_dict"],
        )
        elapsed_before = float(saved["elapsed_seconds"])
        first_epoch = int(saved["epoch"]) + 1
        print(f"Resuming {config['name']} after epoch {first_epoch - 1}", flush=True)
    start = time.perf_counter()
    for epoch in range(first_epoch, epochs + 1):
        model.train()
        losses = []
        for offset in range(0, patches_per_epoch, batch_size):
            crops = []
            for _ in range(min(batch_size, patches_per_epoch - offset)):
                image = images[rng.integers(len(images))]
                y, x = rng.integers(0, image.shape[1] - patch + 1, size=2)
                crop = image[:, y : y + patch, x : x + patch]
                if rng.random() < 0.5:
                    crop = crop[:, :, ::-1]
                if rng.random() < 0.5:
                    crop = crop[:, ::-1, :]
                crops.append(crop.copy())
            clean = torch.from_numpy(np.stack(crops))
            noisy = (clean + config["noise_std"] * torch.randn_like(clean)).clamp(0, 1)
            optimizer.zero_grad(set_to_none=True)
            rebuilt = model(noisy)
            loss = torch.mean((rebuilt - clean) ** 2)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach()))
        prediction = reconstruct(model, tune)
        tune_mse = float(np.mean((prediction - tune) ** 2))
        if not math.isfinite(tune_mse) or not all(
            math.isfinite(value) for value in losses
        ):
            raise ValueError("Non-finite training loss; progress was not committed")
        record = {
            "candidate": config["name"],
            "epoch": epoch,
            "fit_patch_mse": float(np.mean(losses)),
            "tune_image_mse": tune_mse,
            "elapsed_seconds": round(elapsed_before + time.perf_counter() - start, 3),
        }
        history.append(record)
        print(json.dumps(record), flush=True)
        if tune_mse < best:
            best = tune_mse
            best_state = {
                key: value.detach().clone() for key, value in model.state_dict().items()
            }
        if epoch in {15, 22}:
            for group in optimizer.param_groups:
                group["lr"] *= 0.4
        # Commit the complete state at every epoch boundary, after LR scheduling.
        # The next process resumes the same patch/noise stream and AdamW state.
        numpy_state = np.random.get_state()
        progress = {
            "candidate": dict(config),
            "target_epochs": epochs,
            "manifest_sha256": manifest_hash,
            "epoch": epoch,
            "state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "patch_rng_state": rng.bit_generator.state,
            "torch_rng_state": torch.get_rng_state(),
            "python_rng_state": random.getstate(),
            "numpy_rng_state": (
                numpy_state[0],
                numpy_state[1].tolist(),
                numpy_state[2],
                numpy_state[3],
                numpy_state[4],
            ),
            "history": history,
            "best_tune_mse": best,
            "best_state_dict": best_state,
            "elapsed_seconds": elapsed_before + time.perf_counter() - start,
        }
        temporary = resume_path.with_suffix(".pt.tmp")
        torch.save(progress, temporary)
        temporary.replace(resume_path)
    model.load_state_dict(best_state)
    model.eval()
    config = dict(
        config,
        best_tune_mse=best,
        epochs=epochs,
        patches_per_epoch=patches_per_epoch,
        batch_size=batch_size,
        patch_size=patch,
        image_size=256,
        parameters=sum(p.numel() for p in model.parameters()),
        best_epoch=min(history, key=lambda row: row["tune_image_mse"])["epoch"],
    )
    torch.save(
        {
            "state_dict": model.state_dict(),
            "config": config,
            "history": history,
            "manifest_sha256": manifest_hash,
        },
        output,
    )
    return model, history


def reusable_candidate(output: Path, config: dict, epochs: int):
    """Reuse a finished matching candidate; never overwrite recovered training."""
    if not output.is_file():
        return None
    saved = torch.load(output, map_location="cpu", weights_only=True)
    stored = saved["config"]
    if (
        any(stored.get(key) != value for key, value in config.items())
        or stored.get("epochs") != epochs
    ):
        raise ValueError(f"Existing candidate does not match experiment: {output}")
    manifest_hash = hashlib.sha256(
        (ROOT / "data/manifest.csv").read_bytes()
    ).hexdigest()
    if "manifest_sha256" not in saved and (
        config["name"] != "compact-clean"
        or hashlib.sha256(output.read_bytes()).hexdigest() != RECOVERED_COMPACT_SHA256
        or manifest_hash != RECOVERED_MANIFEST_SHA256
    ):
        raise ValueError(
            "Legacy candidate without data lineage is not the pinned recovered compact checkpoint"
        )
    if saved.get("manifest_sha256", manifest_hash) != manifest_hash:
        raise ValueError(f"Candidate dataset manifest differs: {output}")
    records = saved.get("history", [])
    if not records:
        # The recovered original compact candidate predates embedded history.
        # Recover its real epoch records, not estimated or synthetic curves.
        by_epoch = {}
        for line in (ROOT / "reports/training.log").read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("candidate") == config["name"] and "epoch" in row:
                by_epoch[int(row["epoch"])] = row
        try:
            records = [by_epoch[epoch] for epoch in range(1, epochs + 1)]
        except KeyError as error:
            raise ValueError(
                f"Candidate lacks complete real training history: {output}"
            ) from error
    validate_history(records, config["name"], epochs)
    if (
        min(records, key=lambda row: row["tune_image_mse"])["epoch"]
        != stored["best_epoch"]
        or min(row["tune_image_mse"] for row in records) != stored["best_tune_mse"]
    ):
        raise ValueError("Candidate best checkpoint disagrees with real epoch history")
    model, _ = load_checkpoint(output)
    print(f"Reusing completed {config['name']} ({epochs} epochs)", flush=True)
    return model, records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=26)
    args = parser.parse_args()
    if not 2 <= args.epochs <= 100:
        parser.error("epochs must lie between 2 and 100")
    torch.set_num_threads(4)
    rows = read_manifest(ROOT)
    fit_rows = [row for row in rows if row["split"] == "fit"]
    tune_rows = [row for row in rows if row["split"] == "tune"]
    fit, tune = load_images(ROOT, fit_rows), load_images(ROOT, tune_rows)
    synthetic = synthetic_defects(tune)
    artifacts, reports = ROOT / "artifacts", ROOT / "reports"
    artifacts.mkdir(exist_ok=True)
    (reports / "figures").mkdir(parents=True, exist_ok=True)
    configs = [
        {"name": "compact-clean", "latent_channels": 4, "noise_std": 0.0, "seed": 42},
        {"name": "denoising", "latent_channels": 8, "noise_std": 0.035, "seed": 43},
    ]
    experiments, history = [], []
    for config in configs:
        path = artifacts / f"candidate-{config['name']}.pt"
        cached = reusable_candidate(path, config, args.epochs)
        model, records = (
            cached
            if cached is not None
            else train_candidate(fit, tune, config, args.epochs, path)
        )
        history.extend(records)
        normal_rebuilt = reconstruct(model, tune)
        stored = torch.load(path, map_location="cpu", weights_only=True)["config"]
        measured_mse = float(np.mean((normal_rebuilt - tune) ** 2))
        if abs(measured_mse - stored["best_tune_mse"]) > 1e-7:
            raise ValueError(
                "Reused candidate does not reproduce its recorded normal tune MSE"
            )
        synthetic_rebuilt = reconstruct(model, synthetic)
        for fraction in [0.01, 0.05]:
            normal_scores = [
                residual_score(image, rebuilt, fraction)[0]
                for image, rebuilt in zip(tune, normal_rebuilt)
            ]
            synthetic_scores = [
                residual_score(image, rebuilt, fraction)[0]
                for image, rebuilt in zip(synthetic, synthetic_rebuilt)
            ]
            auc = float(
                roc_auc_score(
                    [0] * len(tune) + [1] * len(tune), normal_scores + synthetic_scores
                )
            )
            experiments.append(
                {
                    **config,
                    "epochs": args.epochs,
                    "top_fraction": fraction,
                    "development_synthetic_auroc": auc,
                    "normal_tune_mse": measured_mse,
                    "checkpoint": str(path.relative_to(ROOT)),
                    "best_epoch": min(records, key=lambda r: r["tune_image_mse"])[
                        "epoch"
                    ],
                }
            )
    winner = sorted(
        experiments,
        key=lambda row: (
            -row["development_synthetic_auroc"],
            row["normal_tune_mse"],
            row["top_fraction"],
        ),
    )[0]
    checkpoint = torch.load(
        ROOT / winner["checkpoint"], map_location="cpu", weights_only=True
    )
    checkpoint["config"]["top_fraction"] = winner["top_fraction"]
    torch.save(checkpoint, artifacts / "checkpoint.pt")
    selection = {
        "selected": winner,
        "candidates": experiments,
        "selection_rule": "Maximize AUROC of normal tune52 versus fixed synthetic alterations of the same tune52; ties favor lower normal MSE, then smaller top fraction. Checkpoint minimizes normal tune MSE.",
        "test_loaded_during_selection": False,
        "calibration_loaded_during_selection": False,
        "seed_policy": "Data split42; compact42; denoising43; synthetic4201",
        "manifest_sha256": hashlib.sha256(
            (ROOT / "data/manifest.csv").read_bytes()
        ).hexdigest(),
        "synthetic_defects": "Colored 16x24 rectangle, dark5x45 cut, bright32x9 streak on tune images only; proxies do not replace real held-out defects.",
    }
    (reports / "selection.json").write_text(json.dumps(selection, indent=2) + "\n")
    with (reports / "training_history.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(history[0]), lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(history)
    fig, ax = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    for name in [config["name"] for config in configs]:
        rows_for = [row for row in history if row["candidate"] == name]
        ax[0].plot(
            [r["epoch"] for r in rows_for],
            [r["fit_patch_mse"] for r in rows_for],
            label=name,
        )
        ax[1].plot(
            [r["epoch"] for r in rows_for],
            [r["tune_image_mse"] for r in rows_for],
            label=name,
        )
    for panel, title in zip(
        ax, ["Normal fit patches", "Reserved normal development images"]
    ):
        panel.set(
            xlabel="Epoch", ylabel="Mean squared reconstruction error", title=title
        )
        panel.legend()
        panel.grid(alpha=0.25)
    fig.savefig(reports / "figures/training_curves.png", dpi=180)
    plt.close(fig)
    print("FROZEN SELECTION", json.dumps(winner), flush=True)


if __name__ == "__main__":
    main()
