# Independent field acceptance

The shipped evidence is a research benchmark. No independent target-line acceptance study has been measured. A benchmark result, gallery replay, synthetic defect or repeated camera frame cannot establish performance on a new factory line.

## Collect a held-out physical-part cohort

Before scoring, record the intended mesh/material, defect types and minimum defect sizes, cameras/lenses, resolution, working distance, lighting, orientation, line speed and permitted operating ranges. Cover each intended camera and shift, multiple capture dates and material lots, and expected nuisance conditions. Record these strata alongside the required CSV columns; this command evaluates the pooled cohort. Run separately with frozen stratum-specific criteria to substantiate each condition. There is no universal minimum number of days or cameras: every deployed condition needs representative evidence.

Use one independently labeled physical part per row. Preserve raw source bytes, camera/time/lot IDs and label reconciliation records. Keep neighboring frames, crops and transformed views of a part in the same partition. Independent human inspection or another agreed reference method must establish labels before comparing with model outputs. Reconcile uncertain labels rather than silently deleting difficult examples. Develop and recalibrate on separate parts; freeze the model, threshold, sampling protocol and acceptance criteria before opening the field holdout. If a field failure changes the model or protocol, collect a new untouched holdout for the next release.

`field/cohort.csv` is the complete frozen roster:

```csv
part_id,image_sha256,label
line-a-lot7-part001,<SHA256 of original image bytes>,0
line-a-lot7-part002,<SHA256 of original image bytes>,1
```

`field/scores.csv` contains one run and optional inconclusive records:

```csv
run_id,part_id,image_sha256,label,status,score
line-a-run1,line-a-lot7-part001,<same source SHA256>,0,scored,0.5
line-a-run1,line-a-lot7-part002,<same source SHA256>,1,inconclusive,
```

Labels are `0` clean and `1` defective. A scored result needs a finite nonnegative score. Missing and explicit inconclusive records stay in the full cohort denominators. Input-quality rejection and model unavailability are inconclusive, never clean decisions. This command consumes recorded scores; it does not train or independently rerun the detector.

## Freeze run provenance and criteria

Create `field/run.json` with this schema. SHA256 values describe actual file bytes, including line endings. Replace every placeholder. Values below illustrate an acceptance policy; they are not an approved factory specification or a measured result.

```json
{
  "schema_version": 1,
  "dataset": {
    "dataset_id": "line-a-independent-holdout",
    "role": "field_holdout",
    "source_kind": "target_line_capture",
    "held_out_from_development": true,
    "one_record_per_part": true,
    "capture_scope": "material, cameras, lens, shifts, lots, light and speed",
    "label_method": "independent physical inspection and reconciliation",
    "collection_start": "2026-11-10",
    "collection_end": "2026-11-11",
    "manifest_sha256": "<cohort.csv SHA256>"
  },
  "run": {
    "run_id": "line-a-run1",
    "model_version": "<detector.json model_version>",
    "artifact_sha256": "<model file SHA256>",
    "metadata_sha256": "<detector.json SHA256>",
    "records_sha256": "<scores.csv SHA256>",
    "threshold": 1.0,
    "decision_rule": "score > threshold",
    "protocol_frozen_at": "2026-11-09T09:00:00+00:00",
    "scored_at": "2026-11-12T09:00:00+00:00"
  },
  "acceptance": {
    "confidence_level": 0.95,
    "min_clean_parts": 100,
    "min_defect_parts": 100,
    "min_recall_lower_bound": 0.95,
    "max_clean_review_upper_bound": 0.05,
    "min_class_coverage": 1.0
  }
}
```

Choose counts and bounds from missed-defect cost, review capacity and required uncertainty. Even 100/100 detections has a 95% two-sided Wilson lower bound of about 96.30%, rather than 100%. Plan each defect family and operating stratum before capture; the pooled count alone cannot prove coverage of rare defects.

Run from the repository folder in PowerShell with Python 3.12:

```powershell
$detector = Get-Content -Raw artifacts/inspection/detector.json | ConvertFrom-Json
$artifact = Join-Path 'artifacts/inspection' $detector.export.model_file
Get-FileHash -Algorithm SHA256 $artifact, artifacts/inspection/detector.json, field/cohort.csv, field/scores.csv
python scripts/qualify_field.py --cohort-manifest field/cohort.csv --records field/scores.csv --provenance field/run.json --model-artifact "$artifact" --model-metadata artifacts/inspection/detector.json --report reports/field-qualification-run-1.json
```

`reports/` already exists. Use a new report filename per run, or omit `--report` for standard output. The command needs only Python's standard library and no server. Exit `0` means all configured checks pass, `1` means valid evidence fails a check, and `2` means invalid evidence or an output error. Existing report files are preserved.

## Interpret the report

The decision rule is strictly `score > threshold`; a tie is unflagged. Scores are not probabilities. The command verifies artifact/metadata hashes, model version and threshold, cohort/record digests, run identity, labels and collection dates. Local digests detect inconsistent bundles; they are not digital signatures or evidence that a trusted party authored a file.

Every defective part enters recall, including missing/inconclusive decisions. Clean parts needing review include detector alerts and inconclusive results. The gate checks the recall **lower** Wilson bound, clean-review **upper** Wilson bound, minimum clean/defect counts and observed coverage for both classes separately. False alarms are reported separately. No-class cases fail rather than producing a perfect rate. Wilson bounds are marginal per metric, not a joint family-wise guarantee.

Pinned benchmark hashes and original/active resized galleries are excluded automatically. Add `--exclude-manifest path/to/development.csv` for every other fitting/tuning/calibration source manifest containing a `sha256` column. Hashes catch identical bytes only; physical-part lineage and crop/augmentation tracking remain collection responsibilities. Archive raw evidence, run output and the frozen environment together. A passing report applies only to its declared capture scope and chosen criteria. Maintain human review, track drift/latency and requalify changed hardware, material, lighting or model releases.

## Dataset rights and statistical reference

MVTec's [official AD dataset page](https://www.mvtec.com/research-teaching/datasets/mvtec-ad) publishes the dataset under CC BY-NC-SA 4.0 and directs commercial-use questions to the dataset authors. The [license terms](https://creativecommons.org/licenses/by-nc-sa/4.0/) require attribution, noncommercial use and share-alike for adaptations. Preserve existing notices; code ownership does not transfer dataset rights or certify commercial deployment permissions. Obtain suitable rights for target-line collection and the chosen training assets before commercial use.

Intervals follow the [NIST Wilson confidence-interval formulation](https://itl.nist.gov/div898/handbook/prc/section2/prc241.htm). Their binomial interpretation assumes independently sampled physical parts; repeated video frames cannot justify the sample count.
