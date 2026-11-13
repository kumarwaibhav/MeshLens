# Dataset card: MVTec AD grid

## Purpose and rights

Industrial mesh-like texture anomaly detection using normal-only fitting. Dataset copyright
remains with MVTec Software GmbH and the original authors. Original MeshLens code/documentation
is separate work; the data license remains CC BY-NC-SA 4.0.

Official source: https://www.mvtec.com/research-teaching/datasets/mvtec-ad

License: https://creativecommons.org/licenses/by-nc-sa/4.0/

## Source specification and verification

The grid category contains 342 original 1024 x 1024 images and 57 defect masks: 264 normal training
images, 21 normal test images and 57 defective test images. The downloader checks the actual
current acquisition against these expected counts, validates decoded images, rejects unsafe
archive paths/links, detects duplicate source-image hashes and records per-file SHA256 values.

| Acquisition field | Pinned value |
|---|---|
| Mirror revision | `dc1c313de9de1be8e41fe6818dc43caac8601efa` |
| Archive SHA256 | `d94a9a651cbfaee22c94d06cf8fa8204a590c872362de0489eb34f1645328de8` |

The audit matches a pinned public mirror's archive hash. It does not claim byte-for-byte
comparison with a separate official download. Current-run evidence is in provenance and manifests.

## Image-level partition protocol

| Role | Normal images | Use |
|---|---:|---|
| Fit | 160 | Normal training, reference statistics and candidate fitting |
| Tune | 52 | Checkpoint/candidate/score-rule comparison with fixed synthetic alterations |
| Calibration | 52 | Final normal-only threshold |
| Official test | 21 normal + 57 defective | Final frozen-model evaluation |

A deterministic seed 42 shuffle assigns official normal training images. Patches and synthetic
versions remain in their source image's role. Real test defects and masks do not fit the models,
select the new candidate or select the review threshold. Test defects: bent 12, broken 12, glue 11, metal contamination 11,
thread 11. Small group counts imply substantial sampling uncertainty.

The accuracy-upgrade development suite contains the 52 unchanged tune images and 260
synthetic versions: one bend, gap, fibre, glue and contamination alteration per tune source.
`scripts/make_development_suite.py` records each source hash, alteration seed and resulting
image hash. These are paired development proxies. Their labels and scores are never included
in the real-defect benchmark totals.

The official test set was already used to measure the historical autoencoder and the selected
texture detector. This recovery repeats the previously selected method with its architecture
and cutoff unchanged. The original detector selection excluded these test images from fitting
and candidate selection. The recovered benchmark is reproducibility evidence rather than a
newly blinded study or an independent collection from a customer's factory.

## Preprocessing and limits

Still PNG/JPEG/WebP inputs resolve EXIF orientation and composite transparency over opaque white
before resizing. Inputs are bounded to 32-4096 pixels on each side and 16 megapixels; upload/CLI
files are bounded to 12 MiB. The inspection detector uses the versioned `area-rgb8-v1` integer
area filter in Python and JavaScript. Its input size and normalization are pinned in the
detector metadata. Both implementations apply the same filter and rounding to the same
decoded pixels. Codec decoding and orientation handling are separate verification boundaries.

The file bounds are safety limits, not evidence that an image is suitable for inspection.
The active browser also requires each side to be at least the detector's input size and
the ratio of the longer side to the shorter side to be at most 1.5. It does not crop an
unsuitable image to fit. Missing mesh repetition requests input review without a numeric
defect decision. A usable close-up still needs comparable mesh scale, focus and lighting.

The historical reconstruction autoencoder uses 256 x 256 RGB Float32 CHW tensors in `[0,1]`
and was fitted on 64 x 64 normal patches with its original bilinear preprocessing. Its visual
reconstruction and residual are separate from the active detector decision. See the
[historical model card](AUTOENCODER_MODEL_CARD.md) for that frozen experiment.

This curated category does not establish performance on new materials, factories, optics,
scale, illumination, pose or motion. Residual maps are review evidence, not validated segmentation.

```bash
python scripts/download_data.py
python scripts/download_data.py --verify-only
python scripts/download_data.py --repair
```

The verify-only command requires the complete raw acquisition. This repository tracks all
401 files in `data/raw/grid/`: 342 source images, 57 masks, `license.txt` and `readme.txt`.
Although `.gitignore` contains `data/raw/`, that rule does not remove files already tracked
by Git. Generated caches remain ignored. The separate small licensed example set supports
quick model checks without processing the complete acquisition.
Verification never rewrites expected checksums. Explicit repair stages and verifies the pinned
source before replacing a partial or corrupt raw acquisition.
