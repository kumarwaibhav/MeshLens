#!/usr/bin/env python3
"""Build the editable MeshLens report and its GitHub-readable Markdown edition.

Run from the project root. Rendering to PDF needs LibreOffice on PATH.
The figures read the frozen evidence; this builder never trains a model.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / 'docs/report'
REFERENCE = '5f11b39fbd989e2b4f6359dc75cda062daf8b9ba'
OWNER = 'Kumar Waibhav Akshat'
DATE = '14 November 2026'
INK = '163F39'
MUTED = '536B62'


def p(text): return {'type': 'p', 'text': text}
def sub(title): return {'type': 'sub', 'text': title}
def bullets(*items): return {'type': 'bullets', 'items': items}
def table(headers, rows, widths=None): return {'type': 'table', 'headers': headers, 'rows': rows, 'widths': widths}
def fig(name, caption, width=6.65): return {'type': 'figure', 'path': 'docs/assets/'+name, 'caption': caption, 'width': width}
def code(text): return {'type': 'code', 'text': text}


def content():
    e = json.loads((ROOT/'reports/inspection/evaluation.json').read_text())
    pages = []
    def chapter(title, *blocks): pages.append({'title': title, 'blocks': list(blocks)})
    chapter('Project purpose and contribution',
        p('MeshLens supports a human who needs to inspect a close-up photograph of woven industrial mesh. The application compares repeated patterns, highlights unusual disagreement and explains why an image was sent for review. The intended interaction is a second inspection aid, with the material and final judgment remaining with the operator.'),
        sub('The delivered system'),
        p('A static web application runs a normal-lattice texture detector in a browser worker. A trained convolutional autoencoder runs separately through ONNX Runtime Web and supplies reconstruction views. Python supports development, calibration, evaluation and offline inspection. The repository includes the Grid data, frozen artifacts, tests and operating guides.'),
        table(['User sees', 'Meaning'], [
            ['Review', 'The active detector score is above its frozen limit. Inspect the material.'],
            ['Within calibrated range', 'The score is at or below the limit. Defects may still be missed.'],
            ['Input needs review', 'Input or model conditions do not support a numeric inspection decision.']
        ], [1.8, 5.0]),
        sub('Assessment of originality'),
        p('Normal-only anomaly detection and reconstruction-based inspection are established ideas. This project does not demonstrate a new state-of-the-art research method. Its defensible contribution is the engineering: frozen data roles, deterministic preprocessing, cross-runtime agreement, controlled asynchronous execution, clear failure states and transparent limits.'),
        p('For the next project, establish a real user need, a measurable gap in existing solutions and access to representative data before committing to an application or a preferred model family. A distinctive name and an attractive interface do not supply that evidence.'),
        p('Read alongside docs/LESSONS_LEARNED.md and docs/NEXT_PROJECT_PLAYBOOK.md.'))
    chapter('Development history',
        fig('diagrams/release-timeline.png', 'Published commits and their recorded workflow outcomes. Historical failures remain visible after a later fix passes.'),
        p('The project began as an autoencoder inspection experiment. Guided onboarding and dataset explanations addressed confusion in the first interface. A specialized texture detector subsequently improved the recorded benchmark recall while retaining the AE as separate visual evidence.'),
        p('The last repair, 5f11b39, corrected a process-cleanup test race. The source and full research-data jobs passed in GitHub run 43376785899. Public repository state was checked again on 14 November 2026: six commits, six workflow runs and no repository issues were returned. This documentation update will have its own commit and CI outcome.'))
    chapter('System architecture',
        fig('diagrams/system-architecture.png', 'The browser receives static assets. Inspection pixels remain on the visitor device.'),
        p('The host serves the interface, metadata, model files, JavaScript and WebAssembly assets. It does not provide a Python inference API. The browser validates the release, decodes a local source image, runs inference and displays evidence. An offline Python interface uses the same active detector contract.'),
        p('Browser-local execution reduces hosting requirements and avoids sending inspection images to a scoring server. It transfers performance and memory constraints to the client device. Local history is convenient for export but is not a shared authenticated industrial audit store.'),
        p('Source map: web/app.js manages the workflow; web/detector.js and web/texture_worker.js manage the active worker; src/meshlens/inspection.py validates the offline bundle. Numerical implementations and input code are pinned in the freeze record.'))
    chapter('Dataset and source controls',
        fig('diagrams/data-workflow.png', 'Source-image roles remain separate through development, calibration and evaluation.'),
        p('MVTec AD Grid contains 342 original photographs and 57 defect masks. Its 264 normal training sources become 160 fit, 52 tune and 52 calibration images. The official test contains 21 normal and 57 defective images. Bent and broken groups each have 12 defects; glue, metal contamination and thread each have 11.'),
        p('All 401 raw files are tracked: the photographs, masks and two source text files. The acquisition pins a public mirror revision and archive digest. The audit verifies that mirror acquisition; it does not claim an independent byte comparison with an official download. Data retain CC BY-NC-SA 4.0 terms.'),
        p('Use data/manifest.csv, data/mask_checksums.json and data/provenance.json for exact paths, roles and digests. The source image, rather than a derived patch or crop, is the partition unit.'))
    chapter('Development and leakage controls',
        p('Fitting, method selection, threshold calibration and final measurement answer different questions. MeshLens separates them so that a strong-looking test result cannot justify changing the model or cutoff after seeing a release failure. Patches and synthetic alterations inherit the role of their source image.'),
        table(['Stage', 'Evidence and permitted use'], [
            ['Fit', '160 normal sources fit the normal reference. The historical AE also trains only from normal development data.'],
            ['Tune', '52 unchanged normal images plus 260 seeded alterations compare candidates. Alteration families are bend, gap, fibre, glue and contamination.'],
            ['Select', 'The texture comparison retains 15 variant and aggregation configurations. The selected joint configuration records 72.31% synthetic macro recall at 2/52 clean tune alerts.'],
            ['Calibrate', '52 separate normal images supply the frozen operating limit after the method and score rule are selected.'],
            ['Evaluate', 'All 78 official test sources are scored after freeze, including explicit inconclusive outcomes. Labels and masks do not fit the active detector or threshold.']
        ], [1.1, 5.7]),
        sub('What the recovered evidence can establish'),
        p('The current release recovers the previously selected detector and repeats a benchmark whose outcomes were already known. Its architecture, score and threshold were not retuned during recovery. The results establish reproducibility on that known benchmark. They do not create an unseen holdout or an independent factory cohort.'),
        p('Synthetic development recall is a selection proxy, not real-defect test accuracy. For a new target process, collect and independently label separate physical parts or sections. Keep repeated frames and crops in the same group. Preserve an untouched evaluation cohort for any subsequently changed release.'),
        p('References: reports/inspection/selection.json, reports/inspection/protocol.json, reports/texture/ and docs/FIELD_VALIDATION.md.'))
    chapter('Active detector and model responsibilities',
        fig('diagrams/model-architecture.png', 'The active score and historical reconstruction follow separate processing and decision paths.', 6.4),
        p('The active normal-lattice-v1 method uses the joint variant and no pretrained neural weights. Its 1,261-byte JSON artifact stores normal-fit and scoring parameters. Opening the page or choosing an image does not train either model. The relative detector map is neither a defect probability nor a validated segmentation boundary.'))
    chapter('Historical autoencoder experiment',
        fig('diagrams/autoencoder-architecture.png', 'The full-frame inference shape includes reflection padding and final cropping. Training uses smaller normal patches.'),
        table(['Property', 'Recorded configuration'], [
            ['Architecture', 'Convolutional denoising AE; 25,339 parameters; eight-channel bottleneck'],
            ['Training', '26 recorded epochs; selected best epoch 26; seed 43; Gaussian input noise 0.035'],
            ['Hidden and output activations', 'LeakyReLU 0.1; linear bottleneck; sigmoid reconstruction'],
            ['Historical score', 'Average the largest 1% of per-pixel mean squared RGB reconstruction errors'],
            ['Historical outcome', '11/57 defects flagged, 46 missed; 0/21 normal false alarms at its own cutoff']
        ], [2.0, 4.8]),
        p('The weak recall showed that this frozen reconstruction experiment was unsuitable as the main inspection decision. A reconstruction residual is not guaranteed to separate a defect from normal texture variation. The record does not contain controlled ablations that isolate the contribution of capacity, training, resizing and score aggregation to every miss.'),
        p('The AE remains useful for teaching reconstruction and comparing evidence. Its original model card, notebook and technical_report.pdf are retained as historical material and must not be read as the active detector specification.'))
    chapter('Preprocessing scoring and calibration',
        sub('Canonical input'),
        p('Still PNG, JPEG and WebP containers are limited to 12 MiB, 4,096 pixels per side and 16 megapixels. The active detector additionally requires at least 256 pixels on each side and an aspect ratio no greater than 1.5. Orientation is resolved, alpha is composited over white and the whole suitable image is area-resized to 256 by 256 RGB. Unsuitable framing is not silently cropped.'),
        sub('Pattern disagreement'),
        p('The algorithm converts RGB to channel-mean grayscale, normalizes local contrast and estimates independent repeat directions through autocorrelation. It compares neighboring repetitions with small alignment tolerance at radii 3 and 9. At least two usable lattice directions are required. The joint map combines median-normalized local and cell responses, then divides by the normal-fit scale.'),
        code('joint = 0.6 * local_normalized + 0.4 * cell_normalized\nresponse = joint / 0.47045176621031776\nk = ceil(256 * 256 * 0.005) = 328\nscore = round_half_up(mean(largest_k(response)), 8)\nreview = score > 1.01049636'),
        sub('Separate calibration'),
        p('The 52 normal calibration scores are sorted after method selection. Rank ceil((52 + 1) x 0.95) = 51 sets the threshold. Exact equality remains within range. The calibration-tail interpretation assumes exchangeability; it cannot guarantee the false-alarm rate after lighting, material or viewpoint changes.'),
        p('Python and JavaScript use the same canonical filter when supplied identical decoded pixels. Native browser and Pillow codec decoding remain a separate boundary. A SHA256 digest detects changed bytes; it is not an author signature.'))
    chapter('Benchmark performance',
        fig('diagrams/benchmark-results.png', 'Image-level confusion counts at the active frozen operating point.'),
        table(['Defect family', 'Flagged', 'Missed'], [[k.replace('_',' ').title(), str(v['model']['true_positive']), str(v['model']['false_negative'])] for k,v in e['per_defect'].items() if k != 'good'], [3.6,1.6,1.6]),
        p('The known glue-008 defect scores 0.97635626, below the 1.01049636 limit. Its gallery inclusion makes an actual miss visible. The gallery is selected from already evaluated cases and is not an independent validation collection.'))
    chapter('Stress tests and uncertainty',
        fig('diagrams/stress-results.png', 'Fixed-threshold results under six declared replay conditions. No new physical parts are added.'),
        p('The original-condition recall is 56/57, with Wilson 95% bounds of 90.71% to 99.69%. The normal false-alarm rate is 4/21, with bounds of 7.67% to 40.00%. These wide intervals reflect the small sample sizes. A strong AUROC of 0.9958 does not remove the cost of the chosen operating point.'),
        p('The release goal required at least 90% recall and no more than 5% normal false alarms. The original false-alarm rate exceeds that limit. Reflected translation flags every normal test image, exposing sensitivity that prevents automated line acceptance. All 468 image-condition records produced scores; none was inconclusive in this defined stress suite.'))
    chapter('Inspection lifecycle and result states',
        fig('diagrams/inference-sequence.png', 'Main active-worker sequence. The separate AE evidence path does not supply a fallback decision.'),
        table(['State', 'Expected behavior'], [
            ['Loading or unavailable', 'Explain readiness or retry. Block a numeric result from an unverified model.'],
            ['Running', 'Keep one inference in flight. New input or cancellation invalidates stale work.'],
            ['Scored', 'Display score, frozen threshold, decision, model provenance and evidence.'],
            ['Inconclusive or failed', 'Explain the cause. Do not turn failure into a normal acceptance or successful history record.']
        ], [1.8,5.0]),
        p('Camera access follows user action and browser permission. Sampling is serial and waits after each frame; it does not claim video-rate inspection. Camera stop, page hiding, ended tracks and failed inference require resource cleanup.'))
    chapter('Interface overview and first use',
        fig('screenshots/overview-desktop.jpg', 'Actual public MeshLens desktop interface captured on 14 November 2026. The hero explicitly labels its historical AE illustration.'),
        p('A new visitor should be able to explain the task before trying the model. The revised page introduces the material, identifies local inference, shows an original/rebuilt/difference example and provides a direct route to inspection. The project-scope statement places measured limitations before the main task.'),
        bullets('Open the public demo and wait for Detector ready.', 'Try a guided benchmark image and reveal its label after inference.', 'Compare all four evidence views and read the result against the fixed limit.', 'Export a record or bring a suitable new photograph.'),
        p('The first interface looked empty and did not explain the dataset or the next action. This was owner feedback, not a quantified recruited-user study. The revised onboarding addresses that feedback, while comprehension still benefits from testing with first-time users.'))
    chapter('Inspection workspace and evidence views',
        fig('screenshots/inspection-desktop.jpg', 'Actual completed inspection of a bent-wire benchmark example. The relative detector response and review state are visible.'),
        table(['View', 'Interpretation'], [
            ['Original', 'The active detector input after its canonical RGB area resize.'],
            ['Detector map', 'Relative disagreement used by the active texture method. Color is not a defect probability.'],
            ['Reconstruction', 'The historical AE rebuilds a separate 256 by 256 input.'],
            ['AE error map', 'Reconstruction residual of that separate baseline, not the active score.']
        ], [1.7,5.1]),
        p('Known benchmark labels appear after inference and do not enter model feeds. History holds up to 100 records in the browser, without saving image pixels. JSON and CSV exports preserve numerical provenance; CSV escaping also addresses untrusted filenames.'))
    chapter('Dataset and measured results screens',
        fig('screenshots/dataset-desktop.jpg', 'Actual dataset view explains the four source roles and the meaning of the masks.', 5.7),
        fig('screenshots/results-desktop.jpg', 'Actual results view displays detected defects, missed defects, correct normal decisions and false alarms.', 5.7),
        p('Screenshots document the current desktop workflow. They are not independent accuracy measurements or evidence that every device and assistive technology was tested.'))
    chapter('Responsive design and accessibility scope',
        fig('diagrams/responsive-layout.png', 'Documented responsive rules illustrated schematically. This figure is deliberately labeled as a schematic, not a phone capture.'),
        table(['CSS condition', 'Declared layout behavior'], [
            ['Up to 1100 px', 'Tighter spacing, compact toolbars and a narrower source column.'],
            ['Up to 820 px', 'Hero, inspection, dataset, results and method grids stack.'],
            ['Up to 600 px', 'Navigation wraps, controls compact, score rows reflow and tables scroll locally.'],
            ['User preferences', 'Dark appearance, reduced motion, reduced transparency and forced-colors rules.']
        ], [1.7,5.1]),
        p('The prior accessibility record includes contrast, keyboard and automated layout checks on an earlier UI revision. The later four-tab detector workflow needs its own complete review. The 44-pixel core target is a design target; WCAG 2.1 target-size criterion 2.5.5 is AAA. Fresh desktop captures are included here; a fresh mobile capture, physical phones, screen readers and camera hardware were not tested for this report.'))
    chapter('Offline interface and operating commands',
        p('The active offline route needs Python 3.12 with NumPy and Pillow. It is separate from the heavier historical training environment. A scored result contains a score and a strict-threshold decision. An inconclusive result contains an actionable reason; a missing model must not silently fall back to the AE.'),
        code('py -3.12 -m venv .venv-inspection\n.\\.venv-inspection\\Scripts\\python.exe -m pip install -r requirements-inspection.lock\n.\\.venv-inspection\\Scripts\\python.exe -m pip install --no-deps -e .\n.\\.venv-inspection\\Scripts\\python.exe scripts/inspect_image.py "C:\\mesh.png" --evidence inspection-output/run-1'),
        table(['Interface', 'Contract'], [
            ['Result status', 'scored or inconclusive; inconclusive inputs have no acceptance decision.'],
            ['Scored fields', 'score, threshold, is_anomaly, decision, model_version and provenance digests.'],
            ['Evidence directory', 'New directory containing result.json, canonical-input.png and relative-anomaly-map.png when scored.'],
            ['CLI exit', '0 for scored; 1 for inconclusive; 2 for invalid arguments or output write failure.'],
            ['Output protection', 'Existing outputs, source/data/artifact paths and input overwrite are rejected.']
        ], [1.6,5.2]),
        p('Use a new evidence directory for each inspection. If port 4173 is occupied, use the documented programmatic startServer({port:0}) command and open its printed address. The server entrypoint does not parse a --port flag. Full command details and Linux equivalents are in PROJECT_DOCUMENTATION.md and RUNBOOK.md.'))
    chapter('Deployment and release controls',
        fig('diagrams/deployment-architecture.png', 'Source verification and deployment must both be assessed against the same commit.'),
        table(['Reference release evidence', 'Observed status'], [
            ['Source commit', '5f11b39fbd989e2b4f6359dc75cda062daf8b9ba'],
            ['GitHub run 43376785899', 'Source/frozen-model and full research-data jobs passed.'],
            ['Vercel commit status', 'Success for the reference commit.'],
            ['Public application', 'https://mesh-lens.vercel.app/']
        ], [2.3,4.5]),
        p('These statuses were rechecked on 14 November 2026. A subsequent documentation commit needs a new run. Validate model readiness, the displayed version and a real inspection after deployment; a successfully uploaded site alone does not establish data integrity or target-line performance.'))
    chapter('Verification and security evidence',
        p('After the CI repair, local verification passed 215 Python tests and 143 browser tests. The timeout integration passed 12 consecutive repetitions. The corresponding hosted source and full-data jobs passed. The committed verification.json is an earlier 211-test snapshot; its date and source digests are retained rather than relabeled as the later CI artifact.'),
        table(['Evidence', 'Scope and limitation'], [
            ['Runtime parity', '78 official inputs and 18 gallery replays agree on canonical pixels, rounded scores and decisions between Python and shipped JavaScript under Node. Native decoder behavior remains separate.'],
            ['Software regressions', 'Input bounds, artifact tampering, tensor contracts, stale work, worker/camera cleanup, replay/history recovery, build replacement and local server behavior.'],
            ['13 November dependency review', 'Browser packages, two active Python dependencies and 61 development additions reported no known findings in those queries.'],
            ['Training query limitation', 'The 36-package training scope skipped Torch 2.14.1+cpu because that distribution could not be matched by the query. It is not counted as audited.'],
            ['31 October historical scan', 'The original training environment had five recorded Torch advisory findings. That is a different dated environment.']
        ], [1.8,5.0]),
        p('The documentation work does not introduce a new penetration test or establish the absence of unknown vulnerabilities. Report audit date, packages, skipped components and unresolved findings. SHA256 release consistency checks complement bounded inputs and safe output handling but are not a complete supply-chain trust system.'),
        p('References: reports/inspection/security-review.json, reports/security-audit-summary.json, tests/, .github/workflows/ci.yml and the model runtime-parity reports.'))
    chapter('Delivery and environment incidents',
        p('These incidents affected the ability to receive, run and understand the project. Their corrective actions should become default delivery checks for future work.'),
        table(['Observed problem', 'Established cause or scope', 'Corrective action'], [
            ['Shared ZIP failed to download', 'Recipient could not use the selected sharing route; the backend cause was not established.', 'Supply a directly downloadable artifact and verify the recipient route.'],
            ['Archive destination failed', 'The proposed Documents destination was unavailable; a later command entered a nonexistent path.', 'Use the already extracted folder and inspect its real files before proposing commands.'],
            ['Updater rejected .git', 'The selected path was the update package or outer folder, rather than the existing repository.', 'Validate project root, repository, remote and branch before mutation.'],
            ['Large Git transfer', 'Data/model history produced a transfer around 168 MiB; bandwidth also affected elapsed time.', 'Keep lightweight update packages and evaluate external acquisition or release assets early.'],
            ['Port 4173 occupied', 'Another process owned the default port.', 'Choose a documented free port; do not stop an unidentified process.'],
            ['Ownership confusion', 'Author metadata, active login, pushing credentials and historical contributor attribution are separate.', 'Check the authenticated account, expected remote and author. Preserve history and third-party rights.']
        ], [1.45,2.65,2.7]),
        p('A delivery is only reviewable when another person can download it, locate the correct folder, run it and interpret the first result. A compressed archive and a list of assumed paths are insufficient. The full incident record is in LESSONS_LEARNED.md.'))
    chapter('Model UX and verification incidents',
        table(['Observed problem', 'Correction or remaining work'], [
            ['AE flagged only 11 of 57 defects', 'A specialized texture detector became the active decision. Keep the weak baseline and its failure counts visible.'],
            ['False alarms and shift sensitivity', 'The active detector still flags 4/21 normal originals and 21/21 shifted normals. Qualification remains open.'],
            ['Unclear first screen', 'Added guided examples, source roles, new-photo instructions, visible limits and explanation views. User comprehension still requires direct observation.'],
            ['Line-ending hash mismatch', 'Preserve frozen CSV bytes and force ordinary text to LF in .gitattributes. Test a fresh cross-platform checkout.'],
            ['Interrupted or stale verification evidence', 'Write a current failed/pending report before execution, validate JUnit and replace reports atomically.'],
            ['Hosting green while CI red', 'Check independent statuses for the exact commit; retrieve the failed assertion before changing code.'],
            ['Process cleanup race', 'Replace check-then-read existence assertions with bounded Linux-state polling. Accept disappearance while still rejecting a running child.']
        ], [2.0,4.8]),
        sub('The confirmed CI failure'),
        p('Run 43371910619 had 210 passing Python tests, one failing timeout regression and 143 passing browser tests. Linux removed a stopped child between os.kill(pid, 0) and stat.exists(). The missing /proc entry represented completed cleanup, but the test rejected it.'),
        p('The repair handles both FileNotFoundError and ProcessLookupError, recognizes stopped states and allows a bounded termination interval. Four deterministic regressions preserve these cases. Node action-runtime and Ubuntu-image notices were maintenance warnings; the detailed failure log established the actual cause.'),
        p('The correction fixes that CI race. It does not improve model accuracy or qualify the inspection process.'))
    chapter('Operational risks and field qualification',
        p('The strongest remaining risk is an appealing demonstration being interpreted as a qualified inspection system. The original benchmark missed one defect, produced normal false alarms above the declared limit and failed the defined translation stress. A score inside the normal reference is not a defect-free certificate.'),
        table(['Risk', 'Required evidence or control'], [
            ['Material and capture shift', 'Collect representative new parts across the intended material, optics, lighting, alignment, focus and nuisance conditions.'],
            ['Dependent observations', 'Group repeated frames, views and crops by physical part or section; count independent parts explicitly.'],
            ['Error cost and review workload', 'Agree the acceptable miss rate, normal review demand, coverage, latency and operator burden before evaluation.'],
            ['Statistical uncertainty', 'Report support counts and confidence bounds; do not let high AUROC conceal unacceptable fixed-threshold errors.'],
            ['Operational ownership', 'Specify review responsibility, version provenance, escalation, monitoring, rollback and requalification triggers.'],
            ['Rights and data use', 'Confirm permission and commercial data rights. The MIT code license does not override benchmark restrictions.']
        ], [1.8,5.0]),
        p('The field workflow in docs/FIELD_VALIDATION.md records a cohort, independently checked labels, grouping, frozen model/threshold, failures and acceptance limits. It is a procedure to be performed, not evidence that a factory study has been completed.'),
        p('Any changed architecture, cutoff or capture process needs an appropriate new evaluation. Prefer a restricted, defensible scope to an unsupported claim of universal or production-grade accuracy.'))
    chapter('Staggered plan for the next project',
        p('Use the following stages to prevent a conventional premise or weak model from accumulating a large delivery effort around it. Parallel work is useful after contracts and evidence boundaries are clear. Each stage has a decision to continue, narrow the scope or stop.'),
        table(['Stage', 'Evidence required to proceed'], [
            ['1 Problem discovery', 'A real intended user, a repeated task, an observed baseline and a measurable potential benefit.'],
            ['2 Novelty and feasibility', 'Comparison with existing solutions, a specific gap and a feasible data/deployment path.'],
            ['3 Data and acceptance', 'Lawful representative data, credible labels, entity grouping, independent roles and predeclared operating criteria.'],
            ['4 Baselines and experiments', 'A reproducible simple baseline and justified alternatives that improve a useful task metric.'],
            ['5 Frozen evaluation', 'A pinned candidate and untouched holdout with error counts, coverage, uncertainty and nuisance-condition results.'],
            ['6 Product workflow', 'Users can complete and explain the task; error, accessibility and representative-device checks are recorded.'],
            ['7 Reliable delivery', 'Fresh-install reproduction, passing required CI, dated security findings and observed deployment for the same commit.'],
            ['8 Handoff and operation', 'Complete documentation, ownership, monitoring, rollback and conditions requiring new evaluation.']
        ], [1.8,5.0]),
        p('Estimate value in the user\'s units: review time, rejected clean parts, missed defects, latency and operating cost. Do not invent throughput or savings. Compare the added complexity against the baseline workflow.'),
        p('The next project topic has deliberately not been selected in this report. Use NEXT_PROJECT_PLAYBOOK.md to compare candidate problems before development begins.'))
    chapter('Reproduction and documentation maintenance',
        sub('Run the delivered application'),
        code('git clone https://github.com/kumarwaibhav/MeshLens.git\ncd MeshLens\nnpm ci\nnpm test\nnpm run build\nnpm run serve'),
        p('Node.js 22 or newer is required. Use npm.cmd on Windows if its PowerShell shim is blocked. The verified build uses shipped artifacts and does not retrain the detector or download raw data. Python 3.12 is required for the separately documented inference and development workflows.'),
        sub('Regenerate documentation assets'),
        code('python -m pip install -r docs/report/requirements-docs.lock\nnpm ci --prefix docs/report\npython docs/report/build_assets.py\nnode docs/report/render_assets.mjs\npython docs/report/build_report.py --pdf'),
        p('The editable SVG figures derive benchmark values from the frozen evaluation. PNGs support Word/PDF rendering. The report builder writes a Word edition and PROJECT_REPORT.md; optional PDF conversion needs LibreOffice on PATH. Inspect rendered pages after edits. Keep screenshots as dated observations, and capture the UI again after material interface changes.'),
        p('Regenerate models in a separate reproduction copy using the manual. Fitting and export can overwrite artifacts; changing evidence requires a new release record and suitable evaluation. Preserve hashes and filenames rather than editing expected values to make checks pass.'),
        p('A documentation-only update should leave numerical code, model artifacts and the frozen evaluation unchanged. Its new GitHub Actions run still needs to complete before publication is declared verified.'))
    chapter('Evidence index authorship and licenses',
        table(['Evidence', 'Primary location'], [
            ['Reference source and CI', 'Commit 5f11b39; GitHub Actions run 43376785899'],
            ['Active model and threshold', 'artifacts/inspection/detector.json and detector-model.json'],
            ['Freeze and protocol', 'reports/inspection/frozen_configuration.json and protocol.json'],
            ['Raw and packaged evaluation', 'reports/inspection/independent_evaluation.json and evaluation.json'],
            ['Dataset provenance', 'data/manifest.csv, mask_checksums.json and provenance.json'],
            ['Current dated dependency review', 'reports/inspection/security-review.json and linked scanner files'],
            ['Historical UI review', 'docs/design/ and reports/ui-redesign-browser-scans.json'],
            ['Fresh desktop UI captures', 'docs/assets/screenshots/; captured 14 November 2026'],
            ['Editable diagrams and report', 'docs/assets/diagrams/ and docs/report/'],
            ['Technical and learning guides', 'PROJECT_DOCUMENTATION.md, LESSONS_LEARNED.md and NEXT_PROJECT_PLAYBOOK.md']
        ], [2.25,4.55]),
        p('Original MeshLens code and documentation are authored by Kumar Waibhav Akshat under the repository MIT license. MVTec Software GmbH and the original authors retain rights in the photographs, masks and dataset-derived material under CC BY-NC-SA 4.0. Preserve the dataset license and THIRD_PARTY_NOTICES.md when distributing the project.'),
        p('Primary external references are the official MVTec AD dataset page, its linked license, the repository source and the successful hosted CI run. This report separates recorded results, interpretation and recommended future work. It makes no independent factory-qualification, universal accessibility or vulnerability-free guarantee.'),
        p('Repository: https://github.com/kumarwaibhav/MeshLens\nDemo: https://mesh-lens.vercel.app/\nDataset: https://www.mvtec.com/research-teaching/datasets/mvtec-ad\nLicense: https://creativecommons.org/licenses/by-nc-sa/4.0/\nCI: https://github.com/kumarwaibhav/MeshLens/actions/runs/43376785899'))
    return pages


def shade(cell, fill):
    props = cell._tc.get_or_add_tcPr()
    el = OxmlElement('w:shd'); el.set(qn('w:fill'),fill);props.append(el)


def write_table(doc, block):
    t = doc.add_table(rows=1, cols=len(block['headers']))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    widths = block.get('widths') or [6.8/len(block['headers'])]*len(block['headers'])
    for col,w in zip(t.columns,widths): col.width = Inches(w)
    props = t._tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for side in ['top','left','bottom','right','insideH','insideV']:
        edge=OxmlElement('w:'+side);edge.set(qn('w:val'),'single');edge.set(qn('w:sz'),'4');edge.set(qn('w:color'),'D9D9D9');borders.append(edge)
    props.append(borders)
    repeat=OxmlElement('w:tblHeader');t.rows[0]._tr.get_or_add_trPr().append(repeat)
    for i,text in enumerate(block['headers']):t.rows[0].cells[i].text=text
    for row in block['rows']:
        cells=t.add_row().cells
        for cell,text in zip(cells,row):cell.text=str(text)
    for r,row in enumerate(t.rows):
        for c,cell in enumerate(row.cells):
            cell.width=Inches(widths[c]);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            margins=OxmlElement('w:tcMar')
            for side in ['top','left','bottom','right']:
                v=OxmlElement('w:'+side);v.set(qn('w:w'),'95');v.set(qn('w:type'),'dxa');margins.append(v)
            cell._tc.get_or_add_tcPr().append(margins)
            shade(cell, INK if r==0 else ('F1F5F0' if r%2==0 else 'FFFFFF'))
            for para in cell.paragraphs:
                para.paragraph_format.space_after=Pt(1)
                para.paragraph_format.line_spacing=1.06
                for run in para.runs:
                    run.font.size=Pt(9.3);run.bold=r==0
                    run.font.color.rgb=RGBColor.from_string('FFFFFF' if r==0 else '182D28')
    doc.add_paragraph().paragraph_format.space_after=Pt(0)


def add_figure(doc, block, number):
    para=doc.add_paragraph();para.alignment=WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_after=Pt(3)
    run=para.add_run();run.add_picture(str(ROOT/block['path']),width=Inches(block['width']))
    props=run._r.xpath('.//wp:docPr')
    if props:props[0].set('descr',block['caption'])
    para.paragraph_format.keep_with_next=True
    caption=doc.add_paragraph(f'Figure {number}  {block["caption"]}',style='Caption')
    caption.paragraph_format.space_after=Pt(9)


def bookmark(para, identifier):
    start=OxmlElement('w:bookmarkStart');start.set(qn('w:id'),str(identifier));start.set(qn('w:name'),'chapter_'+str(identifier))
    end=OxmlElement('w:bookmarkEnd');end.set(qn('w:id'),str(identifier));para._p.insert(0,start);para._p.append(end)


def build_docx(pages):
    doc=Document();sec=doc.sections[0]
    sec.page_width=Inches(8.2677);sec.page_height=Inches(11.6929)
    sec.top_margin=sec.bottom_margin=Inches(.65);sec.left_margin=sec.right_margin=Inches(.70)
    sec.header_distance=sec.footer_distance=Inches(.28)
    sec.different_first_page_header_footer=True
    for style in doc.styles:
        for border in list(style.element.iter(qn('w:pBdr'))):
            border.getparent().remove(border)
    for name in ['Normal','Title','Subtitle','Heading 1','Heading 2','Heading 3','Header','Footer','Caption']:
        style=doc.styles[name];style.font.name='Arial';style.font.color.rgb=RGBColor(0,0,0)
    normal=doc.styles['Normal'];normal.font.size=Pt(10.5)
    normal.paragraph_format.line_spacing=1.12;normal.paragraph_format.space_after=Pt(7)
    doc.styles['Title'].font.size=Pt(32);doc.styles['Title'].font.bold=True
    doc.styles['Heading 1'].font.size=Pt(21);doc.styles['Heading 1'].paragraph_format.space_after=Pt(12)
    doc.styles['Heading 2'].font.size=Pt(12);doc.styles['Heading 2'].paragraph_format.space_before=Pt(10)
    doc.styles['Heading 2'].paragraph_format.space_after=Pt(5)
    doc.styles['Caption'].font.size=Pt(9);doc.styles['Caption'].font.italic=False
    doc.styles['Caption'].paragraph_format.line_spacing=1.05
    header=sec.header.paragraphs[0];header.text=''
    footer=sec.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.RIGHT
    field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
    for run in footer.runs:run.font.size=Pt(8)
    doc.core_properties.author=OWNER;doc.core_properties.title='MeshLens Project Report'
    doc.core_properties.subject='Technical documentation architecture evaluation and development lessons'
    doc.core_properties.keywords='MeshLens, anomaly detection, MVTec Grid, technical report'
    doc.add_paragraph('MeshLens Project Report',style='Title')
    doc.add_paragraph('Technical documentation and development review',style='Subtitle')
    doc.add_paragraph(OWNER+'\n'+DATE+'\nReference source release '+REFERENCE[:7])
    add_figure(doc,fig('diagrams/brand-banner.png','Original MeshLens documentation branding. The technical figures are editable SVGs.',6.8),1)
    doc.add_heading('Purpose and assessment',level=2)
    doc.add_paragraph('This report documents the delivered MeshLens system, its data and model boundaries, measured results, user workflow, development failures and the lessons to carry into the next project. It is intended for a technical reviewer, project owner or future developer who needs to understand and reproduce the work.')
    doc.add_paragraph('MeshLens is a useful browser-based engineering prototype. The active detector reproduces 56 of 57 defective-image alerts, but flags 4 of 21 normal images and fails the declared false-alarm goal. Its contribution is reproducible integration and visible evidence around a conventional anomaly-detection problem. Independent production qualification remains outstanding.')
    write_table(doc,table(['Reference result','Measured outcome'],[['Defects flagged','56/57; one miss'],['Normal false alarms','4/21; 19.05%'],['Deployment scope','Research and human review prototype']],[2.25,4.55]))
    doc.add_page_break()
    doc.add_heading('How to use this report',level=1)
    doc.add_paragraph('Read the purpose, architecture and measured limits first. Use the technical manual for exact commands and contracts, the retrospective for incident details, and the next-project playbook before choosing a new problem. Chapter numbers organize the report; the footer gives physical page numbers.')
    write_table(doc,table(['Chapters','Subject'],[['01 to 04','Purpose, development history, architecture and data'],['05 to 08','Development controls, active detector, historical AE and calibration'],['09 to 11','Benchmark results, stress behavior and inspection lifecycle'],['12 to 15','Current UI captures, evidence views and responsive accessibility scope'],['16 to 18','Interfaces, deployment, verification and security evidence'],['19 to 21','Delivery incidents, model and CI incidents, operational qualification'],['22 to 24','Next-project stages, reproduction, evidence and licensing']],[1.6,5.2]))
    doc.add_heading('Document editions',level=2)
    doc.add_paragraph('This illustrated report is available as PDF, editable Word and repository Markdown. PROJECT_DOCUMENTATION.md is the longer implementation reference. LESSONS_LEARNED.md records observed incidents and their resolution. NEXT_PROJECT_PLAYBOOK.md defines the evidence required at each stage of future work.')
    doc.add_heading('Evidence boundaries',level=2)
    doc.add_paragraph('Benchmark records, dated scanner outputs and prior UI audits retain their original dates and scope. The fresh screenshots document a desktop browser session on 14 November 2026. Diagrams labeled schematic describe architecture or layout rather than new measurements. New device, camera or factory claims require separate evidence.')
    doc.add_heading('Reference identities',level=2)
    doc.add_paragraph('Source: '+REFERENCE+'\nActive detector: meshlens-inspect-7665cb57f023\nThreshold: 1.01049636\nSuccessful reference CI run: 43376785899')
    count=1
    for index,page in enumerate(pages,1):
        doc.add_page_break();heading=doc.add_heading(f'{index:02d} {page["title"]}',level=1);bookmark(heading,index)
        for block in page['blocks']:
            kind=block['type']
            if kind=='p':doc.add_paragraph(block['text'])
            elif kind=='sub':doc.add_heading(block['text'],level=2)
            elif kind=='bullets':
                for value in block['items']:doc.add_paragraph(value,style='List Bullet')
            elif kind=='table':write_table(doc,block)
            elif kind=='figure':count+=1;add_figure(doc,block,count)
            elif kind=='code':
                para=doc.add_paragraph();para.paragraph_format.space_after=Pt(9);para.paragraph_format.line_spacing=1.07
                run=para.add_run(block['text']);run.font.name='DejaVu Sans Mono';run.font.size=Pt(8.2)
    for border in list(doc.element.iter(qn('w:pBdr'))):
        border.getparent().remove(border)
    path=HERE/'MeshLens_Project_Report.docx';doc.save(path)
    return path


def build_markdown(pages):
    lines=['# MeshLens Project Report','',f'**Author:** {OWNER}','',f'**Date:** {DATE}','',f'**Reference source:** `{REFERENCE}`','',
           '[PDF edition](report/MeshLens_Project_Report.pdf) · [Editable Word edition](report/MeshLens_Project_Report.docx) · [Technical manual](PROJECT_DOCUMENTATION.md) · [Documentation index](README.md)','',
           'MeshLens is a browser-based engineering prototype for human review of woven mesh. Its active detector reproduces 56/57 defect alerts with 4/21 normal false alarms. The false-alarm goal remains unmet and independent factory qualification is outstanding.','']
    for i,page in enumerate(pages,1):
        lines += [f'## {i:02d} {page["title"]}','']
        for block in page['blocks']:
            kind=block['type']
            if kind=='p':lines += [block['text'],'']
            elif kind=='sub':lines += ['### '+block['text'],'']
            elif kind=='bullets':lines += ['- '+str(x)for x in block['items']]+['']
            elif kind=='code':lines += ['```text',block['text'],'```','']
            elif kind=='figure':
                rel=block['path'].removeprefix('docs/')
                lines += [f'![{block["caption"]}]({rel})','',block['caption'],'']
            elif kind=='table':
                clean=lambda x:str(x).replace('|','\\|').replace('\n','<br>')
                lines += ['| '+' | '.join(map(clean,block['headers']))+' |','|'+'|'.join(['---']*len(block['headers']))+'|']
                lines += ['| '+' | '.join(map(clean,row))+' |'for row in block['rows']]+['']
    (ROOT/'docs/PROJECT_REPORT.md').write_text('\n'.join(lines).rstrip()+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--pdf',action='store_true');args=parser.parse_args()
    pages=content();path=build_docx(pages);build_markdown(pages)
    if args.pdf:
        office=shutil.which('soffice') or shutil.which('libreoffice')
        if not office:raise SystemExit('Word and Markdown created. Install LibreOffice and add soffice to PATH for PDF conversion.')
        with tempfile.TemporaryDirectory(prefix='meshlens-report-office-') as profile:
            subprocess.run([office,'-env:UserInstallation='+Path(profile).as_uri(),'--headless','--convert-to','pdf','--outdir',str(HERE),str(path)],check=True,timeout=120)
        if not path.with_suffix('.pdf').is_file():raise RuntimeError('LibreOffice did not produce the expected PDF')
    print(f'Built {len(pages)} chapters plus cover and reading guide: {path}')


if __name__ == '__main__':main()
