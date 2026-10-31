#!/usr/bin/env python3
"""Generate documentation and PDF from this run's measured MeshLens artifacts."""

from __future__ import annotations
import argparse
import json
import math
import re
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
NAVY = colors.HexColor("#193744")
TEAL = colors.HexColor("#116c70")
MUTED = colors.HexColor("#526d75")
PALE = colors.HexColor("#edf3f1")
PW, PH = A4
WIDTH = PW - 100


def read(relative: str) -> dict:
    path = ROOT / relative
    if not path.is_file():
        raise SystemExit("Required current-run evidence is missing: " + relative)
    return json.loads(path.read_text())


def percent(value: float) -> str:
    return f"{100 * value:.2f}%"


def marked(text: str, name: str, replacement: str) -> str:
    start, end = (f"<!-- MESHLENS_{name}_START -->", f"<!-- MESHLENS_{name}_END -->")
    if start not in text or end not in text:
        raise ValueError("Missing README section markers: " + name)
    return (
        text.split(start, 1)[0]
        + start
        + "\n"
        + replacement
        + "\n"
        + end
        + text.split(end, 1)[1]
    )


def verification_records() -> list[str]:
    """Summarize only evidence files actually present in this release."""
    records = []
    path = ROOT / "reports/verification.json"
    if path.is_file():
        current = json.loads(path.read_text())
        summary = current.get("python_test_summary", {})
        passed = summary.get("tests", 0) - sum(summary.get(key, 0) for key in ("failures", "errors", "skipped"))
        records.append(
            f"Source/model verification: {current['status']}; "
            f"{summary.get('tests', 'recorded')} Python tests, {passed} passed, "
            f"{summary.get('failures', 0)} failures, {summary.get('errors', 0)} errors "
            f"and {summary.get('skipped', 0)} skips."
        )
        node_summary = current.get("node_test_summary")
        if node_summary:
            passed_node = node_summary.get("tests", 0) - sum(node_summary.get(key, 0) for key in ("failures", "errors", "skipped"))
            records.append(
                f"Node.js browser-contract tests: {node_summary['tests']} tests, {passed_node} passed, "
                f"{node_summary.get('failures', 0)} failures, {node_summary.get('errors', 0)} errors "
                f"and {node_summary.get('skipped', 0)} skipped."
            )
        for check in [] if node_summary else current.get("checks", []):
            output = check.get("output", "")
            count = re.search(r"^(?:#|\u2139) tests (\d+)$", output, flags=re.MULTILINE)
            if count and "node" in " ".join(check.get("command", [])).lower():
                records.append(
                    f"Node.js browser-contract tests: {count.group(1)} tests; "
                    f"{'passed' if check['exit_code'] == 0 else 'failed'}."
                )
    path = ROOT / "reports/verification-clean-checkout.json"
    if path.is_file():
        current = json.loads(path.read_text())
        summary = current.get("python_test_summary", {})
        passed = summary.get("tests", 0) - sum(summary.get(key, 0) for key in ("failures", "errors", "skipped"))
        records.append(
            f"Source-only checkout verification: {current['status']}; "
            f"{summary.get('tests', 'recorded')} Python tests, {passed} passed, "
            f"{summary.get('failures', 0)} failures, {summary.get('errors', 0)} errors "
            f"and {summary.get('skipped', 0)} skipped. The optional full raw-data audit "
            "is separate from mandatory tracked-model/example inference."
        )
    path = ROOT / "reports/onnx_parity.json"
    if path.is_file():
        item = json.loads(path.read_text())
        records.append(
            f"PyTorch/ONNX export check: {item['test_images_checked']} official test images, "
            f"maximum tensor difference {item['max_tensor_absolute_difference']:.3g}, "
            f"maximum score difference {item['max_score_absolute_difference']:.3g}, "
            f"{item['decision_disagreements']} changed decisions."
        )
    path = ROOT / "reports/wasm-parity.json"
    if path.is_file():
        item = json.loads(path.read_text())
        records.append(
            f"Actual ONNX Runtime Web WebAssembly under Node.js: {item['status']}; "
            f"{item['samples']} shared canonical tensors, maximum score difference "
            f"{item['max_score_abs_error']:.3g}, {item['changed_decisions']} changed decisions. "
            "Browser decoding, DOM interactions and physical cameras are outside this check."
        )
    path = ROOT / "reports/runtime-upgrade-validation.json"
    if path.is_file():
        item = json.loads(path.read_text())
        record = (
            f"Framework boundary diagnostic: PyTorch {item['reference_torch_version']} to "
            f"{item['patched_torch_version']} on {item['images']} calibration/test images. "
            f"Strict decision parity {item['status']}; maximum score difference "
            f"{item['max_score_abs_error']:.3g}. "
        )
        by_split = item.get("changed_decisions_by_split", {})
        if by_split:
            record += (
                f"Changed decisions: calibration {by_split.get('calibration', 0)}, "
                f"official test {by_split.get('test', 0)}. "
            )
        if item.get("calibration_reference_equal_to_threshold") and by_split.get("calibration"):
            record += (
                "A calibration score exactly equal to the frozen threshold crosses it "
                "after a tiny floating-point change. Numerical tolerances are met, "
                "but exact decision equality is not. The threshold was not retuned. "
            )
        record += "Browser/CLI inference use the frozen ONNX graph. No retraining is implied."
        records.append(record)
    path = ROOT / "reports/security-audit-summary.json"
    if path.is_file():
        audit = json.loads(path.read_text())
        parts = []
        for key, label in [("runtime", "recommended runtime"), ("development", "development")]:
            item = audit["scopes"].get(key)
            if item:
                parts.append(
                    f"{label}: {item['status']}, {item['audited_packages']}/"
                    f"{item['expected_packages']} packages, {item['vulnerability_count']} findings"
                )
        historical = audit["scopes"].get("original_training")
        if historical:
            parts.append(
                f"historical original-training lock: {historical['vulnerability_count']} findings "
                "(provenance only, not the default install)"
            )
        npm_path = ROOT / "reports/npm-audit.json"
        if npm_path.is_file():
            npm = json.loads(npm_path.read_text())
            parts.append(f"npm: {npm['metadata']['vulnerabilities']['total']} findings")
        records.append(
            "Named-scope dependency advisory scans: " + "; ".join(parts)
            + ". These scans are not security certification."
        )
    return records


