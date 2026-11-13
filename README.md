![MeshLens: learn the pattern, reveal the exception](docs/banner.svg)

# MeshLens

**A visual inspection lab for woven industrial mesh, with local inference and evidence you can inspect.**

Give MeshLens a close-up of mesh. It looks for regions that disagree with the repeating grid,
returns **Review** or **Within calibrated range**, and shows the regions that influenced the
score. **Input needs review** means the photo cannot support a numeric inspection decision.
Use the result as a second check for a human inspector. The benchmark does not qualify
automatic material acceptance or rejection on a factory line.

The active detector compares neighboring pattern repetitions. A separately trained
**autoencoder** reconstructs the image for visual comparison. Its reconstruction/error views
explain the original experiment; the active texture detector supplies the review decision.

[Public demo](https://mesh-lens.vercel.app) · [Model card](docs/MODEL_CARD.md) ·
[Run locally](docs/RUNBOOK.md) · [Deploy](docs/deployment.md) ·
[Dataset](docs/DATASET_CARD.md) · [Windows GitHub steps](docs/github-windows.md)

Check the model version displayed in a deployed demo against the release metadata.
A source update, private preview and public Vercel deployment can contain different versions.

## Try it in a minute

1. Open Inspection and wait for the models to become ready.
2. Try the guided images. Read each known label and the actual result after inference.
3. Compare **Original**, **Detector map**, **Reconstruction** and **AE error map**.
4. Read the score alongside its threshold. A low score can still miss a real defect.
5. Download a result or replay more examples and export the local history.

The 18 bundled images and downloadable example kit are already-evaluated MVTec Grid benchmark
replays. Their labels help you understand behavior. Uploading or replaying them supplies no
new independent accuracy evidence. The detector map shows relative pattern disagreement;
it is not a defect probability or a validated segmentation mask.

## Where to get a new image

For a new inspection, photograph similar woven mesh yourself or capture a frame from your
inspection camera. Use a sharp close-up, comparable mesh scale and stable lighting, with
both sides at least **256 pixels** and a longest-to-shortest-side ratio no greater than **1.5**.
Still PNG/JPEG/WebP files may be up to 12 MiB, 4096 pixels per side and 16 megapixels.
The whole suitable image is resized to 256×256; no automatic crop repairs an unsuitable view.

For an independent evaluation, collect separate physical parts or mesh sections from the
intended process, including normal material and relevant defects. Have their labels checked
independently of model scores. Keep repeated frames, crops and photos of the same part in
one group. Follow the [field validation workflow](docs/FIELD_VALIDATION.md) to record the
cohort, model/threshold, failures, confidence bounds and operator acceptance limits.

Images stay on your device during inference. Camera mode begins after user action and
browser permission, then samples one frame at a time. Browser-local history can be cleared
and is specific to that browser. It does not provide a shared, authenticated industrial audit log.

## How the project works

| Step | What happens |
|---|---|
| Prepare | Decode the image, resolve orientation, composite alpha over white and apply the versioned integer area resize. |
| Find the pattern | Estimate mesh repetition and compare small regions with neighboring repeats, allowing minor alignment changes. |
| Score | Combine local/cell disagreement, normalize by the normal-fit reference and average the largest 0.5% of responses. |
| Decide | Request review when the rounded score is strictly above the separately calibrated threshold. |
| Explain | Show the detector map and separate AE reconstruction/error evidence. |

The selected method is a normal-fitted texture detector running in JavaScript. Its Python
path needs NumPy and Pillow. The original autoencoder was trained from random initialization
and runs separately through ONNX Runtime Web. Neither uploading a photo nor opening the app
trains a model. The active recovered release is `meshlens-inspect-7665cb57f023`, with threshold **1.01049636**.
Its hashes are recorded in `artifacts/inspection/detector.json` and
`reports/inspection/frozen_configuration.json`.

## Measured results

<!-- MESHLENS_INSPECTION_RESULTS_START -->
**Verified recovery results:** the restored frozen release reproduced the previously recorded
counts across all six conditions. These are known-benchmark reproducibility results.

| Frozen pipeline | Defects flagged | Missed | Normal images flagged | AUROC |
|---|---:|---:|---:|---:|
| Active normal-lattice detector | 56/57 (98.25%) | 1 | 4/21 (19.05%) | 0.9958 |
| Historical reconstruction AE | 11/57 (19.30%) | 46 | 0/21 (0.00%) | 0.7594 |

All 78 original benchmark images produced scores. The detector's Wilson 95% interval
is **90.71%–99.69%** for defect recall and **7.67%–40.00%** for the normal false-alarm rate.
These small-sample intervals do not establish factory accuracy.

**The declared release goal was not met.** Recall exceeded 90%, but the observed 19.05%
normal false-alarm rate exceeded the 5% limit. A translated-view stress flagged all 21 normal
images; brighter images flagged 6/21. The threshold remained frozen. These results support
research and human review while false alarms and view sensitivity require further work.

Try the [known missed glue image](data/raw/grid/test/glue/008.png) from the complete dataset:
its reproduced score is 0.97635626, below the 1.01049636 threshold despite a real defect. It is
an already-measured failure example. Full per-defect and six-condition results are in the
[model card](docs/MODEL_CARD.md) and [evaluation](reports/inspection/evaluation.json).
<!-- MESHLENS_INSPECTION_RESULTS_END -->

This release restores the previously selected algorithm and reproduces its frozen evaluation.
The official benchmark outcomes were already known before this recovery. Architecture and
cutoff are unchanged and were not retuned. The original detector selection excluded these test
images from fitting, candidate selection and calibration. This recovery is reproducibility
evidence; a new representative factory study is still required.

The historical AE's [model card](docs/AUTOENCODER_MODEL_CARD.md),
[technical PDF](reports/technical_report.pdf), [plots](reports/figures/roc_pr.png) and
[executed notebook](notebooks/01_meshlens_walkthrough.ipynb) retain its reconstruction experiment.

## What the dataset contains

[MVTec AD Grid](docs/DATASET_CARD.md) contains real close-ups of an industrial grid texture:
342 source images and 57 defect masks. Defects include bent/broken wires, glue, metal
contamination and foreign thread.

| Partition | Images | Purpose |
|---|---:|---|
| Fit | 160 normal | Normal reference fitting |
| Tune | 52 normal | Candidate/score-rule comparison with seeded synthetic alterations |
| Calibration | 52 normal | Freeze the review threshold |
| Official test | 21 normal + 57 defective | Measure the frozen complete pipeline |

The upgrade's tune suite adds 260 synthetic alterations to those 52 unchanged tune images.
Synthetic development recall is reported separately from real-defect benchmark recall.
Real test labels and masks do not fit the detector or set its threshold. All 401 raw files
(images, masks and license/readme) are tracked; generated caches are ignored.

## Run the application

From the extracted project root, with Node.js 22 or newer:

```powershell
npm.cmd ci
npm.cmd test
npm.cmd run build
npm.cmd run serve
```

Open the printed URL, normally `http://127.0.0.1:4173`. On Linux/macOS use `npm` in place of
`npm.cmd`. The build uses shipped artifacts and does not retrain or download data.
The [workflow guide](docs/RUNBOOK.md) includes an available-port fallback and Python examples.

For offline detector inference on Python 3.12:

```powershell
py -3.12 -m venv .venv-inspection
.\.venv-inspection\Scripts\python.exe -m pip install -r requirements-inspection.lock
.\.venv-inspection\Scripts\python.exe -m pip install --no-deps -e .
.\.venv-inspection\Scripts\python.exe scripts/inspect_image.py "C:\path\to\mesh-photo.png" --evidence inspection-output/run-1
```

Choose a new evidence directory for each run. The CLI returns an explicit inconclusive status
for unsuitable inputs and protects existing outputs. See the guide for Linux commands,
selected-detector reproduction and the separate historical AE training workflow.

## Release contents and limits

| Path | Contents |
|---|---|
| `artifacts/inspection/` | Frozen detector, calibration, metadata and canonical benchmark examples |
| `reports/inspection/` | Protocol, candidate selection, freeze record and measured evaluation |
| `artifacts/model.onnx` | Historical trained reconstruction AE |
| `src/meshlens/`, `web/` | Python/browser input, scoring and interaction contracts |
| `data/` | Complete licensed Grid acquisition, manifest and provenance |
| `tests/` | Model, input, artifact, browser and lifecycle regression checks |
| `docs/` | Cards, operation/deployment guides, field workflow and prior UI audit |

The build validates the selected release's hashes, threshold, source implementation,
calibration, evaluation support and gallery provenance. Software tests cover defined cases.
The recovered release's [78-source runtime check](reports/inspection/official-runtime-parity.json)
and [18-gallery replay check](reports/inspection/gallery-runtime-parity.json) passed with identical
canonical pixels, rounded scores and decisions between Python and JavaScript under Node.js.
New materials, lighting, scale, viewpoints, blur, physical camera operation and line timing
need representative testing. The responsive interface supports narrow layouts and keyboard
use; physical-device and assistive-technology checks remain part of deployment verification.

Original code and documentation: **Kumar Waibhav Akshat**, [MIT](LICENSE).
MVTec data, masks, examples and dataset-derived material retain **CC BY-NC-SA 4.0** terms.
The code license does not grant commercial data rights. Preserve the
[third-party notices](THIRD_PARTY_NOTICES.md) when sharing the project.
