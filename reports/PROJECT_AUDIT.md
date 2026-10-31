# MeshLens project audit

**Owner:** Kumar Waibhav AKshat <kwa.waibhav@gmail.com>

Generated from recorded evidence at 2026-10-31T19:52:14.809362+00:00.

## Conclusion

MeshLens is an industrial-mesh inspection prototype for human review. This audit checks recorded software/workflow cases; it does not establish complete coverage of every possible edge case or qualify an autonomous production inspection system.

The frozen operating point flagged **11/57 defects**, missed **46**, and flagged **0/21 normal images**. Recall is **19.30%**, AUROC 0.7594. This checkpoint cannot support an automatic material acceptance/rejection claim.

## Recorded checks

| Area | Observed result | Evidence |
|---|---|---|
| Full Python/data/model suite | 145 collected: 145 passed, 0 failures, 0 errors, 0 skipped; status passed | [verification](verification.json) |
| Source-only installed release | 145 collected: 144 passed, 0 failures, 0 errors, 1 skipped; status passed | [clean checkout](verification-clean-checkout.json) |
| PyTorch/ONNX export | 78 test images; 0 changed decisions; maximum score difference 4.29e-09 | [export](onnx_parity.json) |
| Actual WebAssembly | passed; 78 canonical real-image tensors; 0 changed decisions; maximum score difference 3.01e-09 | [WASM](wasm-parity.json) |
| Node browser/build/server contracts | 85 collected, 85 passed; 0 failures, 0 errors, 0 skipped | [verification](verification.json) |

The source-only skip is the optional raw audit when raw data is absent. Tracked real-image inference remains mandatory. Canonical-tensor parity is separate from browser decoding, DOM behavior and physical cameras.

## Severity and disposition

`fixed` identifies a corrected issue; `pass` an observed passing check; `open` a remaining limitation; `physical-unverified` a hardware/operational scenario not measured.

| ID | Severity | Disposition | Area | Finding and resolution |
|---|---|---|---|---|
| DOC-01 | medium | fixed | Clean setup | Reproduction omitted npm ci and explicit venv activation. README/RUNBOOK now install locks and local package, activate Python3.12 and install npm assets before checks. |
| DOC-02 | medium | fixed | Install scope and entrypoints | Lock installation alone does not install the local package, and inference-only dependencies cannot execute notebooks/reports. Document inference versus development environments and explicit python -m pip install --no-deps -e . |
| DOC-03 | medium | open | Native platforms | The exact Python closure is Linux x86_64; full native Windows/macOS and a physical WSL machine were not executed. State observed platform and distinguish Node application use from Linux/WSL Python development. |
| DOC-04 | high | fixed | Operational claims | Industrial subject matter and completed software do not establish production qualification. Make the human-review prototype scope and measured misses prominent. |
| MODEL-01 | critical | open | Automatic quality control | Frozen model flags11/57 defects, misses46, and flags20/21 normals after+30% brightness. Do not use for automatic acceptance/rejection; representative target-line data and substantially stronger validated performance remain necessary. |
| DOC-05 | high | physical-unverified | Camera and line timing | Physical hardware, optics, motion, line speeds and long-duration end-to-end throughput have not been tested. Separate serial sampled-camera behavior, model-call time, processing time, source timestamp and physical exposure-to-result latency. |
| DOC-06 | medium | pass | Existing archive completeness | Both saved release ZIPs passed CRC with37 required files and18 tracked examples; complete had342 images, 57 masks and source license/readme. Recheck regenerated archives after all audit code changes; exclude caches, dependencies, hosting/Git metadata and temporary files. |
| DOC-07 | medium | pass | Rights and attribution | Code authorship differs from dataset/runtime rights. Keep MIT original-code ownership, MVTec CC BY-NC-SA 4.0 notices and bundled dependency licenses; add @noble/hashes MIT notice. |
| DOC-08 | medium | pass | Strict framework diagnostic | An exact calibration tie crosses the threshold between PyTorch runtimes. Retain strict failed status, calibration1/test0 decision changes, frozen threshold and unchanged frozen ONNX inference path. |
| DOC-09 | medium | open | Unknown edge cases | A finite review/test suite does not cover every possible input, browser, hardware or operating scenario. Publish observed tests and exclusions; avoid complete edge-coverage or zero-bug guarantees. |
| DOC-10 | high | fixed | Bundled runtime license notices | The pinned ONNX Runtime Web npm package omitted LICENSE and ThirdPartyNotices files, so a best-effort optional copy did not ship the upstream notices. Check in unmodified official v1.23.2 LICENSE and complete ThirdPartyNotices with source URLs/byte hashes, require static build copies, and retain noble/hashes MIT license. |
| DOC-11 | medium | fixed | Generated environment/result exclusions | The new development-venv tutorial used .venv-dev, while the original ignore rule only covered .venv; older CLI examples wrote result files outside ignored scratch. Ignore .venv-* environments, write tutorial inspection outputs under tmp, and include development-venv/tmp paths in Git publication exclusion checks. |

