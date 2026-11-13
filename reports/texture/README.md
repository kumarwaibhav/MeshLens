# Frozen normal lattice candidate A

The detector finds the directions in which a grid texture repeats and compares
each small area with neighboring repeats. The largest local differences form
the image score. This decision score is separate from the autoencoder's
explanatory reconstruction error.

The frozen rule is `normal-lattice-v1`, 256 × 256 RGB input, `joint` local/cell
map, and the mean of the largest 0.5% of map values. Its normal reference scale
is **0.47045176621031776**, fitted only from 160 normal fit images. Selection
used 52 tune normals and five deterministic synthetic variants per tune source;
no new choice was made during recovery.

| Synthetic family | Detected | Total | Recall |
|---|---:|---:|---:|
| Bend | 50 | 52 | 96.15% |
| Contamination | 43 | 52 | 82.69% |
| Fibre | 32 | 52 | 61.54% |
| Gap | 51 | 52 | 98.08% |
| Glue | 12 | 52 | 23.08% |
| Mean across families | | | 72.31% |

These development figures use the tune cutoff, not the final calibration
threshold, and do not measure real-defect test accuracy. All fit, development
and candidate scores are retained alongside this document.

After rule selection, 52 distinct normal calibration images set the final
threshold to **1.01049636**, the 51st order statistic at alpha 0.05. Decisions
use `score > threshold`. A score equal to the cutoff is not flagged. Scores
are quantized to eight decimal places and are nonnegative with no upper bound;
they are not probabilities.

The portable artifact is `artifacts/texture/texture-model.json`. Canonical input
uses `area-rgb8-v1` preprocessing. In Python, `score_texture` accepts float32 CHW
RGB divided by 255, and returns `(score, anomaly_map, periodicity)`. In JavaScript,
`createTextureDetector(model).score(rgb8)` accepts canonical interleaved RGB8 and
returns `score`, `anomaly_map` (Float32Array of length 65,536), `map_size` (256),
`periodicity` and `repeat_count`.

Both runtimes raise `TextureQualityError` with code `mesh-pattern-unavailable`
when fewer than two independent repeat directions can be established. Callers
must show an inconclusive inspection. This repeat check is not a general
material recognizer; another regular texture may also repeat. The weak synthetic
glue recall and lack of independently labeled target-line data prevent a
production-qualification claim.

Reproduce calibration without opening test images:

```sh
python scripts/fit_texture_detector.py \
  --frozen-candidate reports/texture/frozen-candidate.json \
  --output-dir /tmp/meshlens-texture-calibration --workers 2
```

Verify the actual browser implementation on all 52 calibration images and
12 tune-only development examples:

```sh
python scripts/verify_texture_runtime.py \
  --development /path/to/development/manifest.csv
```

The resulting `runtime-parity.json` checks exact eight-decimal scores, cutoff
decisions and repeat counts, all map pixels with the original absolute tolerance
of 0.00002, and periodicity within 1e-10. It also checks that quantization
preserves all 312 stored development decisions. This verifier never opens the
official test split. The recovered JavaScript source has a new textual hash;
its agreement with the unchanged Python rule is measured rather than assumed.
