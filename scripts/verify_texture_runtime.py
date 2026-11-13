"""Check actual browser scoring on all calibration normals and 12 tune examples.

The official test split is not opened. Scores and strict-cutoff decisions must
match exactly; local maps allow the original 2e-5 FFT roundoff tolerance.
"""
# ruff: noqa: E402 -- Bootstrap repository imports and numerical thread limits.
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

for variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[variable] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != ROOT / "scripts"]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
from PIL import Image
from meshlens.core import read_manifest
from meshlens.inspection_input import inspection_rgb8
from meshlens.texture_detector import IMAGE_SIZE, analyze_texture, score_texture


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=ROOT / "artifacts/texture/texture-model.json")
    parser.add_argument("--calibration-scores", type=Path, default=ROOT / "reports/texture/calibration-scores.json")
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--development-scores", type=Path, default=ROOT / "reports/texture/development-scores.json")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/texture/runtime-parity.json")
    args = parser.parse_args()
    model = json.loads(args.model.read_text())
    if model["data_manifest_sha256"] != digest(ROOT / "data/manifest.csv") or model["development_manifest_sha256"] != digest(args.development):
        raise ValueError("The frozen source or development manifest changed")
    manifest = read_manifest(ROOT)
    cal_rows = [row for row in manifest if row["split"] == "calibration"]
    cal = json.loads(args.calibration_scores.read_text())
    cal_by_path = {row["path"]: row for row in cal}
    if len(cal) != 52 or len(cal_by_path) != 52 or set(cal_by_path) != {row["path"] for row in cal_rows}:
        raise ValueError("Expected exactly all 52 calibration normals")
    tune = {row["path"]: row["sha256"] for row in manifest if row["split"] == "tune"}
    with args.development.open(newline="") as stream:
        development = list(csv.DictReader(stream))
    families = {"clean", "bend", "gap", "fibre", "glue", "contamination"}
    observed = set()
    for row in development:
        key = (row["source_path"], row["defect_type"])
        if (row["source_split"] != "tune" or row["source_path"] not in tune
                or row["source_sha256"] != tune[row["source_path"]]
                or row["defect_type"] not in families or key in observed
                or int(row["label"]) != int(row["defect_type"] != "clean")):
            raise ValueError("Development suite violates its tune-only scope")
        observed.add(key)
    if observed != {(path, family) for path in tune for family in families}:
        raise ValueError("Development suite is incomplete")
    family_counts = Counter()
    selected = []
    for row in development:
        if family_counts[row["defect_type"]] < 2:
            selected.append(row)
            family_counts[row["defect_type"]] += 1
    dev_scores = json.loads(args.development_scores.read_text())
    if len(dev_scores) != len(development) or {r["path"] for r in dev_scores} != {r["path"] for r in development}:
        raise ValueError("Stored development scores are incomplete")
    quantizer = 10 ** model["score_decimals"]

    def rounded(value):
        return math.floor(value * quantizer + 0.5) / quantizer

    score_key = f"{model['variant']}:{model['tail_fraction']}"
    changed = sum(
        (r["scores"][score_key] / model["fit_scale"] > model["tune_cutoff"])
        != (rounded(r["scores"][score_key] / model["fit_scale"]) > rounded(model["tune_cutoff"]))
        for r in dev_scores
    )
    cases = [("calibration", ROOT, row) for row in cal_rows]
    cases += [("development", args.development.parent, row) for row in selected]
    with tempfile.TemporaryDirectory(prefix="meshlens-texture-parity-") as temporary:
        directory = Path(temporary)
        samples = []
        for index, (scope, base, row) in enumerate(cases):
            path = (base / row["path"]).resolve()
            if not path.is_relative_to(base.resolve()) or digest(path) != row["sha256"]:
                raise ValueError("Image bytes differ from the manifest")
            with Image.open(path) as image:
                pixels = inspection_rgb8(image, IMAGE_SIZE)
            tensor = pixels.astype(np.float32).transpose(2, 0, 1) / np.float32(255)
            score, anomaly, periodicity = score_texture(tensor, model)
            evidence = analyze_texture(tensor)
            if scope == "calibration" and (score != cal_by_path[row["path"]]["score"] or row["sha256"] != cal_by_path[row["path"]]["sha256"]):
                raise ValueError("Calibration changed after cutoff fitting")
            input_file = directory / f"{index}.rgb8"
            map_file = directory / f"{index}.map-f32"
            pixels.tofile(input_file)
            anomaly.astype("<f4").tofile(map_file)
            samples.append({"id": f"{scope}:{row['path']}", "scope": scope,
                            "input_file": str(input_file), "map_file": str(map_file),
                            "expected_score": score, "expected_periodicity": periodicity,
                            "expected_repeat_count": evidence.repeat_count})
            if (index + 1) % 16 == 0:
                print(f"Prepared canonical parity {index + 1}/{len(cases)}", flush=True)
        input_path = directory / "inputs.json"
        input_path.write_text(json.dumps({"model": model, "samples": samples}))
        completed = subprocess.run(["node", str(ROOT / "scripts/verify_texture_runtime.mjs"), str(input_path)], check=True, text=True, capture_output=True)
        report = json.loads(completed.stdout)
    report.update({
        "scope": "All 52 calibration normals and two tune-only examples from each of six development families. No official test images.",
        "development_quantization_decision_changes": changed,
        "development_quantization_checked_count": len(dev_scores),
        "calibration_threshold": model["threshold"],
        "calibration_scores_equal_to_threshold": sum(r["score"] == model["threshold"] for r in cal),
        "calibration_scores_strictly_above_threshold": sum(r["score"] > model["threshold"] for r in cal),
        "model_sha256": digest(args.model), "calibration_scores_sha256": digest(args.calibration_scores),
        "python_implementation_sha256": digest(ROOT / "src/meshlens/texture_detector.py"),
        "browser_implementation_sha256": digest(ROOT / "web/texture_detector.js"),
        "preprocessing_sha256": digest(ROOT / "src/meshlens/inspection_input.py"),
        "development_manifest_sha256": digest(args.development),
        "development_scores_sha256": digest(args.development_scores),
        "data_manifest_sha256": digest(ROOT / "data/manifest.csv"),
    })
    report["passed"] = report["passed"] and changed == 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "samples"}, indent=2))
    if not report["passed"]:
        raise SystemExit("Portable texture runtime verification failed")


if __name__ == "__main__":
    main()