def release_docs(meta: dict, metrics: dict, selection: dict) -> None:
    model, baseline = (metrics["model"], metrics["baseline_patch_pca"])
    chosen = selection["selected"]
    diagram = ROOT / "reports/model-architecture.svg"
    if diagram.is_file():
        content = (
            diagram.read_text()
            .replace(
                "Selected latent channels",
                f"{chosen['latent_channels']} latent channels",
            )
            .replace("Channels latent", f"Channels {chosen['latent_channels']}")
        )
        diagram.write_text(content)
    interval = metrics["confidence_intervals_95"]["auroc"]
    result = "| Frozen method | AUROC | Average precision | Precision | Defect recall | F1 |\n|---|---:|---:|---:|---:|---:|\n"
    for label, row in [
        ("Convolutional autoencoder", model),
        ("Patch PCA baseline", baseline),
    ]:
        result += f"| {label} | {row['auroc']:.4f} | {row['average_precision']:.4f} | {percent(row['precision'])} | {percent(row['recall'])} | {percent(row['f1'])} |\n"
    result += f"\nAt the frozen threshold, **{model['true_positive']} of {metrics['test_defect']} defects** were flagged, **{model['false_negative']} were missed**, and **{model['false_positive']} of {metrics['test_normal']} normal images** were flagged. The stratified fixed-model bootstrap 95% AUROC interval is {interval['lower']:.4f}-{interval['upper']:.4f}. It measures resampling uncertainty for this fixed model, not retraining or new-factory variation.\n\nDevelopment selected `{chosen['name']}`, {chosen['latent_channels']} latent channels, checkpoint epoch {chosen['best_epoch']}, and the largest {100 * chosen['top_fraction']:g}% of pixel residuals. Separate normal calibration fixed the threshold at `{meta['threshold']:.8f}`.\n"
    wilson = metrics.get("binomial_wilson_intervals_95")
    if wilson:
        result += f"\nWilson 95% precision interval: {percent(wilson['precision']['lower'])}-{percent(wilson['precision']['upper'])}; normal false-alarm interval: {percent(wilson['false_alarm_rate']['lower'])}-{percent(wilson['false_alarm_rate']['upper'])}. Zero observed false alarms is not proof of zero population risk.\n"
    verification = "\n\n".join(verification_records())
    if not verification:
        verification = "Verification evidence is not yet available for this release."
    readme = ROOT / "README.md"
    content = marked(
        readme.read_text(),
        "MEASURED_RESULTS",
        result.replace("bootstrap 95%", "bootstrap 95%").replace(
            "Wilson 95%", "Wilson 95%"
        ),
    )
    readme.write_text(marked(content, "VERIFICATION", verification))
    groups = "\n".join(
        (
            f"| {name.replace('_', ' ').title()} | {row['count']} | {row['flagged']} | {percent(row['flag_rate'])} |"
            for name, row in metrics["per_defect"].items()
        )
    )
    stress = "\n".join(
        (
            f"| {name.replace('_', ' ')} | {row['false_alarms']}/{row['normal_samples']} | {percent(row['false_alarm_rate'])} |"
            for name, row in metrics["stress_tests"].items()
        )
    )
    trials = "\n".join(
        (
            f"| {row['name']} | {row['latent_channels']} | {row['noise_std']} | {100 * row['top_fraction']:g}% | {row['development_synthetic_auroc']:.4f} |"
            for row in selection["candidates"]
        )
    )
    card = f"# Model card: MeshLens convolutional autoencoder\n\n**Owner:** Kumar Waibhav AKshat <kwa.waibhav@gmail.com>\n\n## Intended use\n\nImage-level anomaly review for controlled views of industrial mesh-like material. The model\nlearns normal patterns and exposes reconstruction-error evidence. It does not diagnose a\nphysical defect type, supply a defect probability or deliver validated pixel segmentation.\nIt is a reproducible research/portfolio inspection system, not a factory-qualified controller.\n\n## Frozen configuration\n\n| Property | Measured release value |\n|---|---|\n| Candidate | `{chosen['name']}` |\n| Input/output | RGB Float32 NCHW `[1,3,256,256]`, `[0,1]` |\n| Encoder channels |3 >12 >16 >24 >{chosen['latent_channels']}|\n| Decoder channels |{chosen['latent_channels']} >24 >16 >12 >3|\n| Parameters |{meta['architecture']['parameters']:,}|\n| Hidden/output activations |LeakyReLU0.1; linear bottleneck; sigmoid output|\n| Boundary |Reflect-pad 16 pixels, reconstruct, crop back|\n| Training patches |64x64 normal patches, normal-pattern flips|\n| Input Gaussian noise std |{chosen['noise_std']}|\n| Selected checkpoint epoch |{chosen['best_epoch']} of {chosen['epochs']}|\n| Image score |Mean highest{100 * chosen['top_fraction']:g}% squared RGB residuals; count rounded upward|\n| Threshold |`{meta['threshold']:.10f}`|\n| Decision |Review only if score strictly exceeds threshold|\n\nAll parameters are trained from random initialization. The trusted checkpoint is loaded with\n`weights_only=True`; never load checkpoints from untrusted sources. The exported graph,\nversion, tensor contract and artifact hash are retained with the metadata.\n\n## Selection boundary\n\nFit 160 / tune 52 / calibration 52 use only normal source images; official test 78 remains separate.\nPatches stay in their source-image role. Checkpoint choice minimizes normal tune MSE. Candidate\nand aggregation choice uses normal-versus-fixed-synthetic tune AUROC with the recorded tie\nrule. Synthetic rectangles, cuts and streaks are development proxies rather than real defects.\n\n| Candidate | Latent | Noise std | Top pixels | Synthetic tune AUROC |\n|---|---:|---:|---:|---:|\n{trials}\n\nThe calibration threshold comes from52 separate normal images with alpha = 0.05 and sorted rank\nceil((52+1)*0.95)=51. Its normal-tail interpretation assumes exchangeability and does not\nestablish a false-alarm rate after illumination, scale or viewpoint shift.\n\n## Held-out results\n\n{result}\n\n| Group | Images | Flagged | Flag rate |\n|---|---:|---:|---:|\n{groups}\n\nGood-group flag rate is a normal false-alarm rate. Defect-group flag rates are recalls.\nSmall counts have substantial uncertainty. Fixed-model bootstrap intervals do not include\nretraining or model-selection uncertainty. If no false positives are observed, a degenerate\nprecision bootstrap interval is not proof of perfect population precision; use the recorded\nfinite-count Wilson interval as well.\n\n## Normal-image stress checks\n\n| Condition | False alarms | False-alarm rate |\n|---|---:|---:|\n{stress}\n\nThese modifications probe frozen-model sensitivity on normal images, not factory event rates.\nNo threshold is retuned after observing the held-out test or stress outcomes.\n\n## Framework, export and runtime verification\n\nTraining framework: `{meta['training_framework']['name']} {meta['training_framework']['version']}`.\nThe shipped environment can differ after a security update; framework compatibility records\nstate what was actually checked. Export parity, actual WebAssembly checks and UI/camera checks\nhave different scopes and must not be conflated. Browser/Pillow resampling can differ slightly\nfor arbitrary uploads; tracked opaque examples already have model dimensions.\n\n{verification}\n\n## Limitations and rights\n\nNew material, lighting, blur, mesh scale, pose and camera movement need representative local\nvalidation. The residual can emphasize ordinary edges or reconstruct a defect well enough\nto miss it. A high score supports review; a low score can still hide a defect. Browser-local\nhistory is not authenticated, synchronized or tamper-proof.\n\nOriginal code/documentation are MIT licensed. MVTec AD data, masks, samples and dataset-derived\nmaterial retain CC BY-NC-SA 4.0 terms. See the dataset card and third-party notices.\n"
    for before, after in [
        ("LeakyReLU0.1", "LeakyReLU 0.1"),
        ("Reflect-pad 16", "Reflect-pad 16"),
        ("Mean highest", "Mean highest "),
        ("from52", "from 52"),
        ("alpha = 0.05", "alpha = 0.05"),
        ("CC BY-NC-SA 4.0", "CC BY-NC-SA 4.0"),
        ("bootstrap 95%", "bootstrap 95%"),
        ("Wilson 95%", "Wilson 95%"),
    ]:
        card = card.replace(before, after)
    operations = (
        "## Operational scope and input policy\n\n"
        "The measured checkpoint is a prototype for human review. Its low defect recall does not "
        "qualify automatic material acceptance/rejection or a production quality guarantee.\n\n"
        "Still PNG/JPEG/WebP inputs resolve EXIF orientation and composite transparency over "
        "opaque white before resizing. Bounds are32-4096 pixels per side,16 megapixels and12 MiB "
        "for uploads/CLI files. Browser/Pillow resizing can differ for arbitrary images; opaque "
        "benchmark tensors are unchanged by the alpha policy.\n\n"
        "Camera mode is serial sampled inference, with a selectable250/1000/2500ms delay after "
        "completed inspections (default1000ms). It is not full-video-FPS processing. The source "
        "timestamp is recorded after decoding when source pixels are selected. Processing time "
        "covers animation-frame wait, preprocessing, model inference and scoring, excluding file "
        "decode and final DOM paint. Model inference time covers session.run only. Physical camera "
        "hardware, optics, line speeds and long-duration end-to-end throughput are unverified. "
        "See the workflow guide and project audit for bounded coverage.\n\n"
    )
    for before, after in [("are32", "are 32"), (",16", ", 16"), ("and12", "and 12"),
                          ("selectable250", "selectable 250"), ("2500ms", "2500 ms"),
                          ("default1000ms", "default 1000 ms")]:
        operations = operations.replace(before, after)
    card = card.replace("## Frozen configuration", operations + "## Frozen configuration")
    (ROOT / "docs/MODEL_CARD.md").write_text(card)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "reports/technical_report.pdf"
    )
    args = parser.parse_args()
    meta, evaluation, provenance, selection = (
        read(path)
        for path in [
            "artifacts/metadata.json",
            "reports/metrics.json",
            "data/provenance.json",
            "reports/selection.json",
        ]
    )
    measured, baseline, chosen = (
        evaluation["model"],
        evaluation["baseline_patch_pca"],
        selection["selected"],
    )
    release_docs(meta, evaluation, selection)
    fontdir = Path("/usr/share/fonts/truetype/dejavu")
    regular, bold, mono = ("Helvetica", "Helvetica-Bold", "Courier")
    if (fontdir / "DejaVuSans.ttf").is_file():
        for name, filename in [
            ("Mesh", "DejaVuSans.ttf"),
            ("MeshBold", "DejaVuSans-Bold.ttf"),
            ("MeshMono", "DejaVuSansMono.ttf"),
        ]:
            pdfmetrics.registerFont(TTFont(name, str(fontdir / filename)))
        regular, bold, mono = ("Mesh", "MeshBold", "MeshMono")
    styles = {
        "body": ParagraphStyle(
            "body",
            fontName=regular,
            fontSize=9.3,
            leading=14,
            textColor=NAVY,
            spaceAfter=9,
        ),
        "small": ParagraphStyle(
            "small",
            fontName=regular,
            fontSize=7.8,
            leading=11.5,
            textColor=MUTED,
            spaceAfter=7,
        ),
        "title": ParagraphStyle(
            "title",
            fontName=bold,
            fontSize=39,
            leading=45,
            textColor=NAVY,
            spaceAfter=12,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName=regular,
            fontSize=17,
            leading=25,
            textColor=TEAL,
            spaceAfter=16,
        ),
        "h1": ParagraphStyle(
            "h1", fontName=bold, fontSize=23, leading=29, textColor=NAVY, spaceAfter=16
        ),
        "h2": ParagraphStyle(
            "h2",
            fontName=bold,
            fontSize=12,
            leading=17,
            textColor=TEAL,
            spaceBefore=9,
            spaceAfter=7,
        ),
        "code": ParagraphStyle(
            "code",
            fontName=mono,
            fontSize=7.4,
            leading=11,
            textColor=NAVY,
            backColor=PALE,
            borderPadding=8,
            spaceAfter=10,
        ),
        "cell": ParagraphStyle(
            "cell", fontName=regular, fontSize=8, leading=11, textColor=NAVY
        ),
        "head": ParagraphStyle(
            "head", fontName=bold, fontSize=8, leading=11, textColor=colors.white
        ),
        "metric": ParagraphStyle(
            "metric",
            fontName=bold,
            fontSize=21,
            leading=27,
            textColor=TEAL,
            alignment=TA_CENTER,
        ),
        "label": ParagraphStyle(
            "label",
            fontName=regular,
            fontSize=8,
            leading=12,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
    }
    story = []

    def p(text, style="body"):
        story.append(Paragraph(text, styles[style]))

    def heading(number, text):
        p(number + " / " + text, "h1")

    def page():
        story.append(PageBreak())

    def table(rows, widths):
        cells = [
            [
                Paragraph(escape(str(value)), styles["head" if i == 0 else "cell"])
                for value in row
            ]
            for i, row in enumerate(rows)
        ]
        out = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
        out.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), TEAL),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("LEFTPADDING", (0, 0), (-1, -1), 9),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ]
            )
        )
        story.append(out)

    def fig(name, height=3 * inch):
        from PIL import Image as PILImage

        path = ROOT / "reports/figures" / name
        if not path.is_file():
            raise SystemExit("Missing measured figure: " + name)
        with PILImage.open(path) as image:
            w, h = image.size
        scale = min(WIDTH / w, height / h)
        story.append(
            Image(str(path), width=w * scale, height=h * scale, hAlign="CENTER")
        )

    story.append(Spacer(1, 35))
    p("MeshLens", "title")
    p("Learn the pattern.<br/>Reveal the exception.", "subtitle")
    p(
        "Industrial mesh anomaly detection with a trained convolutional autoencoder, held-out evaluation and real model inference in the browser."
    )
    story.append(Spacer(1, 17))
    cards = Table(
        [
            [
                Paragraph(f"{measured['auroc']:.4f}", styles["metric"]),
                Paragraph(percent(measured["recall"]), styles["metric"]),
                Paragraph(
                    f"{measured['true_positive']}/{evaluation['test_defect']}",
                    styles["metric"],
                ),
            ],
            [
                Paragraph("Held-out AUROC", styles["label"]),
                Paragraph("Defect recall", styles["label"]),
                Paragraph("Defects flagged", styles["label"]),
            ],
        ],
        colWidths=[WIDTH / 3] * 3,
    )
    cards.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("TOPPADDING", (0, 0), (-1, 0), 14),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 14),
            ]
        )
    )
    story.append(cards)
    story.append(Spacer(1, 20))
    p("What was built", "h2")
    p(
        "An audited dataset pipeline; original normal-only model development; separate calibration; frozen checkpoint and ONNX export; a browser inspection workspace; measured plots, tests, an executed notebook, and deployment instructions."
    )
    p("What the results mean", "h2")
    p(
        f"The fixed threshold flagged {measured['true_positive']} defects and missed {measured['false_negative']}; it flagged {measured['false_positive']} of {evaluation['test_normal']} normal images. Precision is {percent(measured['precision'])} and recall is {percent(measured['recall'])}. These counts describe the chosen operating point on a small curated benchmark."
    )
    p(
        "The score is a reconstruction-error statistic, not a defect probability. Residual maps support review and are not validated segmentation. This report summarizes this run's versioned artifacts.",
        "small",
    )
    story.append(Spacer(1, 15))
    p("Kumar Waibhav AKshat<br/>kwa.waibhav@gmail.com")
    p("Technical report / reproducible portfolio release / 2026", "small")
    page()
    heading("01", "Problem and system design")
    p(
        "Industrial grid material has repeated local structure. A broken or bent strand and foreign material can disturb that pattern. Defect-free images are easier to obtain than a comprehensive catalogue of every future defect."
    )
    p(
        "MeshLens learns to reconstruct normal material. It exposes local reconstruction disagreement and compares an image-level error statistic with a frozen normal-calibrated threshold. A reviewer can examine both the reconstruction and residual evidence."
    )
    table(
        [
            ["Stage", "Implementation", "Output"],
            [
                "Acquire/audit",
                "Pinned archive, safe extraction, hashes and image checks",
                "Image-level manifest",
            ],
            [
                "Learn/select",
                "Normal patches, normal tune and fixed synthetic alterations",
                "Chosen from-scratch model",
            ],
            [
                "Calibrate/test",
                "Separate normal threshold calibration; held-out real defects",
                "Frozen rule and measured report",
            ],
            [
                "Inspect locally",
                "Static app and ONNX Runtime Web",
                "Score, reconstruction and evidence",
            ],
        ],
        [85, 245, WIDTH - 330],
    )
    story.append(Spacer(1, 16))
    p("Two environments, one frozen model", "h2")
    p(
        "Python owns development, evaluation and export. The static web app loads the exported graph and executes it locally through WebAssembly. Visitors need no Python installation and send no image to a Python inference service."
    )
    p("User workflow", "h2")
    p(
        "Choose an example, decode a local image, or sample a permitted camera frame; run inspection; compare input/reconstruction/residual views; review the score and threshold; optionally export local history."
    )
    p(
        "The intended setting is a stable inspection view. New materials, lighting, scale or pose require representative camera validation."
    )
    page()
    heading("02", "Dataset and data lineage")
    p(
        f"This acquisition records {provenance['image_count']} real MVTec AD grid images and {provenance['mask_count']} defect masks. Source images are decoded and hashed; counts, duplicate checks and image-level roles are retained in the manifest."
    )
    table(
        [
            ["Partition", "Images", "Use"],
            ["Fit", "160 normal", "Optimize weights using normal patches"],
            [
                "Tune",
                "52 normal",
                "Checkpoint/candidate/score selection with synthetic alterations",
            ],
            ["Calibration", "52 normal", "Freeze the normal-tail threshold"],
            ["Official test", "21 normal + 57 defects", "Final real-image evaluation"],
        ],
        [85, 125, WIDTH - 210],
    )
    story.append(Spacer(1, 11))
    fig("split_distribution.png", 2 * inch)
    p(
        "Defect groups: bent 12, broken 12, glue 11, metal contamination 11 and thread 11. Patches stay in the source image's partition. Real defects/masks do not select weights, score aggregation or threshold.",
        "small",
    )
    p("Acquisition and rights", "h2")
    p(
        "The archive is pinned to immutable mirror revision "
        + escape(provenance["mirror_revision"])
        + ". Archive, image and mask hashes are recorded. The audit checks the pinned mirror and decoded structure; it does not independently compare every byte with a separate official download."
    )
    p(
        "MVTec Software GmbH and original authors retain data rights. Images, masks, samples and dataset-derived material remain subject to CC BY-NC-SA 4.0; the original code's MIT license does not grant commercial data rights.",
        "small",
    )
    page()
    heading("03", "Autoencoder and anomaly score")
    p(
        "Every network parameter is trained from random initialization. The encoder compresses local texture and the decoder reconstructs RGB intensities. No pretrained feature extractor or external anomaly detector runs in the inference path."
    )
    p(
        f"Selected model: {meta['architecture']['parameters']:,} parameters; input-noise standard deviation {chosen['noise_std']}. Deployment uses the clean input directly.",
        "small",
    )
    p(
        "Still PNG/JPEG/WebP inputs resolve EXIF orientation and composite alpha over opaque white before resizing. Bounds: 32-4096 pixels per side, at most 16 megapixels and 12 MiB. Browser/Pillow interpolation can differ; opaque benchmark tensors are unchanged.",
        "small",
    )
    table(
        [
            ["Block", "Operation", "Contract"],
            ["Input", "RGB Float32 [0,1]", "1x3x256x256"],
            ["Boundary", "Reflect-pad 16 pixels", "Crop back after decoding"],
            [
                "Encoder",
                "3x3 convolution, then three stride-2 layers",
                f"3 > 12 > 16 > 24 > {chosen['latent_channels']}",
            ],
            [
                "Decoder",
                "Three stride-2 transpose layers, RGB convolution",
                f"{chosen['latent_channels']} > 24 > 16 > 12 > 3",
            ],
            [
                "Activations",
                "LeakyReLU hidden; linear bottleneck; sigmoid output",
                "Output intensities [0,1]",
            ],
        ],
        [70, 235, WIDTH - 305],
    )
    p("Pixel residual", "h2")
    p(
        "Square the input/reconstruction difference in each normalized RGB channel and average the three values for each pixel. No ground-truth mask enters this computation."
    )
    count = math.ceil(256 * 256 * chosen["top_fraction"])
    p("Image score", "h2")
    p(
        f"Average the largest {count} of 65,536 pixel residuals ({100 * chosen['top_fraction']:g}%, count rounded upward). This fixed aggregation emphasizes localized high-error regions."
    )
    p("Decision", "h2")
    p(
        f"Request review only when score &gt; {meta['threshold']:.8f}. Equality remains within the learned range. The score is not a calibrated probability, and its residual map is not validated segmentation."
    )
    page()
    heading("04", "Training and selection")
    p(
        "Training uses 64 x 64 random patches from normal fit images after image-level preprocessing. Horizontal/vertical flips vary normal patterns. Clean reconstruction and denoising candidates are compared; clean normal patches remain the targets."
    )
    fig("training_curves.png", 2.55 * inch)
    p(
        "Checkpoint selection minimizes full-image reconstruction MSE on reserved normal tune images. Candidate and aggregation selection use normal-versus-fixed-synthetic tune AUROC. Synthetic colored blocks, dark cuts and bright streaks are development proxies, not additional real test defects."
    )
    rows = [["Candidate", "Latent", "Top pixels", "Synthetic tune AUROC"]]
    for item in selection["candidates"]:
        rows.append(
            [
                item["name"],
                item["latent_channels"],
                f"{100 * item['top_fraction']:g}%",
                f"{item['development_synthetic_auroc']:.4f}",
            ]
        )
    table(rows, [145, 50, 95, WIDTH - 290])
    p(
        f"Frozen choice: {escape(chosen['name'])}, {chosen['latent_channels']} latent channels, epoch {chosen['best_epoch']}, top {100 * chosen['top_fraction']:g}% residuals. Ties use the recorded lower-MSE/smaller-tail rule.",
        "small",
    )
    p(
        "Separate normal calibration uses 52 images and alpha = 0.05. The finite-sample sorted rank ceil((52+1)*0.95)=51 targets a normal-tail operating point under exchangeability. It does not guarantee a false-alarm rate under image-formation shift.",
        "small",
    )
    page()
    heading("05", "Held-out performance")
    p(
        "The model, checkpoint, scoring rule and calibration threshold are fixed before official test scoring. Ranking metrics and fixed-threshold metrics describe different aspects of behavior."
    )
    table(
        [
            ["Metric", "Result", "Meaning"],
            ["AUROC", f"{measured['auroc']:.4f}", "Normal/defect score ranking"],
            [
                "Average precision",
                f"{measured['average_precision']:.4f}",
                "Precision-recall ranking",
            ],
            [
                "Precision",
                percent(measured["precision"]),
                "Defects among flagged images",
            ],
            ["Recall", percent(measured["recall"]), "Defects flagged for review"],
            ["F1", percent(measured["f1"]), "Precision/recall harmonic mean"],
        ],
        [110, 100, WIDTH - 210],
    )
    story.append(Spacer(1, 12))
    fig("roc_pr.png", 2.65 * inch)
    interval = evaluation["confidence_intervals_95"]["auroc"]
    p(
        f"Fixed-model stratified bootstrap 95% AUROC interval: {interval['lower']:.4f}-{interval['upper']:.4f}. Resampling test images does not capture retraining or unseen-factory uncertainty.",
        "small",
    )
    if evaluation.get("binomial_wilson_intervals_95"):
        w = evaluation["binomial_wilson_intervals_95"]
        p(
            f"Wilson 95% intervals: precision {percent(w['precision']['lower'])}-{percent(w['precision']['upper'])}; recall {percent(w['recall']['lower'])}-{percent(w['recall']['upper'])}; normal false alarms {percent(w['false_alarm_rate']['lower'])}-{percent(w['false_alarm_rate']['upper'])}.",
            "small",
        )
    p(
        f"Patch PCA baseline: AUROC {baseline['auroc']:.4f}, average precision {baseline['average_precision']:.4f}, recall {percent(baseline['recall'])}. Both methods retain their frozen calibration thresholds.",
        "small",
    )
    p("Operating point", "h2")
    p(
        f"The autoencoder flagged {measured['true_positive']} defects and missed {measured['false_negative']}, with {measured['false_positive']} false alarms among {evaluation['test_normal']} normal images. Good observed precision can accompany low recall; zero observed false alarms does not imply zero population risk."
    )
    page()
    heading("06", "Reconstruction evidence")
    p(
        "The input, reconstruction and squared RGB residual expose why an image may receive a high score. A residual can also reflect normal texture phase, boundaries, contrast or distribution shift."
    )
    fig("reconstruction_examples.png", 7.4 * inch)
    p(
        "These are actual held-out model outputs. Ground-truth masks, if shown, support post-freeze analysis only and are unavailable during normal browser inference. A bright residual is not proof of a physical defect or validated pixel segmentation.",
        "small",
    )
    page()
    heading("07", "Failure and robustness")
    fig("confusion_matrix.png", 2.45 * inch)
    fig("stress_test.png", 2.45 * inch)
    bright = evaluation["stress_tests"]["bright_130_percent"]
    shift = evaluation["stress_tests"]["circular_shift_8_pixels"]
    p(
        f"Brightening normal images to 130% caused {bright['false_alarms']}/{bright['normal_samples']} false alarms; an 8-pixel circular shift caused {shift['false_alarms']}/{shift['normal_samples']}. The model and threshold remained frozen.",
        "small",
    )
    p(
        "These controlled image modifications probe sensitivity rather than estimate factory event rates. Held-out observations are reports, not a new threshold-tuning loop."
    )
    p("Deployment implication", "h2")
    p(
        "Control lighting, view and material scale. Validate representative camera data and agree the false-alarm/missed-defect trade-off before operational use. This curated benchmark does not establish factory qualification or autonomous rejection reliability."
    )
    page()
    heading("08", "Reproduction and verification")
    p(
        "Versioned evidence includes acquisition hashes, the image-level split manifest, candidate records, epoch history, calibration values, per-image test predictions, export parity, plots and an executed notebook."
    )
    p("Rebuild and check", "h2")
    commands = [
        "python -m pip install -r requirements-dev.lock",
        "python -m pip install --no-deps -e .",
        "python scripts/download_data.py",
        "python scripts/train.py",
        "python scripts/evaluate.py",
        "python scripts/export_model.py",
        "python -m pytest -q",
        "npm ci",
        "npm test",
        "npm run build",
    ]
    p("<br/>".join(escape(command) for command in commands), "code")
    p(
        "Seeds and a bounded CPU schedule are recorded. Hardware/library differences can affect floating-point details; numerical agreement must be measured rather than assumed.",
        "small",
    )
    p(
        "The release includes completed candidate checkpoints. The training command validates/reuses matching candidates and recomputes selection. For fresh optimization, first move candidate-*.pt and training-resume-*.pt out of artifacts; retain the release for comparison.",
        "small",
    )
    p("Verification scope", "h2")
    p(
        "These are recorded cases, not proof that every possible edge case is covered. Software/mock-camera checks and physical hardware validation have separate scopes.",
        "small",
    )
    for record in verification_records():
        if not record.startswith("Named-scope"):
            p(escape(record), "small")
    path = ROOT / "notebooks/execution_summary.json"
    if path.is_file():
        item = json.loads(path.read_text())
        p(
            f"Walkthrough: {item['executed_cells']}/{item['code_cells']} code cells executed with real outputs; {item['error_outputs']} errors. Execution engine: {escape(item.get('execution_engine', 'recorded'))}.",
            "small",
        )
    page()
    heading("09", "Deployment and scope")
    p(
        "The website serves HTML, CSS, JavaScript, a local WebAssembly runtime, ONNX graph, metadata and licensed examples. Model inference happens in the browser, without a Python hosting process or remote inference API."
    )
    table(
        [
            ["Concern", "Behavior"],
            [
                "Images",
                "Decoded/inspected locally; not uploaded to a Python inference service",
            ],
            ["History", "Bounded browser-local summaries; clear and CSV export"],
            ["Camera", "User initiated; serial sampled frames; browser permission"],
            ["Model", "Frozen graph/metadata; no website-startup training"],
            ["Hosting", "Static dist output; documented local/static-host paths"],
            ["Audience", "Live publication and access controls verified separately"],
        ],
        [105, WIDTH - 105],
    )
    p("Industrial audit conclusion", "h2")
    p(
        f"This checkpoint flagged {measured['true_positive']}/{evaluation['test_defect']} defects and missed {measured['false_negative']}. It is an industrial-mesh prototype for human review and does not qualify automatic acceptance/rejection. New materials, optics, motion and line speeds need independent representative validation."
    )
    p(
        "Camera mode samples serially, waiting 250/1000/2500 ms after completed inspections (default 1000 ms). It is not full-video-FPS processing. Physical camera hardware, target-line latency and long-duration throughput remain unverified. Model-call time alone is not end-to-end latency.",
        "small",
    )
    p(
        "The detailed project audit (reports/PROJECT_AUDIT.md) separates fixes, passing checks, open limitations and physical-unverified scenarios. A finite test suite cannot prove the absence of undiscovered bugs.",
        "small",
    )
    p("Privacy and persistence", "h2")
    p(
        "Local history can be cleared or altered by the browser user, does not synchronize across devices and is not an authenticated production audit trail. Hosting audience is configured independently of model training."
    )
    for record in verification_records():
        if record.startswith("Named-scope"):
            p(escape(record), "small")
    p("Rights and authorship", "h2")
    p(
        "Original MeshLens code/documentation: Kumar Waibhav AKshat, MIT. MVTec AD images and masks: MVTec Software GmbH and original authors, CC BY-NC-SA 4.0. Review the dataset card and third-party notices before redistribution."
    )
    p(
        "The delivered machine-readable experiment records, test outputs, notebook and deployment record are the source of truth for this release.",
        "small",
    )

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFillColor(TEAL)
        canvas.rect(0, PH - 13, PW, 13, fill=1, stroke=0)
        canvas.setStrokeColor(colors.HexColor("#d9e4e1"))
        canvas.line(50, 39, PW - 50, 39)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(50, 25, "MESHLENS / TECHNICAL REPORT / Kumar Waibhav AKshat")
        canvas.drawRightString(PW - 50, 25, str(document.page))
        canvas.restoreState()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(args.output),
        pagesize=A4,
        leftMargin=50,
        rightMargin=50,
        topMargin=46,
        bottomMargin=52,
        title="MeshLens Technical Report",
        author="Kumar Waibhav AKshat",
        subject="Original autoencoder anomaly detection: measured release",
    )
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    print(args.output)


if __name__ == "__main__":
    main()
