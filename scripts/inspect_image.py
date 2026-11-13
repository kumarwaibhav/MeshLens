#!/usr/bin/env python3
"""Inspect a still PNG/JPEG/WebP with the frozen detector, entirely offline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from meshlens.inspection import InspectionDetector  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="One still image, no larger than 12 MiB")
    parser.add_argument("--bundle", type=Path, default=ROOT, help="Root containing frozen artifacts/inspection and reports/inspection")
    parser.add_argument("--output", type=Path, help="Optional new JSON result file")
    parser.add_argument("--evidence", type=Path, help="Optional new directory for canonical-input.png, relative-anomaly-map.png and result.json")
    args = parser.parse_args(argv)
    destinations = [args.output] if args.output else []
    if args.evidence:
        destinations.extend(args.evidence / name for name in ("canonical-input.png", "relative-anomaly-map.png", "result.json"))
    protected = [(args.bundle / name).resolve() for name in ("artifacts", "data", "reports", "src", "scripts", "web", "tests")]
    for target in destinations:
        absolute = target.resolve()
        if absolute == args.image.resolve() or any(absolute.is_relative_to(directory) for directory in protected):
            parser.error("Outputs must be outside input and frozen bundle source/data/artifact/report paths")
        if target.exists():
            parser.error(f"Output file already exists: {target}")
    if args.output and args.evidence and args.output.resolve() in {path.resolve() for path in destinations[1:]}:
        parser.error("--output must differ from evidence filenames")
    if args.evidence and args.evidence.exists():
        parser.error("Use a new evidence directory to preserve earlier inspections")
    result = InspectionDetector(args.bundle).inspect(args.image)
    document = result.to_dict()
    document["anomaly_map_kind"] = "relative differences within this image; not a probability or segmentation mask"
    if args.evidence and result.status == "scored":
        document["evidence"] = {"canonical_input": "canonical-input.png", "relative_anomaly_map": "relative-anomaly-map.png", "map_normalization": "per-image maximum; zero map stays zero"}
    output = json.dumps(document, indent=2, allow_nan=False) + "\n"
    try:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(output)
        if args.evidence:
            args.evidence.mkdir(parents=True, exist_ok=False)
            if result.status == "scored":
                with (args.evidence / "canonical-input.png").open("xb") as stream:
                    Image.fromarray(result.canonical_input).save(stream, format="PNG")
                maximum = float(np.max(result.anomaly_map))
                relative = result.anomaly_map / maximum if maximum > 0 else np.zeros_like(result.anomaly_map)
                gray = np.floor(np.clip(relative, 0, 1) * 255 + 0.5).astype(np.uint8)
                with (args.evidence / "relative-anomaly-map.png").open("xb") as stream:
                    Image.fromarray(gray).save(stream, format="PNG")
            with (args.evidence / "result.json").open("x", encoding="utf-8") as stream:
                stream.write(output)
    except OSError as error:
        print(f"Could not save inspection output: {error}", file=sys.stderr)
        return 2
    print(output, end="")
    return 0 if result.status == "scored" else 1


if __name__ == "__main__":
    raise SystemExit(main())