### ML pipeline findings

| ID | Severity | Disposition | Finding and resolution |
|---|---|---|---|
| ML-01 | critical | open | Frozen model is not qualified for automated industrial acceptance/rejection Keep research/review-support labeling. Real camera, material, lighting, motion, missed-defect and deadline qualification require new representative data and a predefined independent evaluation; no frozen-test retuning. |
| ML-02 | high | fixed | Existing raw-data verification could bless corruption by regenerating its reference hashes Pinned canonical manifest and mask fingerprints now gate all acquisition/audits. --verify-only is read-only. --repair stages and fully verifies the archive before promotion, preserves a recovery backup, and rolls back failed/interrupted promotion. |
| ML-03 | high | fixed | Training/evaluation image loader trusted files without checking manifest digests load_images checks each file digest and decodes the same checked bytes; empty rows and escaped paths fail explicitly. |
| ML-04 | high | fixed | Inference CLI did not bind graph, threshold and calibration artifacts Frozen loader checks schema, exact tensor contract, score aliases, calibration digest/rank/normal labels, threshold equality, checkpoint-derived version and ONNX digest/size. ONNX Runtime receives the same verified bytes, closing file-replacement races. A bundled checkpoint, when present, must also match its frozen SHA256; ONNX-only inference bundles need no PyTorch file. |
| ML-05 | medium | fixed | CLI decision and malformed-image behavior diverged from review-support UI Decision now within_range; --bundle selects a frozen project root; invalid/missing/corrupt/oversized/unsupported/animated images and output failures return friendly exit2. Outputs cannot overwrite the input or frozen bundle artifacts/data/reports. |
| ML-06 | medium | fixed | Python discarded transparency while browser used a white background Python now EXIF-transposes and composites alpha over opaque white before Pillow bilinear resize. Shared still-image bounds are32..4096px per side,<=16m pixels,<=12MiB. Every one of342 opaque benchmark images was compared to the old path and is exactly unchanged. All APNG/WebP animation containers, including singleton-frame containers, are rejected by the CLI before decoding. |
| ML-07 | high | fixed | Resume payload semantic validation was incomplete Resume validates consecutive finite history, best error, current/best parameter names/shapes/dtypes/finiteness, AdamW steps20*epoch, LR schedule, moments and RNG states before restoring process state. Original full26epoch payload passes unchanged. Legacy compact reuse is restricted to its exact original checkpoint and manifest digest. |
| ML-08 | high | fixed | Checkpoint and export paths lacked explicit integrity/finiteness checks Checkpoint loader hashes and loads the same bytes using weights_only=True, validates configuration and finite state, and wraps unsafe/corrupt payload failures as ValueError. Export requires the frozen checkpoint digest and valid calibration metadata, writes a temporary graph, and promotes after parity succeeds. |
| ML-09 | high | fixed | Selection and evaluated checkpoint were not explicitly bound Selection loader checks manifest digest, four planned comparisons, recorded winner rule and exclusion flags. Evaluation compares selected candidate configuration and exact tensors against the final checkpoint before calibration/test loading. |
| ML-10 | medium | fixed | Manifest and archive schema admitted ambiguous paths/categories Reject duplicate archive targets, unsafe member types, traversal, Windows paths, excess count/size; require canonical manifest schema/paths and matching label/category/mask relationships. |
| ML-11 | medium | fixed | evaluate/export --help could execute expensive or mutating work Both now handle --help without doing evaluation/export and reject unknown options before work. |
| ML-12 | medium | open | Cross-runtime resizing and benchmark timing do not establish factory performance Use identically preprocessed tracked samples for parity. Treat reported latency as environment-specific inference timing, not a line-rate or deadline guarantee. Data remain CC-BY-NC-SA-4.0; original code licensing does not replace data rights. |

