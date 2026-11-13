# Model card: MeshLens normal-lattice inspection detector

**Owner:** Kumar Waibhav Akshat

This release supports image-level human review of controlled close-ups of woven industrial
mesh. It compares repeated texture regions and highlights unusual disagreement. It does not
identify a physical defect type, estimate a defect probability or provide validated pixel
segmentation. No independently labeled target-line cohort or physical process qualification
has been supplied.

## Active detector and visual autoencoder

The active decision comes from a normal-fitted texture detector. It estimates lattice repeats,
compares small regions with neighboring repeats using local alignment tolerance, combines
local and cell-scale disagreement, and scales responses using normal-fit statistics. The
highest 0.5% of responses supplies the image score.

The original convolutional AE separately reconstructs the input for visual comparison.
Its reconstruction and error map do not set the active score or threshold. The historical AE
flagged 11/57 defects at its own operating point; its complete experiment remains in the
[autoencoder card](AUTOENCODER_MODEL_CARD.md), original reports and notebook.

## Frozen release contract

This recovered release reproduces the previously selected algorithm and known benchmark.
Its model/calibration bytes and cutoff are unchanged; the implementation is bound by the
new recovery freeze. Exact provenance is recorded in `artifacts/inspection/detector.json`
and `reports/inspection/frozen_configuration.json`.

| Property | Value |
|---|---|
| Version | `meshlens-inspect-7665cb57f023` |
| Method | `normal-lattice-v1`, `joint` variant |
| Browser runtime | `texture-js` |
| Canonical input / map | 256×256 RGB uint8 / 256×256 relative response |
| Numeric analysis | RGB CHW in `[0,1]`; local grayscale contrast normalization |
| Resize | `area-rgb8-v1`, integer area overlap and fixed rounding |
| Local/cell windows | Radii 3 and 9 pixels |
| Aggregation | Mean largest 0.5% of responses, rounded upward to a whole pixel count |
| Normal fit scale | `0.47045176621031776` |
| Score quantization | Round half-up to 8 decimal places |
| Threshold | `1.01049636` |
| Decision | Review when `score > threshold`; equality stays within range |
| Artifact | `artifacts/inspection/detector-model.json`, 1,261 bytes |
| Calibration | 52 separate normal images; alpha 0.05; sorted rank 51 |

Artifact SHA256:
`7665cb57f02315c29a51209686a34b8a2e872f447ff31dac359c81d5c3fae5c1`

Pre-evaluation recovery-freeze SHA256:
`84b80e2b170f97ef5b432f78e210f260bbe687b72484e648661a21719daf9e23`

The frozen record pins model, metadata, calibration, protocol, selection, source manifest and
Python/JavaScript implementation bytes. These digests detect a mismatched local release.
They are not a digital signature.

## Input policy and inconclusive results

Still PNG/JPEG/WebP files are limited to 12 MiB, 4096 pixels per side and 16 megapixels.
Orientation is resolved and transparency is composited over white. Suitable inputs need both
sides at least 256 pixels and a longest-to-shortest-side ratio at most 1.5. The system resizes
the whole suitable image, without a hidden crop. Identical decoded pixels receive the same
canonical integer filter in Python and JavaScript; codec decoding is a separate boundary.

Missing/changed model files, invalid images and unsuitable dimensions block numeric decisions.
The texture method also needs at least two usable independent lattice directions. Missing
repetition returns `inconclusive` / **Input needs review** with a reason. Such results must not
be represented as a normal part or dropped from evaluation.

Input suitability does not establish that the material belongs to the trained domain.
Use comparable mesh scale, focus, lighting and viewpoint. An arbitrary photograph can contain
repetition while remaining outside the measured scope.

## Selection and calibration boundary

Normal source images are partitioned into 160 fit, 52 tune and 52 calibration images. All
patches and synthetic versions stay with their source role. The original detector-selection
protocol excludes official test images and their labels/masks.

The tune-only suite contains 52 unchanged images plus 260 fixed synthetic alterations:
bend, gap, fibre, glue and contamination. The selection metric is macro synthetic-family
recall with at most 2/52 clean tune alerts. Ties use fewer clean alerts, lower warm latency,
then smaller artifact size. The selected texture configuration's recorded synthetic macro
recall was **72.31% at 2/52 clean tune alerts**. Fifteen texture variant/aggregation
configurations were compared; their evidence is retained in `reports/texture/`.

These are development proxies rather than real-defect test accuracy. This recovery uses the
already-selected texture configuration. The active detector uses no pretrained neural weights.

After architecture and score-rule freeze, the separate 52 normal calibration images supplied
the 51st sorted score: `ceil((52+1)×0.95) = 51`. Calibration-tail interpretation assumes
exchangeability. It does not establish the false-alarm rate after a camera or process shift.
The protocol and selection record live in `reports/inspection/`.

## Official benchmark results

<!-- MESHLENS_INSPECTION_RESULTS_START -->
**Verified recovery results:** the hash-pinned restored release reproduced the previously
recorded counts in all six conditions. These are known-benchmark reproducibility results.

The original benchmark produced **56 true positives, 1 missed defect, 17 true negatives and
4 false alarms**, with 78/78 scored and no inconclusive inputs.

