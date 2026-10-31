# MeshLens workflow guide

Run commands from the extracted `MeshLens` folder containing `package.json` and
`pyproject.toml`. Keep a copy of the delivered release before regenerating weights or reports.
The GitHub archive includes trained assets and real examples. The complete archive additionally
contains the licensed raw data and built `dist/` application.

## Choose a workflow

| Goal | Requirements | Raw data? |
|---|---|---|
| Use the private hosted preview | Supported browser and owner access | No |
| Build/serve the app | Node.js 22 or newer and npm | No |
| Inspect an image through Python | Python 3.12, inference lock and local package install | No |
| Run source/model checks | Python development environment and Node.js/npm | Optional; raw-only audit explicitly skips when absent |
| Audit all images/masks or recompute evaluation | Above plus complete dataset or downloader access | Yes |
| Optimize new weights | Full environment, complete dataset, separate fresh-training copy | Yes |

The exact Python closure was recorded on CPython 3.12 Linux x86_64. Full native Windows/macOS
Python installation and a particular WSL machine have not been executed. WSL supplies Linux on
Windows, but local installation still needs verification. Node.js 24.22.1 was used for the
recorded local audit; CI specifies Node.js 22.

## Build and use the static app

```bash
node --version
npm --version
npm ci
npm test
npm run build
npm run serve
```

Open `http://127.0.0.1:4173`. The server binds to loopback by default. The complete archive's
existing `dist/` can be served with `npm run serve` without reinstalling ML dependencies.
Rebuilding requires `npm ci` first. Wait for model ready, inspect a bundled example, and
compare input, reconstruction and residual. A low score is not a defect-free guarantee.
Use HTTP rather than opening `index.html` through `file://`.

If Python is available, an alternative local server is:

```bash
python -m http.server 8000 --bind 127.0.0.1 --directory dist
```

For that alternative, open `http://127.0.0.1:8000`.

## Run the frozen ONNX model through Python