### Frontend/build/server findings

| ID | Severity | Disposition | Finding and resolution |
|---|---|---|---|
| WEB-01 | high | fixed | The browser created sessions from a URL without verifying the recorded model digest; sample digests were ignored. Build a coherent release manifest; verify sizes and SHA256 of metadata, graph, evaluation and gallery bytes; verify each sample before decoding. Same-host digests detect corruption and mixed releases, not malicious replacement of all files. |
| WEB-02 | high | fixed | Metadata and runtime input/output tensor names, dtype and fixed shapes were insufficiently validated. Require the frozen shared image/score contract and validate both session and actual output tensor contracts before recording decisions. |
| WEB-03 | high | fixed | An earlier in-flight result could publish after a newer image was selected. Capture source pixels, session and image generation; discard invalidated work before and after inference and dispose every tensor. |
| WEB-04 | high | fixed | Stopping a replay did not invalidate its pending sample fetch/decode. Abort pending fetches and invalidate image/replay generations; no late history entry after cancellation. |
| WEB-05 | high | fixed | Stopped playback could reactivate controls and a stale permission rejection could stop a newer stream. Check the media generation after every asynchronous operation; stop only the captured stale stream and expose pending-camera cancellation. |
| WEB-06 | medium | fixed | Empty streams and ended tracks were accepted or ignored. Require live video tracks, stop on disconnect or inference failure, release tracks on stop/hide and keep one inference at a time. |
| WEB-07 | high | fixed | Image dimensions were checked after native decoding could allocate memory. Check PNG/JPEG/WebP signatures, bounded container lengths and dimensions before bitmap allocation; reject animated containers, unsupported types and oversized inputs. Native decoding remains required to validate pixel data. |
| WEB-08 | high | fixed | Invalid output shapes or failed attempts could leave an earlier decision visible/downloadable. Clear the previous decision, score and downloadable result as soon as reinspection starts; mark cancelled work without recording a new decision. Reject nonfinite, out-of-range, incorrect dtype/shape/length output; retain only completed history records. |
| WEB-09 | medium | fixed | Stored records were weakly checked for dates, scores, decisions and filename size. Validate deserialized history; render filenames as text and neutralize CSV formulas. A quota failure keeps the current result and export available. |
| WEB-10 | high | fixed | Copying into an existing output left stale files and could leave a partial failed build. Validate all frozen artifacts before staging, publish a fresh directory with rollback, clean stale outputs and refuse source-directory replacement or symlinked public inputs. |
| WEB-11 | medium | fixed | The browser app lacked a Node-only local serving entry point. Add a loopback static server with GET/HEAD, exact MIME types, true404/405 responses, traversal/dotfile/symlink protection and friendly startup errors. |
| WEB-12 | medium | fixed | Camera sampling and model-call time could be mistaken for full-frame real-time throughput. Expose a serial250/1000/2500 ms post-inference delay, source_timestamp, processing_ms and inference_ms; document their boundaries. Physical exposure-to-result throughput remains unmeasured. |
| WEB-13 | medium | fixed | The npm runtime package omitted upstream license files. Bundle unmodified official ONNX Runtime v1.23.2 LICENSE/ThirdPartyNotices and nobleMIT license with the static release. |

