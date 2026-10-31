#!/usr/bin/env python3
"""Summarize recorded MeshLens audit evidence without inventing coverage."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text())


def cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def test_summary(report: dict) -> str:
    counts = report["python_test_summary"]
    passed = counts["tests"] - sum(counts[key] for key in ("failures", "errors", "skipped"))
    return (f"{counts['tests']} collected: {passed} passed, {counts['failures']} failures, "
            f"{counts['errors']} errors, {counts['skipped']} skipped; status {report['status']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", action="store_true", help="Permit a visibly incomplete audit draft")
    args = parser.parse_args()
    audit = read("reports/audit-documentation.json")
    if audit["status"] not in {"completed", "completed_with_open_limits"} and not args.draft:
        raise SystemExit("Complete the documentation record before publishing its summary.")
    metrics = read("reports/metrics.json")
    model = metrics["model"]
    full = read("reports/verification.json")
    clean = read("reports/verification-clean-checkout.json")
    export = read("reports/onnx_parity.json")
    wasm = read("reports/wasm-parity.json")
    migration = read("reports/runtime-upgrade-validation.json")
    lines = [
        "# MeshLens project audit", "",
        "**Owner:** Kumar Waibhav AKshat <kwa.waibhav@gmail.com>", "",
        f"Generated from recorded evidence at {datetime.now(timezone.utc).isoformat()}.", "",
    ]
    if args.draft:
        lines += ["**Audit in progress: final code/test evidence and delivery checks are pending.**", ""]
    lines += [
        "## Conclusion", "",
        "MeshLens is an industrial-mesh inspection prototype for human review. This audit "
        "checks recorded software/workflow cases; it does not establish complete coverage "
        "of every possible edge case or qualify an autonomous production inspection system.", "",
        f"The frozen operating point flagged **{model['true_positive']}/{metrics['test_defect']} "
        f"defects**, missed **{model['false_negative']}**, and flagged "
        f"**{model['false_positive']}/{metrics['test_normal']} normal images**. Recall is "
        f"**{100*model['recall']:.2f}%**, AUROC {model['auroc']:.4f}. This checkpoint cannot "
        "support an automatic material acceptance/rejection claim.", "",
        "## Recorded checks", "",
        "| Area | Observed result | Evidence |", "|---|---|---|",
        f"| Full Python/data/model suite | {test_summary(full)} | [verification](verification.json) |",
        f"| Source-only installed release | {test_summary(clean)} | [clean checkout](verification-clean-checkout.json) |",
        f"| PyTorch/ONNX export | {export['test_images_checked']} test images; "
        f"{export['decision_disagreements']} changed decisions; maximum score difference "
        f"{export['max_score_absolute_difference']:.3g} | [export](onnx_parity.json) |",
        f"| Actual WebAssembly | {wasm['status']}; {wasm['samples']} canonical real-image tensors; "
        f"{wasm['changed_decisions']} changed decisions; maximum score difference "
        f"{wasm['max_score_abs_error']:.3g} | [WASM](wasm-parity.json) |",
    ]
    node_summary = full.get("node_test_summary")
    if node_summary:
        passed_node = node_summary["tests"] - sum(node_summary.get(key, 0) for key in ("failures", "errors", "skipped"))
        lines.append(f"| Node browser/build/server contracts | {node_summary['tests']} collected, {passed_node} passed; "
                     f"{node_summary.get('failures', 0)} failures, {node_summary.get('errors', 0)} errors, "
                     f"{node_summary.get('skipped', 0)} skipped | [verification](verification.json) |")
    for check in [] if node_summary else full.get("checks", []):
        count = re.search(r"^(?:#|\u2139) tests (\d+)$", check.get("output", ""), re.MULTILINE)
        if count and "node" in " ".join(check.get("command", [])).lower():
            lines.append(f"| Node browser/build/server contracts | {count.group(1)} tests; exit code "
                         f"{check['exit_code']} | [verification](verification.json) |")
    lines += [
        "", "The source-only skip is the optional raw audit when raw data is absent. "
        "Tracked real-image inference remains mandatory. Canonical-tensor parity is separate "
        "from browser decoding, DOM behavior and physical cameras.", "",
        "## Severity and disposition", "",
        "`fixed` identifies a corrected issue; `pass` an observed passing check; `open` a remaining "
        "limitation; `physical-unverified` a hardware/operational scenario not measured.", "",
        "| ID | Severity | Disposition | Area | Finding and resolution |",
        "|---|---|---|---|---|",
    ]
    for item in audit["findings"]:
        lines.append("| " + " | ".join(cell(item[key]) for key in ("id", "severity", "status", "area"))
                     + " | " + cell(item["finding"] + " " + item["resolution"]) + " |")
    for name, heading in [("audit-ml.json", "ML pipeline findings"), ("audit-web.json", "Frontend/build/server findings")]:
        path = ROOT / "reports" / name
        if not path.is_file():
            continue
        report = json.loads(path.read_text())
        findings = report.get("findings", [])
        if not findings:
            continue
        lines += ["", "### " + heading, "", "| ID | Severity | Disposition | Finding and resolution |", "|---|---|---|---|"]
        for item in findings:
            disposition = item.get("status", "open")
            if disposition.startswith("open") or disposition == "documented_limit":
                disposition = "open"
            detail = item.get("title", item.get("finding", item.get("area", "Recorded finding")))
            resolution = item.get("resolution", item.get("fix", "See the detailed evidence record."))
            lines.append("| " + " | ".join(cell(value) for value in [item.get("id", "recorded"), item.get("severity", "recorded"), disposition, str(detail) + " " + str(resolution)]) + " |")
    lines += ["", "## Detailed audit evidence", ""]
    for name, label in [
        ("audit-validation.json", "Adversarial coverage, corrected failures and exclusions"),
        ("audit-ml.json", "Dataset, training, export and CLI audit"),
        ("audit-web.json", "Frontend, build and server audit"),
        ("browser-ui-checks.json", "Observed browser interactions"),
        ("audit-documentation.json", "Documentation and workflow audit"),
    ]:
        if (ROOT / "reports" / name).is_file():
            lines.append(f"- [{label}]({name})")
    lines += [
        "", "## Framework boundary diagnostic", "",
        f"The same checkpoint was compared on {migration['images']} calibration/test images "
        f"across PyTorch {migration['reference_torch_version']} and {migration['patched_torch_version']}. "
        f"Strict decision parity is **{migration['status']}**; maximum score difference "
        f"{migration['max_score_abs_error']:.3g}; changed decisions by split "
        f"{migration['changed_decisions_by_split']}. A calibration score exactly equal to the "
        "original frozen threshold crosses it after a tiny floating-point change. The threshold "
        "was not retuned. Numerical tolerances do not alter the strict greater-than rule. "
        "All official test decisions are unchanged. Browser/default CLI use the frozen ONNX "
        "graph. This does not assert identical weights after retraining.", "",
        "## Data and training boundary", "",
        "The source image is the split unit:160 normal fit,52 normal tune,52 normal calibration, "
        "and78 official test images (21 normal/57 defective). Patches remain within source roles. "
        "Fixed synthetic tune alterations are development proxies; real test defects/masks do not "
        "choose weights or threshold. Candidate histories, checkpoint hashes, selection, calibration "
        "scores and per-image predictions remain recorded. Default training reuses matching completed "
        "candidates or resumes matching state. Fresh optimization uses a separate copy, as described "
        "in the [workflow guide](../docs/RUNBOOK.md). Short training smoke tests exercise code; "
        "they do not replace the release quality evaluation.", "",
        "## Camera and industrial limits", "",
        "Camera inspection is serial and sampled, with selectable250/1000/2500ms delay after "
        "completed inspections (default1000ms). Ideal cadence bounds before processing overhead "
        "are4/1/0.4Hz. This is not full-video-FPS processing or a real-time control guarantee. "
        "Source timestamp is after decoding at source selection; processing time covers animation-frame "
        "wait, preprocessing, inference and scoring, excluding file decode/final DOM paint. Model-call "
        "time measures session.run only. Mock streams verify software lifecycle, not physical hardware.", "",
        f"At130% brightness, {metrics['stress_tests']['bright_130_percent']['false_alarms']}/"
        f"{metrics['stress_tests']['bright_130_percent']['normal_samples']} normal images triggered "
        "false alarms. Optics, motion, scale, pose, materials, line speed, drift and long-duration "
        "operation need independent representative measurements. Residuals are review evidence, "
        "not validated segmentation or defect probabilities.", "",
        "## Delivery, rights and audience", "",
        "Both archives contain one MeshLens root with source, locks, scripts, trained assets,18 "
        "real examples, reports, tests and executed notebook. GitHub output excludes raw data/dist. "
        "Complete output includes342 images,57 masks, source license/readme and static dist. Git/hosting "
        "metadata, dependencies, venvs, caches and temporary files are excluded. Final archives receive "
        "CRC and critical embedded-file hash checks after packaging.", "",
        "Original code/documentation: Kumar Waibhav AKshat, MIT. Dataset: MVTec Software GmbH and "
        "original authors, CC BY-NC-SA4.0. Runtime notices remain intact. Advisory scans are dated "
        "named-scope checks, not security certification. The hosted preview remains owner-private.", "",
        "## Unknown coverage", "",
    ]
    lines += ["- " + value for value in audit["unknown_coverage"]]
    lines += ["", "No audit proves that no undiscovered bugs remain. New environments, codecs, browsers, "
              "devices and operating conditions require focused additional checks.", ""]
    content = "\n".join(lines)
    for before, after in [("unit:160", "unit: 160"), (",52", ", 52"), ("and78", "and 78"),
                          ("selectable250", "selectable 250"), ("2500ms", "2500 ms"),
                          ("default1000ms", "default 1000 ms"), ("are4/", "are 4/"),
                          ("At130", "At 130"), ("assets,18", "assets, 18"),
                          ("includes342", "includes 342"), (",57", ", 57"),
                          ("CC BY-NC-SA4", "CC BY-NC-SA 4")]:
        content = content.replace(before, after)
    destination = ROOT / "reports/PROJECT_AUDIT.md"
    destination.write_text(content)
    print(destination)


if __name__ == "__main__":
    main()
