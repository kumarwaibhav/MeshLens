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
| Fit | 160 | Weight optimization; normal training patches |
| Tune | 52 | Checkpoint/candidate/score-rule comparison with fixed synthetic alterations |
| Calibration | 52 | Final normal-only threshold |
| Official test | 21 normal + 57 defective | Final frozen-model evaluation |

A deterministic seed 42 shuffle assigns official normal training images. Patches and synthetic
versions remain in their source image's role. Real defects and masks do not train the network
or select the review threshold. Held-out defects: bent 12, broken 12, glue 11, metal contamination 11,
thread 11. Small group counts imply substantial sampling uncertainty.

## Preprocessing and limits

Still PNG/JPEG/WebP inputs resolve EXIF orientation and composite transparency over opaque white
before resizing. Inputs are bounded to 32-4096 pixels on each side and 16 megapixels; upload/CLI
files are bounded to 12 MiB. Pillow bilinear resizing produces 256 x 256 Float32 CHW tensors in
`[0,1]`. Training samples 64 x 64 normal patches. Browser uploads obey the
same tensor contract, but browser/Pillow interpolation can differ slightly. Tracked opaque
examples are already at model dimensions for exact runtime comparisons.

This curated category does not establish performance on new materials, factories, optics,
scale, illumination, pose or motion. Residual maps are review evidence, not validated segmentation.

```bash
python scripts/download_data.py
python scripts/download_data.py --verify-only
python scripts/download_data.py --repair
```

The verify-only command requires the complete raw acquisition. Raw data/cache are ignored by
Git. A small licensed real example set is tracked for usable source-only model checks.
Verification never rewrites expected checksums. Explicit repair stages and verifies the pinned
source before replacing a partial or corrupt raw acquisition.
