# MeshLens workflow guide

Run commands from the extracted `MeshLens` folder containing `package.json` and
`pyproject.toml`. Keep the delivered release intact. Use a separate project copy when
regenerating a model, calibration threshold or benchmark reports.

## Choose a workflow

| Goal | Environment | Raw dataset needed? |
|---|---|---|
| Use the web application | Browser | No |
| Build and serve the web application | Node.js 22 or newer and npm | No |
| Inspect a new still image offline | Python 3.12, minimal inspection lock | No |
| Reproduce the selected texture detector | Same Python environment and complete Grid acquisition | Yes |
| Reproduce historical AE training | Full Python development environment | Yes |
| Qualify a target-line deployment | Independently labeled physical parts and frozen scoring evidence | New field collection |

The selected inspection detector uses NumPy and Pillow. PyTorch and a Python ONNX server
are unnecessary for this path. The separate historical autoencoder has its own dependencies
and training workflow. Python lock closures were observed on Linux x86_64; a complete
native Windows/macOS Python installation is a separate platform check.

## Build and use the static app

```bash
npm ci
npm test
npm run build
npm run serve
```

Open the printed URL, normally `http://127.0.0.1:4173`. The server binds to loopback. Wait for
model readiness, inspect a bundled image and compare Original, Detector map, Reconstruction
and AE error map. The detector decides whether to request review. The AE views illustrate
reconstruction. A score within the calibrated range does not establish defect-free material.

The build verifies and copies the frozen release. It does not fit a detector, train a network
or download raw data. Serve through HTTP rather than opening `index.html` with `file://`.

If port 4173 is occupied, select an available port without stopping another application:

```bash
node --input-type=module -e "import {startServer} from './scripts/serve_web.mjs'; const server = await startServer({port:0}); console.log('http://127.0.0.1:' + server.address().port)"
```

## Inspect a still image through Python

Create an environment for the lightweight texture detector on Python 3.12:

```bash
python3.12 -m venv .venv-inspection
.venv-inspection/bin/python -m pip install -r requirements-inspection.lock
.venv-inspection/bin/python -m pip install --no-deps -e .
.venv-inspection/bin/python scripts/inspect_image.py data/raw/grid/train/good/000.png --evidence inspection-output/run-1
```

Replace the example path with a new still PNG/JPEG/WebP photo. No download or training occurs.
Optional `--output inspection-output/result-1.json` writes a separate result JSON.
`--bundle PROJECT_ROOT` selects another complete trusted release.

The CLI checks frozen files before scoring and applies the same detector input policy. Results
contain the status, reason, version, threshold, score and decision. A valid scored result exits
with `0`; an inconclusive input exits with `1`; command/output errors use `2`. Inconclusive
results have no numeric acceptance decision. Fix the stated input issue and inspect again.

Evidence contains the canonical input, a per-image normalized relative anomaly map and JSON.
Map intensity is neither a defect probability nor a validated segmentation mask. Choose a new
evidence directory and output filename each time; earlier outputs are protected from overwrite.
Outputs must be outside frozen source/data/artifact/report paths. `inspection-output/` is
ignored by Git to keep local image evidence out of a normal source push.

Structural file limits are 12 MiB, 32-4096 pixels per side and 16 megapixels. Suitability also
requires each side to be at least the detector input size, an aspect ratio at most 1.5 and
usable mesh repetition. No automatic crop repairs an unsuitable view. Use a sharp close-up
of comparable mesh scale under stable lighting. Uploading an image never trains the model.

## Verify the data

```bash
.venv-inspection/bin/python scripts/download_data.py --verify-only
```

This repository tracks all 401 files in `data/raw/grid/`: 342 images, 57 masks and the source
license/readme files. The `data/raw/` ignore rule covers untracked files and does not remove
this acquisition. Generated caches are ignored. Quick app/runtime checks use trained assets
and small examples without processing the complete dataset.

If the acquisition is absent, run `scripts/download_data.py` in this environment. For an
explicit repair of partial or corrupt data, use `scripts/download_data.py --repair`.
The downloader stages and verifies the pinned source before replacing raw files. Never edit
expected hashes to make damaged files pass.

Data, masks, examples and dataset-derived material retain MVTec's CC BY-NC-SA 4.0 terms.
The original code's MIT license does not grant commercial data rights.

