# Model card: MeshLens convolutional autoencoder

**Historical reconstruction model.** The active inspection decision is documented in
[MODEL_CARD.md](MODEL_CARD.md). The figures below describe this autoencoder only.

**Owner:** Kumar Waibhav AKshat <kwa.waibhav@gmail.com>

## Intended use

Image-level anomaly review for controlled views of industrial mesh-like material. The model
learns normal patterns and exposes reconstruction-error evidence. It does not diagnose a
physical defect type, supply a defect probability or deliver validated pixel segmentation.
It is a reproducible research/portfolio inspection system, not a factory-qualified controller.

## Operational scope and input policy

The measured checkpoint is a prototype for human review. Its low defect recall does not qualify automatic material acceptance/rejection or a production quality guarantee.

Still PNG/JPEG/WebP inputs resolve EXIF orientation and composite transparency over opaque white before resizing. Bounds are 32-4096 pixels per side, 16 megapixels and 12 MiB for uploads/CLI files. Browser/Pillow resizing can differ for arbitrary images; opaque benchmark tensors are unchanged by the alpha policy.

Camera mode is serial sampled inference, with a selectable 250/1000/2500 ms delay after completed inspections (default 1000 ms). It is not full-video-FPS processing. The source timestamp is recorded after decoding when source pixels are selected. Processing time covers animation-frame wait, preprocessing, model inference and scoring, excluding file decode and final DOM paint. Model inference time covers session.run only. Physical camera hardware, optics, line speeds and long-duration end-to-end throughput are unverified. See the workflow guide and project audit for bounded coverage.

## Frozen configuration

| Property | Measured release value |
|---|---|
| Candidate | `denoising` |
| Input/output | RGB Float32 NCHW `[1,3,256,256]`, `[0,1]` |
| Encoder channels |3 >12 >16 >24 >8|
| Decoder channels |8 >24 >16 >12 >3|
| Parameters |25,339|
| Hidden/output activations |LeakyReLU 0.1; linear bottleneck; sigmoid output|
| Boundary |Reflect-pad 16 pixels, reconstruct, crop back|
| Training patches |64x64 normal patches, normal-pattern flips|
| Input Gaussian noise std |0.035|
| Selected checkpoint epoch |26 of 26|
| Image score |Mean highest 1% squared RGB residuals; count rounded upward|
| Threshold |`0.0240220837`|
| Decision |Review only if score strictly exceeds threshold|

All parameters are trained from random initialization. The trusted checkpoint is loaded with
`weights_only=True`; never load checkpoints from untrusted sources. The exported graph,
version, tensor contract and artifact hash are retained with the metadata.

## Selection boundary

Fit 160 / tune 52 / calibration 52 use only normal source images; official test 78 remains separate.
Patches stay in their source-image role. Checkpoint choice minimizes normal tune MSE. Candidate
and aggregation choice uses normal-versus-fixed-synthetic tune AUROC with the recorded tie
rule. Synthetic rectangles, cuts and streaks are development proxies rather than real defects.

| Candidate | Latent | Noise std | Top pixels | Synthetic tune AUROC |
|---|---:|---:|---:|---:|
| compact-clean | 4 | 0.0 | 1% | 0.9094 |
| compact-clean | 4 | 0.0 | 5% | 0.7792 |
| denoising | 8 | 0.035 | 1% | 0.9124 |
| denoising | 8 | 0.035 | 5% | 0.7885 |

The calibration threshold comes from 52 separate normal images with alpha = 0.05 and sorted rank
ceil((52+1)*0.95)=51. Its normal-tail interpretation assumes exchangeability and does not
establish a false-alarm rate after illumination, scale or viewpoint shift.

## Held-out results

| Frozen method | AUROC | Average precision | Precision | Defect recall | F1 |
|---|---:|---:|---:|---:|---:|
| Convolutional autoencoder | 0.7594 | 0.9005 | 100.00% | 19.30% | 32.35% |
| Patch PCA baseline | 0.7602 | 0.8987 | 100.00% | 8.77% | 16.13% |

