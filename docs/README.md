# MeshLens Documentation

This documentation explains the delivered inspection system, its development history, and the evidence required before a target-line deployment. The active normal-lattice detector and the historical reconstruction autoencoder have separate roles and measured results. The current release supports research and human review; its false alarms and view sensitivity remain unresolved qualification limits.

[Return to the project](../README.md) · [Open the demo](https://mesh-lens.vercel.app)

## Start here

| Document | Use it to |
|---|---|
| [Project report PDF](report/MeshLens_Project_Report.pdf) | Review the illustrated architecture, dataset, results, UI, development stages, and project assessment |
| [Editable Word report](report/MeshLens_Project_Report.docx) | Adapt the report for academic review or a technical handoff |
| [Complete technical documentation](PROJECT_DOCUMENTATION.md) | Understand implementation contracts, algorithms, commands, verification, and operation |
| [Lessons learned](LESSONS_LEARNED.md) | Trace observed problems, causes, corrective actions, and remaining risks |
| [Next project playbook](NEXT_PROJECT_PLAYBOOK.md) | Apply staged problem selection, evidence, design, and release criteria to the next project |

The report and manual reference source release `5f11b39`. A later documentation commit has its own CI result. Treat prior test reports, screenshots, dependency scans, and design audits as dated evidence with a defined scope.

## Architecture and visual evidence

The diagrams are editable SVG assets, with PNG renderings alongside them for document compatibility. Current UI captures show the actual desktop application. They do not establish physical-camera, mobile-device, or complete accessibility certification.

| Visual | Subject |
|---|---|
| [System architecture](assets/diagrams/system-architecture.svg) | Development, static delivery, and browser-local processing boundaries |
| [Data workflow](assets/diagrams/data-workflow.svg) | Source-image roles, candidate selection, calibration, freeze, and evaluation |
| [Model architecture](assets/diagrams/model-architecture.svg) | Active texture decisions and separate AE reconstruction evidence |
| [Autoencoder architecture](assets/diagrams/autoencoder-architecture.svg) | The retained historical neural reconstruction model |
| [Inference sequence](assets/diagrams/inference-sequence.svg) | Input checks, worker inference, result state, and evidence |
| [Deployment architecture](assets/diagrams/deployment-architecture.svg) | GitHub verification, build artifacts, Vercel, and browser execution |
| [Benchmark results](assets/diagrams/benchmark-results.svg) | Measured original-condition results with their support |
| [Stress results](assets/diagrams/stress-results.svg) | Declared perturbations and observed sensitivity |
| [Application overview](assets/screenshots/overview-desktop.jpg) | Project introduction and entry workflow |
| [Inspection workspace](assets/screenshots/inspection-desktop.jpg) | Image choice, evidence, and decision controls |
| [Results page](assets/screenshots/results-desktop.jpg) | Benchmark performance and visible limitations |

## Model and dataset references

- [Active model card](MODEL_CARD.md) defines normal-lattice scoring, calibration, supported inputs, benchmark results, and limits.
- [Historical AE model card](AUTOENCODER_MODEL_CARD.md) preserves the original reconstruction experiment and its separate threshold.
- [Dataset card](DATASET_CARD.md) records source counts, partition protocol, acquisition hashes, and data rights.
- [Architecture notes](ARCHITECTURE.md) provide a compact implementation overview.
- [Frozen evaluation](../reports/inspection/independent_evaluation.json), [packaged results](../reports/inspection/evaluation.json), and [freeze record](../reports/inspection/frozen_configuration.json) provide machine-readable evidence.

## Run and maintain

- [Workflow guide](RUNBOOK.md): local build, offline inference, dataset checks, detector reproduction, historical training, and troubleshooting.
- [Deployment guide](deployment.md): static hosting settings, version verification, and deployment smoke checks.
- [Windows GitHub guide](github-windows.md): repository selection, commit identity, and authenticated push workflow.
- [Field validation guide](FIELD_VALIDATION.md): independent physical-part collection, frozen evidence, statistical bounds, and acceptance criteria.

The full development environment differs from the two-package active Python inference environment. Use the lock and interpreter specified for the chosen task. Regenerate models and evaluation evidence in a separate reproduction copy, keeping the delivered release intact.

## UI design and accessibility history

The prior [design critique](design/DESIGN_CRITIQUE.md), [accessibility review](design/ACCESSIBILITY_REVIEW.md), [design handoff](design/DESIGN_HANDOFF.md), [design system](design/DESIGN_SYSTEM.md), and [research synthesis](design/RESEARCH_SYNTHESIS.md) document an earlier UI revision and the feedback that drove its changes. Current desktop screenshots are a separate observation. Repeat relevant keyboard, zoom, assistive-technology, native-device, and camera checks after interface changes.

## Rights

Original MeshLens code and documentation are [MIT licensed](../LICENSE). MVTec AD photographs, masks, benchmark examples, and dataset-derived assets retain CC BY-NC-SA 4.0 terms. Preserve the [third-party notices](../THIRD_PARTY_NOTICES.md); a code license does not transfer commercial dataset rights.