## Reproduce the selected texture detector

Use a separate extracted project copy. These steps regenerate the selected method from its
normal data and recorded protocol. They do not establish a new independent benchmark.
The official test set was already measured for the historical autoencoder and this selected
texture method. Recovery repeats that previously selected algorithm without architecture or
cutoff retuning; the recorded outcomes are known before reproduction.

First create a new output directory outside the repository for development images:

```bash
.venv-inspection/bin/python scripts/make_development_suite.py --output ../meshlens-reproduction/development
.venv-inspection/bin/python scripts/fit_texture_detector.py --development ../meshlens-reproduction/development/manifest.csv --output-dir ../meshlens-reproduction/texture
.venv-inspection/bin/python scripts/fit_texture_detector.py --frozen-candidate ../meshlens-reproduction/texture/frozen-candidate.json --output-dir ../meshlens-reproduction/calibration
```

The suite uses only 52 tune sources: 52 unchanged images and 260 seeded synthetic alterations.
Candidate variants and score aggregation are chosen using those development proxies. The
separate 52 normal calibration images then set the threshold at sorted rank 51 with alpha
0.05. Real test defects and masks do not choose the candidate or threshold.

The recorded selected texture configuration and selection policy are in
`reports/inspection/selection.json` and `reports/inspection/protocol.json`; the original
15-configuration development evidence is retained in `reports/texture/`. This recovery
reproduces the already-selected texture method. Synthetic tune recall is separate from
real-defect accuracy.

Compare regenerated outputs with the supplied `artifacts/texture/texture-model.json`,
`reports/texture/calibration-scores.json` and `reports/texture/frozen-candidate.json` using
SHA256. Retain both sets when investigating a difference. Source/framework changes can alter
numerical bytes; changing expected hashes does not establish that the difference is acceptable.

For the supplied recovered release, verify its existing frozen inputs:

```bash
.venv-inspection/bin/python scripts/freeze_inspection.py --check
```

The command prints the configuration's SHA256 and model version. The packaging form without
`--check` reads the supplied texture model/calibration/selection paths and creates the
inspection bundle only when compatible frozen outputs are absent. It rejects conflicting
existing bytes and is specific to the recorded selected algorithm and cutoff. A changed
method needs a separately versioned development/calibration/release protocol.

Retain the pre-evaluation digest of `reports/inspection/frozen_configuration.json`.
Supply that independently recorded digest explicitly to repeat evaluation:

```bash
.venv-inspection/bin/python scripts/evaluate_inspection.py --freeze-sha256 84b80e2b170f97ef5b432f78e210f260bbe687b72484e648661a21719daf9e23
.venv-inspection/bin/python scripts/export_inspection_release.py
npm run build
```

The digest above is this delivered recovery release's pre-evaluation pin. A deliberately
regenerated release needs its own independently recorded digest. Evaluation verifies the model,
metadata, calibration, protocol, selection, manifest and implementation bytes. It measures the
78 original benchmark images plus five declared perturbations. Export packages measured
results and 18 canonical benchmark replay images. Do not tune the threshold after these results.
The selected method, support counts, confidence intervals, coverage and all stress conditions
must remain visible even when a release goal fails.

## Check Python/browser runtime agreement

With the minimal Python environment and Node.js installed:

```bash
.venv-inspection/bin/python scripts/verify_inspection_runtime.py --freeze-sha256 84b80e2b170f97ef5b432f78e210f260bbe687b72484e648661a21719daf9e23
.venv-inspection/bin/python scripts/verify_inspection_runtime.py --full-test --freeze-sha256 84b80e2b170f97ef5b432f78e210f260bbe687b72484e648661a21719daf9e23
```

The default checks the 18 served gallery replays and writes
`reports/inspection/gallery-runtime-parity.json`. `--full-test` additionally checks the 78
official inputs and writes `reports/inspection/runtime_parity.json`. These gallery derivatives
reuse benchmark images. The command compares canonical pixels, scores, decisions and maps
across Python and the JavaScript runtime; it does not add independent physical parts.

For independently pinned verification, add `--freeze-sha256` with the pre-evaluation digest
recorded for that release. The no-argument CI command validates the current checkout freeze.
A deliberately regenerated release needs its own newly recorded digest. Runtime agreement
is separate from every browser/device's image decoder, camera and accessibility behavior.