At the frozen threshold, **11 of 57 defects** were flagged, **46 were missed**, and **0 of 21 normal images** were flagged. The stratified fixed-model bootstrap 95% AUROC interval is 0.6391-0.8655. It measures resampling uncertainty for this fixed model, not retraining or new-factory variation.

Development selected `denoising`, 8 latent channels, checkpoint epoch 26, and the largest 1% of pixel residuals. Separate normal calibration fixed the threshold at `0.02402208`.

Wilson 95% precision interval: 74.12%-100.00%; normal false-alarm interval: 0.00%-15.46%. Zero observed false alarms is not proof of zero population risk.


| Group | Images | Flagged | Flag rate |
|---|---:|---:|---:|
| Bent | 12 | 1 | 8.33% |
| Broken | 12 | 3 | 25.00% |
| Glue | 11 | 5 | 45.45% |
| Good | 21 | 0 | 0.00% |
| Metal Contamination | 11 | 1 | 9.09% |
| Thread | 11 | 1 | 9.09% |

Good-group flag rate is a normal false-alarm rate. Defect-group flag rates are recalls.
Small counts have substantial uncertainty. Fixed-model bootstrap intervals do not include
retraining or model-selection uncertainty. If no false positives are observed, a degenerate
precision bootstrap interval is not proof of perfect population precision; use the recorded
finite-count Wilson interval as well.

## Normal-image stress checks

| Condition | False alarms | False-alarm rate |
|---|---:|---:|
| original | 0/21 | 0.00% |
| dim 70 percent | 0/21 | 0.00% |
| bright 130 percent | 20/21 | 95.24% |
| circular shift 8 pixels | 3/21 | 14.29% |

These modifications probe frozen-model sensitivity on normal images, not factory event rates.
No threshold is retuned after observing the held-out test or stress outcomes.

## Framework, export and runtime verification

Training framework: `PyTorch 2.9.0+cpu`.
The shipped environment can differ after a security update; framework compatibility records
state what was actually checked. Export parity, actual WebAssembly checks and UI/camera checks
have different scopes and must not be conflated. Browser/Pillow resampling can differ slightly
for arbitrary uploads; tracked opaque examples already have model dimensions.

Source/model verification: passed; 145 Python tests, 145 passed, 0 failures, 0 errors and 0 skips.

Node.js browser-contract tests: 85 tests, 85 passed, 0 failures, 0 errors and 0 skipped.

Source-only checkout verification: passed; 145 Python tests, 144 passed, 0 failures, 0 errors and 1 skipped. The optional full raw-data audit is separate from mandatory tracked-model/example inference.

PyTorch/ONNX export check: 78 official test images, maximum tensor difference 2.98e-07, maximum score difference 4.29e-09, 0 changed decisions.

Actual ONNX Runtime Web WebAssembly under Node.js: passed; 78 shared canonical tensors, maximum score difference 3.01e-09, 0 changed decisions. Browser decoding, DOM interactions and physical cameras are outside this check.

Framework boundary diagnostic: PyTorch 2.9.0+cpu to 2.14.1+cpu on 130 calibration/test images. Strict decision parity failed; maximum score difference 3.52e-10. Changed decisions: calibration 1, official test 0. A calibration score exactly equal to the frozen threshold crosses it after a tiny floating-point change. Numerical tolerances are met, but exact decision equality is not. The threshold was not retuned. Browser/CLI inference use the frozen ONNX graph. No retraining is implied.

Named-scope dependency advisory scans: recommended runtime: passed, 36/36 packages, 0 findings; development: passed, 97/97 packages, 0 findings; historical original-training lock: 5 findings (provenance only, not the default install); npm: 0 findings. These scans are not security certification.

## Limitations and rights

New material, lighting, blur, mesh scale, pose and camera movement need representative local
validation. The residual can emphasize ordinary edges or reconstruct a defect well enough
to miss it. A high score supports review; a low score can still hide a defect. Browser-local
history is not authenticated, synchronized or tamper-proof.

Original code/documentation are MIT licensed. MVTec AD data, masks, samples and dataset-derived
material retain CC BY-NC-SA 4.0 terms. See the dataset card and third-party notices.
