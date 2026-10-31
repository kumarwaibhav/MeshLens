#!/usr/bin/env python3
"""Build and actually execute a walkthrough of the current frozen MeshLens model."""

from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import nbformat

ROOT = Path(__file__).resolve().parents[1]


def execute_inprocess(notebook) -> None:
    """Capture real IPython cell outputs without opening restricted kernel sockets."""
    from IPython.core.interactiveshell import InteractiveShell
    from IPython.utils.capture import capture_output
    import matplotlib
    from matplotlib_inline.backend_inline import configure_inline_support

    shell = InteractiveShell.instance()
    matplotlib.use("module://matplotlib_inline.backend_inline")
    configure_inline_support(shell, "inline")
    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue
        with capture_output(stdout=True, stderr=True, display=True) as captured:
            execution = shell.run_cell(cell.source, store_history=True)
        error = execution.error_before_exec or execution.error_in_exec
        if error:
            raise RuntimeError(
                "Real notebook cell execution failed: " + captured.stderr
            ) from error
        cell.execution_count = execution.execution_count
        cell.outputs = []
        if captured.stdout:
            cell.outputs.append(
                nbformat.v4.new_output("stream", name="stdout", text=captured.stdout)
            )
        if captured.stderr:
            cell.outputs.append(
                nbformat.v4.new_output("stream", name="stderr", text=captured.stderr)
            )
        for output in captured.outputs:
            cell.outputs.append(
                nbformat.v4.new_output(
                    "display_data", data=output.data, metadata=output.metadata
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--engine", choices=["inprocess", "jupyter"], default="inprocess"
    )
    args = parser.parse_args()
    for relative in [
        "artifacts/model.onnx",
        "artifacts/checkpoint.pt",
        "artifacts/metadata.json",
        "reports/metrics.json",
        "reports/selection.json",
        "data/provenance.json",
    ]:
        if not (ROOT / relative).is_file():
            raise SystemExit("Missing current-run evidence: " + relative)
    code = nbformat.v4.new_code_cell
    md = nbformat.v4.new_markdown_cell
    cells = [
        md(
            "# MeshLens: from normal patterns to residual evidence\n\n**Kumar Waibhav AKshat** - `kwa.waibhav@gmail.com`\n\nThis walkthrough executes the shipped trained autoencoder, verifies ONNX export agreement,\nand reads the recorded held-out evaluation. It neither retrains a model nor tunes against\ntest labels. The task is image-level anomaly review on industrial grid material.\nMVTec AD images and masks retain their CC BY-NC-SA 4.0 terms.\n"
        ),
        code(
            "from pathlib import Path\nimport csv\nimport hashlib\nimport json\nimport sys\nimport time\nfrom collections import Counter\n\nimport matplotlib.pyplot as plt\nimport numpy as np\nfrom PIL import Image\nimport onnxruntime as ort\n\nROOT = Path.cwd()\nif not (ROOT / 'artifacts/model.onnx').is_file():\n    ROOT = ROOT.parent\nassert (ROOT / 'artifacts/model.onnx').is_file(), 'Run from the project root or notebooks directory'\nsys.path.insert(0, str(ROOT / 'src'))\nfrom meshlens.core import preprocess_image, residual_score\n\nmetadata = json.loads((ROOT / 'artifacts/metadata.json').read_text())\nevaluation = json.loads((ROOT / 'reports/metrics.json').read_text())\nprovenance = json.loads((ROOT / 'data/provenance.json').read_text())\nselection = json.loads((ROOT / 'reports/selection.json').read_text())\nprint('Model:', metadata['model_version'])\nprint('Selected candidate:', selection['selected']['name'])\nprint('Current acquisition:', provenance['image_count'], 'images;', provenance['mask_count'], 'masks')\nprint('Roles:', provenance['split_counts'])\n"
        ),
        md(
            "## 1. Verify the experiment boundary\n\nThe source image is the split unit. Patches and synthetic versions never cross roles.\nFit, tune and calibration contain normal images only. Official test images remain outside\nweight optimization, model/checkpoint choice, score-rule choice and threshold calibration.\n"
        ),
        code(
            "manifest = ROOT / 'data/manifest.csv'\nassert hashlib.sha256(manifest.read_bytes()).hexdigest() == provenance['manifest_sha256']\nwith manifest.open(newline='') as stream:\n    rows = list(csv.DictReader(stream))\nassert len({row['sha256'] for row in rows}) == len(rows)\nassert all(row['label'] == '0' for row in rows if row['split'] != 'test')\nfor (role, label), count in sorted(Counter((row['split'], row['label']) for row in rows).items()):\n    print(role, 'defect' if label == '1' else 'normal', count)\nprint('Current manifest hash, duplicate-image and normal-development contracts verified.')\n"
        ),
        md(
            "## 2. Run the actual exported model\n\nThe tracked replay sample is already at model dimensions, so a clean source checkout can\ninspect it without downloading raw training data. Input is RGB Float32 `[0,1]`, NCHW.\nStill images resolve EXIF orientation and composite transparency over opaque white before\nresizing. Source images are bounded to 32-4096 pixels per side and 16 megapixels. Opaque\nbenchmark inputs are unchanged by the alpha policy. Browser/Pillow resizing can differ for\narbitrary images. The model reconstructs RGB intensities; it does not output a defect-type label.\n"
        ),
        code(
            "sample_path = sorted((ROOT / 'artifacts/samples').glob('*.png'))[0]\nwith Image.open(sample_path) as image:\n    tensor = preprocess_image(image, int(metadata['image_size']))\noptions = ort.SessionOptions()\noptions.intra_op_num_threads = 1\nsession = ort.InferenceSession(str(ROOT / 'artifacts/model.onnx'), options,\n                               providers=['CPUExecutionProvider'])\nstarted = time.perf_counter()\nreconstruction = session.run(None, {session.get_inputs()[0].name: tensor[None]})[0][0]\nelapsed_ms = (time.perf_counter() - started) * 1000\nfraction = float(metadata.get('score_top_fraction', selection['selected']['top_fraction']))\nscore, residual = residual_score(tensor, reconstruction, fraction)\nthreshold = float(metadata['threshold'])\nprint(json.dumps({'sample': sample_path.name, 'score': score, 'threshold': threshold,\n                  'review_recommended': score > threshold, 'score_is_probability': False,\n                  'inference_ms_this_run': round(elapsed_ms, 3)}, indent=2))\nassert np.isfinite(score) and residual.shape == (256, 256)\n"
        ),
        code(
            "fig, axes = plt.subplots(1, 3, figsize=(13, 4), constrained_layout=True)\naxes[0].imshow(tensor.transpose(1, 2, 0))\naxes[0].set_title('Input')\naxes[1].imshow(np.clip(reconstruction.transpose(1, 2, 0), 0, 1))\naxes[1].set_title('Trained reconstruction')\nheat = axes[2].imshow(residual, cmap='magma', vmin=0)\naxes[2].set_title('Squared RGB residual')\nfor axis in axes:\n    axis.axis('off')\nfig.colorbar(heat, ax=axes[2], shrink=0.75, label='Mean squared RGB error')\nplt.show()\n"
        ),
        md(
            "## 3. Verify the trained checkpoint and exported graph agree\n\nThe same input tensor is reconstructed by both actual runtimes. This numerical check verifies\ndeployment agreement; it is separate from the held-out quality evaluation.\n"
        ),
        code(
            "import torch\nfrom meshlens.model import load_checkpoint\n\ntorch.set_num_threads(1)\nmodel, config = load_checkpoint(ROOT / 'artifacts/checkpoint.pt')\nwith torch.inference_mode():\n    native = model(torch.from_numpy(tensor[None])).numpy()[0]\nmaximum_error = float(np.max(np.abs(native - reconstruction)))\nnp.testing.assert_allclose(native, reconstruction, atol=1e-5, rtol=1e-4)\nnative_score, _ = residual_score(tensor, native, fraction)\nprint('Execution PyTorch version:', torch.__version__)\nprint('Execution ONNX Runtime version:', ort.__version__)\nprint('Maximum absolute tensor difference:', maximum_error)\nprint('Absolute score difference:', abs(native_score - score))\nprint('Trainable parameters:', sum(parameter.numel() for parameter in model.parameters()))\nprint('Checkpoint configuration:', config)\n"
        ),
        md(
            "## 4. Read current-run held-out results\n\nAUROC/average precision summarize ranking. Precision, recall, F1 and actual confusion counts\ndescribe the separate normal-calibrated threshold. Neither metric type establishes factory\nreliability. High observed precision can coexist with many missed defects.\n"
        ),
        code(
            "measured = evaluation['model']\nprint(f\"Flagged {measured['true_positive']}/{evaluation['test_defect']} defects; \"\n      f\"missed {measured['false_negative']}; \"\n      f\"flagged {measured['false_positive']}/{evaluation['test_normal']} normal images.\")\ndisplay(measured)\ndisplay(evaluation['baseline_patch_pca'])\nif 'binomial_wilson_intervals_95' in evaluation:\n    display(evaluation['binomial_wilson_intervals_95'])\nprint('Test loaded during selection:', selection['test_loaded_during_selection'])\nprint('Calibration loaded during selection:', selection['calibration_loaded_during_selection'])\nprint('Zero observed false alarms is not proof of zero population false-alarm risk.')\n"
        ),
        code(
            "from IPython.display import Image as DisplayImage, display\n\nfor name in ['roc_pr.png', 'confusion_matrix.png', 'stress_test.png']:\n    path = ROOT / 'reports/figures' / name\n    assert path.is_file(), path\n    display(DisplayImage(filename=str(path), width=850))\n"
        ),
        md(
            "## 5. Interpretation and deployment\n\nThe static app runs the actual graph locally through ONNX Runtime Web. History is bounded and\nbrowser local. Camera sampling needs user action and permission. Images are not uploaded to a\nPython inference API. Reconstruction residuals support review rather than validated segmentation.\n\nCamera inspection is serial and sampled, with a selectable delay after completed results;\nit is not full-video-FPS processing. Model-call time is separate from end-to-end latency.\nPhysical camera hardware, line speed and long-duration operation have not been validated.\n\nLighting, scale, pose, blur and unfamiliar material can alter scores. The curated benchmark is\nsmall and recall is limited; the checkpoint does not qualify automatic material acceptance or\nrejection. See the model/data cards, project audit and workflow guide for exact release scope.\n\nTo rebuild after installing the pinned environment, run acquisition, training, evaluation and\nexport scripts in order. `npm ci` and `npm run build` produce the static web output. Completed\ncandidates are reused by default; fresh optimization uses a separate copy as documented in\nthe workflow guide. This walkthrough itself does not retrain or retune the network.\n"
        ),
    ]
    notebook = nbformat.v4.new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {
                "display_name": "Python3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": sys.version.split()[0]},
            "authors": [
                {"name": "Kumar Waibhav AKshat", "email": "kwa.waibhav@gmail.com"}
            ],
            "artifact_lineage": {
                "model_sha256": hashlib.sha256(
                    (ROOT / "artifacts/model.onnx").read_bytes()
                ).hexdigest(),
                "metrics_sha256": hashlib.sha256(
                    (ROOT / "reports/metrics.json").read_bytes()
                ).hexdigest(),
                "checkpoint_sha256": hashlib.sha256(
                    (ROOT / "artifacts/checkpoint.pt").read_bytes()
                ).hexdigest(),
                "selection_sha256": hashlib.sha256(
                    (ROOT / "reports/selection.json").read_bytes()
                ).hexdigest(),
            },
        },
    )
    started = datetime.now(timezone.utc).isoformat()
    if args.engine == "inprocess":
        execute_inprocess(notebook)
    else:
        from nbclient import NotebookClient

        NotebookClient(
            notebook,
            timeout=180,
            kernel_name="python3",
            resources={"metadata": {"path": str(ROOT)}},
        ).execute()
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    errors = [
        output
        for cell in code_cells
        for output in cell.get("outputs", [])
        if output.output_type == "error"
    ]
    if errors or any((cell.execution_count is None for cell in code_cells)):
        raise RuntimeError("Notebook execution was incomplete or had error outputs")
    destination = ROOT / "notebooks/01_meshlens_walkthrough.ipynb"
    destination.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, str(destination))
    summary = {
        "execution_started_utc": started,
        "execution_finished_utc": datetime.now(timezone.utc).isoformat(),
        "notebook": str(destination.relative_to(ROOT)),
        "code_cells": len(code_cells),
        "executed_cells": len(code_cells),
        "error_outputs": len(errors),
        "image_outputs": sum(
            "image/png" in output.get("data", {})
            for cell in code_cells
            for output in cell.get("outputs", [])
        ),
        "uses_frozen_trained_model": True,
        "retrained_during_walkthrough": False,
        "model_version": json.loads((ROOT / "artifacts/metadata.json").read_text())[
            "model_version"
        ],
        "model_sha256": notebook.metadata["artifact_lineage"]["model_sha256"],
        "metrics_sha256": notebook.metadata["artifact_lineage"]["metrics_sha256"],
        "checkpoint_sha256": notebook.metadata["artifact_lineage"]["checkpoint_sha256"],
        "selection_sha256": notebook.metadata["artifact_lineage"]["selection_sha256"],
        "execution_engine": "socketless IPython"
        if args.engine == "inprocess"
        else "nbclient/Jupyter",
        "execution_python": sys.version.split()[0],
    }
    if args.engine == "inprocess":
        summary["execution_pytorch"] = sys.modules["torch"].__version__
        summary["execution_onnxruntime"] = sys.modules["onnxruntime"].__version__
    (ROOT / "notebooks/execution_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