| Metric | Measured value | Support / uncertainty |
|---|---:|---|
| Defect recall | 98.25% | 56/57; Wilson 95% 90.71%–99.69% |
| Normal false-alarm rate | 19.05% | 4/21; Wilson 95% 7.67%–40.00% |
| Precision | 93.33% | 56/60 review alerts were defects |
| Accuracy | 93.59% | 73/78 correct image decisions |
| F1 | 95.73% | Frozen operating point |
| AUROC | 0.9958 | All 78 scored images |
| Coverage | 100.00% | 78/78 scored; 0 inconclusive |

The declared goal required recall ≥90%, normal false alarms ≤5% and 100% coverage.
**It failed the false-alarm requirement:** 4/21 clean images were flagged (19.05%).
The release remains a research/human-review aid. Its threshold was not adjusted using
these test results.

### Results by known defect group

| Known defect group | Flagged | Missed | Recall |
|---|---:|---:|---:|
| Bent | 12/12 | 0 | 100.00% |
| Broken | 12/12 | 0 | 100.00% |
| Glue | 10/11 | 1 | 90.91% |
| Metal contamination | 11/11 | 0 | 100.00% |
| Thread | 11/11 | 0 | 100.00% |

These are ground-truth benchmark groups, rather than predicted defect-type labels. The only
missed defect is [glue/008.png](../data/raw/grid/test/glue/008.png), score `0.97635626` below
the frozen `1.01049636` threshold. Normal files `007.png`, `011.png`, `018.png` and `019.png`
were falsely flagged. The full records retain every image, score, decision and source hash.

### Declared stress checks

| Condition | Defects flagged / 57 | Normal alerts / 21 | Scored / 78 | AUROC |
|---|---:|---:|---:|---:|
| Original | 56 (98.25%) | 4 (19.05%) | 78 | 0.9958 |
| Brightness 70% | 56 (98.25%) | 2 (9.52%) | 78 | 0.9975 |
| Brightness 130% | 56 (98.25%) | 6 (28.57%) | 78 | 0.9950 |
| Translation 8×4 px at 256 reference | 57 (100.00%) | 21 (100.00%) | 78 | 0.5455 |
| Gaussian blur σ=0.8 at 256 reference | 56 (98.25%) | 0 (0.00%) | 78 | 0.9967 |
| JPEG quality 75 | 56 (98.25%) | 4 (19.05%) | 78 | 0.9950 |

All conditions scored every image, with no quality abstentions. Translated views produced
21/21 normal alerts and AUROC 0.5455; this is a major view-sensitivity failure. Brightened views
also increased clean alerts. The translation uses a reflected border at the declared reference
scale. These deterministic perturbations reuse the same physical images; they are not new
independent parts or measurements of factory event rates. Source evidence: [packaged evaluation](../reports/inspection/evaluation.json) and
[complete frozen evaluation](../reports/inspection/independent_evaluation.json).
<!-- MESHLENS_INSPECTION_RESULTS_END -->

The unchanged official Grid benchmark contains 21 normal and 57 defective images and was
already used to measure the historical AE and the selected texture detector. This release
recovers that previously selected algorithm and repeats its known benchmark. Architecture
and cutoff are unchanged and were not retuned. The original detector selection excluded
test images from fitting, selection and calibration. This run provides reproducibility
evidence rather than a newly blinded independent factory study.

Inconclusive defective images remain missed detections in recall. Inconclusive clean images
remain outside correct clean decisions. AUROC uses scored images and reports that support.
Precision describes review alerts; read it with recall, false alarms, coverage and counts.
Wilson 95% intervals represent finite-count uncertainty, not material/process variation or
retraining uncertainty.

## Runtime agreement

The recovered release's [78-source runtime check](../reports/inspection/official-runtime-parity.json)
and [18-gallery replay check](../reports/inspection/gallery-runtime-parity.json) both passed.
Canonical RGB bytes, rounded scores and decisions agreed exactly. The largest response-map
difference was `3.7826542325092305e-06`, within the recorded `2e-05` tolerance. This compares
the full Python Float64 reference and browser module's Float32 map under Node.js.

The gallery derivatives reuse official test images and add runtime cases, rather than new
physical parts. Shared decoded-pixel checks are separate from browser image decoding, DOM
interactions, physical devices, cameras and assistive-technology testing. The
[workflow guide](RUNBOOK.md) describes exact commands and report scopes.

## Operational qualification and rights

New mesh, lighting, focus, scale, viewpoint, blur and camera movement can change results.
A low score can hide a defect, and a high score can flag harmless variation. Relative map
intensities are normalized evidence, not pixel-level truth. Browser-local history is neither
authenticated nor synchronized.

Camera mode samples serially after explicit user permission. It does not measure every video
frame or establish exposure-to-result latency. Physical cameras, optics, conveyor speeds,
missed-defect costs, review capacity and long-duration operation require target-line testing.
Use the [field validation workflow](FIELD_VALIDATION.md) to freeze a representative cohort,
independent labels, artifact/threshold, operator criteria and confidence-bound acceptance checks.

Original code/documentation use MIT. MVTec AD images, masks, examples and dataset-derived
material retain CC BY-NC-SA 4.0. This benchmark does not establish commercial data rights.
See the [dataset card](DATASET_CARD.md) and [third-party notices](../THIRD_PARTY_NOTICES.md).
