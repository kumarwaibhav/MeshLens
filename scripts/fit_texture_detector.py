"""Fit and select a repeat-based texture detector without opening test images.

Develop uses the fit normals and an independently generated, tune-only
synthetic suite. Calibrate accepts the frozen selection and uses calibration
normals to set its operating point. Reported development performance is
synthetic, not the official real-defect benchmark.
"""
# ruff: noqa: E402 -- Limit numerical threads and bootstrap repository imports before NumPy.

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from time import perf_counter


for variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[variable] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != ROOT / "scripts"]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
from PIL import Image

from meshlens.core import calibrate_threshold, read_manifest
from meshlens.inspection_input import inspection_rgb8
from meshlens.texture_detector import (
    IMAGE_SIZE,
    MODEL_KIND,
    SCORE_DECIMALS,
    VARIANTS,
    analyze_texture,
    score_map,
    score_texture,
    texture_map,
)


TAILS = (0.001, 0.005, 0.02)
SETTINGS = tuple((variant, tail) for variant in VARIANTS for tail in TAILS)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def input_tensor(base: Path, row: dict) -> np.ndarray:
    path = (base / row["path"]).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError("Image path escapes the dataset root")
    data = path.read_bytes()
    if sha256(data) != row["sha256"]:
        raise ValueError(f"Incorrect image digest for {row['path']}")
    with Image.open(io.BytesIO(data)) as image:
        pixels = inspection_rgb8(image, IMAGE_SIZE)
    return pixels.astype(np.float32).transpose(2, 0, 1) / np.float32(255)


def inspect_variants(base: Path, row: dict) -> dict:
    start = perf_counter()
    evidence = analyze_texture(input_tensor(base, row))
    results = {
        f"{variant}:{tail}": score_map(anomaly, tail)
        for variant in VARIANTS
        for anomaly in (texture_map(evidence, variant),)
        for tail in TAILS
    }
    return {
        "path": row["path"],
        "label": int(row["label"]),
        "defect_type": row["defect_type"],
        "source_path": row.get("source_path", row["path"]),
        "periodicity": evidence.periodicity,
        "elapsed_ms": 1000 * (perf_counter() - start),
        "scores": results,
    }


def development_rows(path: Path, manifest: list[dict]) -> list[dict]:
    tune = {row["path"]: row["sha256"] for row in manifest if row["split"] == "tune"}
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    expected = {"clean", "bend", "gap", "fibre", "glue", "contamination"}
    observed = set()
    paths = set()
    for row in rows:
        source = row["source_path"]
        family = row["defect_type"]
        if (
            source not in tune or row["source_sha256"] != tune[source]
            or row["source_split"] != "tune" or family not in expected
            or int(row["label"]) != int(family != "clean")
            or (family == "clean" and row["sha256"] != tune[source])
            or (source, family) in observed or row["path"] in paths
        ):
            raise ValueError("Development suite violates the tune-only contract")
        observed.add((source, family))
        paths.add(row["path"])
    if observed != {(source, family) for source in tune for family in expected}:
        raise ValueError("Development suite does not cover all tune images and families")
    return rows


def run_pool(rows: list[dict], function, workers: int, description: str) -> list[dict]:
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(function, rows):
            results.append(result)
            if len(results) % 52 == 0 or len(results) == len(rows):
                print(f"{description} {len(results)}/{len(rows)}", flush=True)
    return results


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def develop(path: Path, output: Path, manifest: list[dict], workers: int) -> None:
    rows = development_rows(path, manifest)
    fit = [row for row in manifest if row["split"] == "fit"]
    fit_results = run_pool(fit, lambda row: inspect_variants(ROOT, row), workers, "Fit normals")
    dev_results = run_pool(rows, lambda row: inspect_variants(path.parent, row), workers, "Tune suite")
    families = sorted({row["defect_type"] for row in dev_results if row["label"]})
    candidates = []
    for variant, tail in SETTINGS:
        name = f"{variant}:{tail}"
        scale = float(np.quantile([row["scores"][name] for row in fit_results], 0.95))
        if scale <= 0:
            raise ValueError("Fit-normal score scale must be positive")
        clean = [row["scores"][name] / scale for row in dev_results if row["label"] == 0]
        # Development operating point allows at most two tune-clean alerts.
        cutoff = sorted(clean)[-3]
        recall = {}
        for family in families:
            scores = [row["scores"][name] / scale for row in dev_results if row["defect_type"] == family]
            recall[family] = sum(score > cutoff for score in scores) / len(scores)
        candidates.append({
            "kind": MODEL_KIND,
            "image_size": IMAGE_SIZE,
            "variant": variant,
            "tail_fraction": tail,
            "fit_scale": scale,
            "tune_cutoff": cutoff,
            "tune_clean_count": len(clean),
            "tune_clean_alerts": sum(score > cutoff for score in clean),
            "synthetic_recall_by_family": recall,
            "synthetic_macro_recall": sum(recall.values()) / len(recall),
        })
    candidates.sort(key=lambda row: -row["synthetic_macro_recall"])
    chosen = {
        **candidates[0],
        "data_manifest_sha256": sha256((ROOT / "data/manifest.csv").read_bytes()),
        "development_manifest_sha256": sha256(path.read_bytes()),
        "fit_count": len(fit),
        "selection_rule": "Maximum synthetic-family macro recall at no more than two tune-clean alerts",
    }
    save_json(output / "fit-scores.json", fit_results)
    save_json(output / "development-scores.json", dev_results)
    save_json(output / "development-candidates.json", candidates)
    save_json(output / "frozen-candidate.json", chosen)
    print(json.dumps(chosen, indent=2), flush=True)


def calibrate(path: Path, output: Path, manifest: list[dict], workers: int, alpha: float) -> None:
    frozen = json.loads(path.read_text(encoding="utf-8"))
    if "threshold" in frozen or frozen["data_manifest_sha256"] != sha256((ROOT / "data/manifest.csv").read_bytes()):
        raise ValueError("Expected an uncalibrated candidate from this fixed dataset manifest")
    rows = [row for row in manifest if row["split"] == "calibration"]

    def analyze(row: dict) -> dict:
        score, _, periodicity = score_texture(input_tensor(ROOT, row), frozen)
        return {"path": row["path"], "sha256": row["sha256"], "score": score, "periodicity": periodicity}

    results = run_pool(rows, analyze, workers, "Calibration normals")
    final = {
        **frozen,
        "score_decimals": SCORE_DECIMALS,
        "frozen_candidate_sha256": sha256(path.read_bytes()),
        "implementation_sha256": sha256((ROOT / "src/meshlens/texture_detector.py").read_bytes()),
        "preprocessing": "area-rgb8-v1",
        "preprocessing_sha256": sha256((ROOT / "src/meshlens/inspection_input.py").read_bytes()),
        "threshold": calibrate_threshold([row["score"] for row in results], alpha),
        "calibration": {"count": len(rows), "alpha": alpha, "strict_greater_than": True},
    }
    save_json(output / "calibration-scores.json", results)
    save_json(output / "texture-model.json", final)
    print(json.dumps(final, indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--development", type=Path, help="Tune-only development manifest CSV")
    input_group.add_argument("--frozen-candidate", type=Path, help="Calibrate a frozen selection JSON")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--workers", default=2, type=int, choices=(1, 2, 3))
    parser.add_argument("--alpha", type=float, default=0.05)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(ROOT)
    if args.development:
        develop(args.development.resolve(), args.output_dir, manifest, args.workers)
    else:
        calibrate(args.frozen_candidate.resolve(), args.output_dir, manifest, args.workers, args.alpha)


if __name__ == "__main__":
    main()
