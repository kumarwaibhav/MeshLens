# MeshLens repair and audit

Owner: **Kumar Waibhav AKshat** <kwa.waibhav@gmail.com> (`kumarwaibhav`).

## Changes

- Restored exact CRLF bytes in the calibration CSV and dataset manifest. Both SHA-256 hashes now equal the original frozen records; CSV values and model decisions were not changed.
- Disabled Git line-ending normalization for CSV files and made CSV record endings explicit in acquisition, evaluation and training writers.
- Updated current project author fields, license, UI, notebook and generated technical report to the requested name. Added a mailmap for the existing GitHub noreply identity. Historical evidence and third-party attribution remain intact.
- Enabled the full research-data job on pushes to main, after source checks.

## Fresh checks

| Check | Result |
|---|---|
| Exact pinned Python installation and pip check | Passed; no broken requirements |
| Full source/model/adversarial/CLI/dataset verification | 145 Python tests passed, zero skipped |
| App lifecycle, numerical, validation, build and server regressions | 85 JavaScript tests passed |
| Full dataset integrity | 342 images and 57 masks verified |
| Actual WebAssembly versus Python ONNX inference | All 78 official test images; zero changed decisions |
| Ruff | Passed |
| Verified static release build | Passed; 18 samples |
| Notebook | 7/7 code cells executed, zero errors |
| Python runtime advisories | 36/36 packages scanned; zero findings |
| Python development advisories | 97/97 packages scanned; zero findings |
| npm advisories | Zero findings |
| Historical original training environment | 36/36 packages scanned; five torch findings retained |
| Technical PDF | Regenerated and visually checked across 10 pages |

Machine-readable results and exact input hashes: [repair-audit.json](repair-audit.json).
Additional evidence: [verification.json](verification.json), [audit-validation.json](audit-validation.json), [wasm-parity.json](wasm-parity.json), [security-audit-summary.json](security-audit-summary.json), [npm-audit.json](npm-audit.json), and [notebook execution](../notebooks/execution_summary.json).

## Remaining limitations

The frozen model identifies 11/57 defects and misses 46. Software checks passing does not improve that recall. A previous PyTorch-version comparison recorded one calibration threshold-tie crossing; this historical failure was retained, not rerun or relabeled. No model retraining or threshold retuning was performed.

Physical camera hardware, factory throughput and unseen production data were not validated. A fresh native-browser render was attempted but Chromium download returned invalid ZIP content. The passing app lifecycle suite uses controlled browser API doubles; existing interactive-browser evidence is historical.

The original training lock preserves its historical dependency versions and five advisory findings. Use the recommended runtime/development locks, which passed the fresh scan; do not treat the historical training environment as a secure deployment environment.

## Commit and publication

New Git commits use **Kumar Waibhav AKshat <kwa.waibhav@gmail.com>** for both author and committer, without coauthor trailers. The original commit is retained, with a mailmap for its noreply identity. Third-party dataset and runtime license credits are preserved.

Remote publication is pending: Git CLI has no authenticated push credentials, and the connected GitHub commit API cannot set the requested author/committer email. No remote commit with a different email was created. Hosted Actions must be checked after pushing.
