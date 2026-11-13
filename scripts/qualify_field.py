#!/usr/bin/env python3
"""Run field acceptance checks on scores from a frozen MeshLens release."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from meshlens.field_qualification import qualify_field  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-manifest", type=Path, required=True, help="Frozen roster of independently labeled physical parts")
    parser.add_argument("--records", type=Path, required=True, help="CSV scores from one run")
    parser.add_argument("--provenance", type=Path, required=True, help="Field protocol and run digests")
    parser.add_argument("--model-artifact", type=Path, required=True, help="The exact frozen model file used in the run")
    parser.add_argument("--model-metadata", type=Path, required=True, help="Frozen JSON with version, threshold and model SHA256")
    parser.add_argument("--exclude-manifest", type=Path, action="append", default=[], help="Additional development image CSV with a sha256 column")
    parser.add_argument("--report", type=Path, help="Write JSON to a new file. Defaults to stdout.")
    args = parser.parse_args()
    try:
        report = qualify_field(
            ROOT,
            cohort_manifest=args.cohort_manifest,
            records=args.records,
            provenance=args.provenance,
            model_artifact=args.model_artifact,
            model_metadata=args.model_metadata,
            exclude_manifests=tuple(args.exclude_manifest),
        )
        output = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.report:
            with args.report.open("x", encoding="utf-8") as stream:
                stream.write(output)
        else:
            sys.stdout.write(output)
    except (OSError, ValueError, csv.Error) as error:
        print(f"Invalid field qualification evidence: {error}", file=sys.stderr)
        return 2
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