## Detailed audit evidence

- [Adversarial coverage, corrected failures and exclusions](audit-validation.json)
- [Dataset, training, export and CLI audit](audit-ml.json)
- [Frontend, build and server audit](audit-web.json)
- [Observed browser interactions](browser-ui-checks.json)
- [Documentation and workflow audit](audit-documentation.json)

## Framework boundary diagnostic

The same checkpoint was compared on 130 calibration/test images across PyTorch 2.9.0+cpu and 2.14.1+cpu. Strict decision parity is **failed**; maximum score difference 3.52e-10; changed decisions by split {'calibration': 1, 'test': 0}. A calibration score exactly equal to the original frozen threshold crosses it after a tiny floating-point change. The threshold was not retuned. Numerical tolerances do not alter the strict greater-than rule. All official test decisions are unchanged. Browser/default CLI use the frozen ONNX graph. This does not assert identical weights after retraining.

## Data and training boundary

The source image is the split unit: 160 normal fit, 52 normal tune, 52 normal calibration, and 78 official test images (21 normal/57 defective). Patches remain within source roles. Fixed synthetic tune alterations are development proxies; real test defects/masks do not choose weights or threshold. Candidate histories, checkpoint hashes, selection, calibration scores and per-image predictions remain recorded. Default training reuses matching completed candidates or resumes matching state. Fresh optimization uses a separate copy, as described in the [workflow guide](../docs/RUNBOOK.md). Short training smoke tests exercise code; they do not replace the release quality evaluation.

## Camera and industrial limits

Camera inspection is serial and sampled, with selectable 250/1000/2500 ms delay after completed inspections (default 1000 ms). Ideal cadence bounds before processing overhead are 4/1/0.4Hz. This is not full-video-FPS processing or a real-time control guarantee. Source timestamp is after decoding at source selection; processing time covers animation-frame wait, preprocessing, inference and scoring, excluding file decode/final DOM paint. Model-call time measures session.run only. Mock streams verify software lifecycle, not physical hardware.

At 130% brightness, 20/21 normal images triggered false alarms. Optics, motion, scale, pose, materials, line speed, drift and long-duration operation need independent representative measurements. Residuals are review evidence, not validated segmentation or defect probabilities.

## Delivery, rights and audience

Both archives contain one MeshLens root with source, locks, scripts, trained assets, 18 real examples, reports, tests and executed notebook. GitHub output excludes raw data/dist. Complete output includes 342 images, 57 masks, source license/readme and static dist. Git/hosting metadata, dependencies, venvs, caches and temporary files are excluded. Final archives receive CRC and critical embedded-file hash checks after packaging.

Original code/documentation: Kumar Waibhav AKshat, MIT. Dataset: MVTec Software GmbH and original authors, CC BY-NC-SA 4.0. Runtime notices remain intact. Advisory scans are dated named-scope checks, not security certification. The hosted preview remains owner-private.

## Unknown coverage

- Physical camera hardware, optics, motion and target-line throughput
- Full native Windows/macOS Python dependency installation and a particular WSL machine
- Every browser/device/codec variant
- Long-duration resource behavior and high-rate capture
- Factory generalization, drift and industrial acceptance criteria
- Native operating-system file picker was not reverified in the cloud browser; actual File objects are covered by VM lifecycle tests and gallery PNG decoding is observed in the browser, but arbitrary uploaded codec combinations remain bounded coverage.

No audit proves that no undiscovered bugs remain. New environments, codecs, browsers, devices and operating conditions require focused additional checks.