With Python 3.12 installed on Linux x86_64:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-inference.lock
python -m pip install --no-deps -e .
python scripts/predict.py artifacts/samples/bent-000.png --output tmp/inspection.json --evidence tmp/evidence
```

The local package install makes `meshlens` importable; installing the lock alone does not
install this project. The CLI reads the shipped ONNX graph/metadata and does not train or
download a model. JSON/evidence go to the Git-ignored `tmp/` directory. Optional `--bundle PROJECT_ROOT` selects a
different complete trusted model bundle. Use the development environment for all tests,
training, reports and notebooks; the inference lock intentionally omits those dependencies.

## Install the full development environment

```bash
python3.12 -m venv .venv-dev
source .venv-dev/bin/activate
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
npm ci
python scripts/verify_project.py
python scripts/verify_wasm.py
```

The quick path uses tracked real images and trained assets, without downloading raw data.
When raw data is absent, only its explicitly optional audit skips; tracked-image inference
must still run. Partial or modified raw data is an error. `pip install -e .` alone does not
recreate the frozen closure. The original-training lock preserves the historical PyTorch
version and its advisory findings; it is provenance rather than the default recommendation.

## Acquire or verify the dataset

```bash
python scripts/download_data.py
python scripts/download_data.py --verify-only
python scripts/verify_project.py --full-data
python scripts/verify_wasm.py --full-test
```

The first command acquires the pinned grid archive when raw data is absent. Verify-only
requires the raw acquisition and never rewrites expected checksums. For partial/corrupt data,
use `python scripts/download_data.py --repair`; explicit repair stages and verifies the pinned
source before replacing raw data. Never edit hashes to make damaged data pass.

The complete archive contains 342 images, 57 masks, and source license/readme files. Raw data
and caches are ignored by Git. MVTec images/masks/derived material retain CC BY-NC-SA 4.0;
the original code's MIT license does not grant commercial dataset rights.

## Recompute release artifacts

```bash
python scripts/train.py
python scripts/evaluate.py
python scripts/export_model.py
python scripts/verify_project.py --full-data
python scripts/verify_wasm.py --full-test
python scripts/make_notebook.py
python scripts/make_report.py
python scripts/make_audit_report.py
npm run build
```

Default training validates/reuses matching completed `candidate-*.pt` checkpoints, then
recomputes normal-development selection. An interrupted optimization resumes from matching
`training-resume-*.pt` state. Running the command does not always optimize from scratch.
The notebook runs the shipped model and records real outputs using socketless IPython; it
does not train or tune a network. The report reads measured artifacts. The static build copies
the frozen graph/metadata/report; browser startup never trains weights.

For fresh optimization, use a **separate extracted project copy**. From that copy's root:

```bash
mkdir -p ../meshlens-saved-checkpoints
mv artifacts/candidate-*.pt artifacts/training-resume-*.pt ../meshlens-saved-checkpoints/
python scripts/download_data.py
python scripts/train.py --epochs 26
python scripts/evaluate.py
python scripts/export_model.py
python scripts/verify_project.py --full-data
python scripts/verify_wasm.py --full-test
```

Retain the 160 fit / 52 tune / 52 calibration split. Fitting all 264 original normal images
would consume existing tune/calibration data and require independent new development/calibration
data. Hardware/framework changes can alter new weights and results. Never change the frozen
threshold merely to hide an exact runtime tie. The strict PyTorch migration diagnostic remains
separate from ONNX checks, and a short training smoke test is not a new quality evaluation.

## Windows PowerShell

For the static application, use Node.js without the ML Python stack:

```powershell
Set-Location "C:\path\to\MeshLens"
Get-Item .\package.json
node --version
npm.cmd --version
npm.cmd ci
npm.cmd test
npm.cmd run build
npm.cmd run serve
```

The `.cmd` wrapper avoids PowerShell blocking `npm.ps1`; it does not change execution policy.

For Linux Python development on Windows, follow Microsoft's WSL installation guide, confirm
Python 3.12 is installed in that distribution, and run the Linux commands there. Do not use
PowerShell's Windows `py` executable to create a Linux venv. Windows venv interpreters live at
`.venv\Scripts\python.exe`; Linux uses `.venv/bin/python`. Create environments on the target
system rather than copying them across platforms. Calling a venv interpreter directly avoids
changing PowerShell execution policy. See the separate [GitHub guide](github-windows.md) for
commit identity and account verification. Publishing source does not change the private
preview's audience.

## Camera timing and industrial limits

Camera capture requires HTTPS or localhost, device/browser support and explicit permission.
It requests video only. The app processes one frame at a time, then waits the selected 250,
1000 or 2500 ms (default 1000 ms) before sampling again. Ideal upper bounds before processing
overhead are 4, 1 or 0.4 inspected frames/second respectively. There is no inference queue.
This is sampled live review, not full-video-FPS line inspection or a real-time control guarantee.

`source_timestamp` is captured when decoded source pixels are selected. `processing_ms` covers
animation-frame wait, preprocessing, ONNX inference and residual/scoring, excluding file decode
and final DOM paint. `inference_ms` measures `session.run` only. None alone measures a physical
camera's full exposure-to-result latency. Hardware, optics, motion blur, conveyor speed and
long-duration operation remain unverified.

The measured 19.3% defect recall cannot qualify automatic material acceptance/rejection.
A target-line study needs independent representative data, stable lighting/view/scale,
agreed missed-defect and false-alarm costs, and measured end-to-end timing at the intended speed.

## Troubleshooting

| Symptom | Check |
|---|---|
| `ModuleNotFoundError: meshlens` | Install the local package in the same environment as the script. |
| Notebook/report module missing | Use the development lock; the inference lock is intentionally smaller. |
| `npm`/`node` unavailable | Install Node.js/npm and reopen the shell. |
| Missing model/metadata | Extract the whole source archive, preserving `artifacts/`. |
| Missing browser/WASM assets | Run `npm ci` before building or verifying WASM. |
| Camera unavailable | Check HTTPS/localhost, device/browser support and permission; use a still image. |
| Raw audit fails | Use pinned explicit repair; do not edit hashes or ignore partial data. |
| Arbitrary image scores differ across runtimes | Check orientation, alpha, interpolation and bounds; exact arbitrary-resize equivalence is not asserted. |

## Official command references

- [Python 3.12 venv](https://docs.python.org/3.12/library/venv.html)
- [npm ci](https://docs.npmjs.com/cli/v11/commands/npm-ci/)
- [Microsoft WSL installation](https://learn.microsoft.com/en-us/windows/wsl/install)