## Windows PowerShell

The web application needs Node.js:

```powershell
Set-Location "C:\Users\kumar\Downloads\MeshLens_Complete_Project (1)\MeshLens"
Get-Item .\package.json
node --version
npm.cmd ci
npm.cmd test
npm.cmd run build
npm.cmd run serve
```

Use your actual folder path. `npm.cmd` avoids PowerShell's `npm.ps1` execution-policy issue.
Press `Ctrl+C` to stop the local server. The port-0 command above also works in PowerShell.

For offline inspection with Python 3.12 installed:

```powershell
py -3.12 -m venv .venv-inspection
.\.venv-inspection\Scripts\python.exe -m pip install -r requirements-inspection.lock
.\.venv-inspection\Scripts\python.exe -m pip install --no-deps -e .
.\.venv-inspection\Scripts\python.exe scripts/inspect_image.py "C:\path\to\mesh-photo.png" --evidence inspection-output/run-1
$LASTEXITCODE
```

Calling the environment's interpreter directly avoids changing execution policy. Create
virtual environments on their target operating system; do not copy a Linux environment
onto Windows. For full historical PyTorch development on Windows, use a verified Python 3.12
Linux/WSL environment. The [GitHub guide](github-windows.md) checks the existing repository,
commit identity and authenticated account before a normal push.

## Historical autoencoder training and reports

The original AE remains an educational reconstruction model. `scripts/predict.py` uses its
ONNX graph and residual score. It does not run the active texture detector.

For its original development workflow, use a separate copy and the full development lock:

```bash
python3.12 -m venv .venv-dev
.venv-dev/bin/python -m pip install -r requirements-dev.lock
.venv-dev/bin/python -m pip install --no-deps -e .
.venv-dev/bin/python scripts/train.py
.venv-dev/bin/python scripts/evaluate.py
.venv-dev/bin/python scripts/export_model.py
.venv-dev/bin/python scripts/verify_project.py --full-data
.venv-dev/bin/python scripts/verify_wasm.py --full-test
.venv-dev/bin/python scripts/make_notebook.py
.venv-dev/bin/python scripts/make_report.py
```

Training reuses validated matching `candidate-*.pt` files, and interrupted runs resume from
matching `training-resume-*.pt` files. To train from random initialization, first retain and
move both checkpoint families out of `artifacts/` in the separate reproduction copy.
Keep the 160 fit / 52 tune / 52 calibration split. Training on all 264 normals consumes the
current development/calibration partitions and requires new independent partitions.

`make_report.py` writes the historical AE card, summary and technical PDF. It leaves the
active README and inspection model card intact. The historical training lock preserves the
original framework for provenance. A patched framework, hardware change or fresh fit can
change results; a short smoke test does not establish a new accuracy result.

## Field qualification and timing

Use the [field validation guide](FIELD_VALIDATION.md) for a frozen roster of independently
labeled physical parts, scoring records, hashes, operator acceptance limits and confidence
bounds. Benchmark examples, synthetic images, repeated frames and altered crops do not
supply a new independent field cohort.

Camera capture requires HTTPS or localhost, device/browser support and explicit permission.
It processes one frame at a time, then waits 250, 1000 or 2500 ms (default 1000 ms). There is
no inference queue. Model-call time, processing time and exposure-to-result latency are
different quantities. Physical cameras, optics, motion blur, conveyor speed and long-duration
operation need measurement on the intended line. The benchmark does not qualify automatic
acceptance/rejection or promise production throughput.

## Troubleshooting

| Symptom | Next step |
|---|---|
| Port 4173 is in use | Use the port-0 command and open its printed URL. |
| `ModuleNotFoundError` | Use the same interpreter that installed the minimal lock and local package. |
| Missing/changed model files | Restore the complete frozen release and investigate the mismatch. |
| `Input needs review` / `inconclusive` | Read the reason; improve resolution, framing, focus, lighting or mesh match. |
| Output already exists | Choose a new result filename/evidence directory. |
| Browser model/WASM assets are missing | Run `npm ci` and a clean `npm run build`. |
| Camera unavailable | Check HTTPS/localhost and permission; use a supported still image. |
| Dataset audit fails | Use explicit pinned repair; keep expected checksums unchanged. |
