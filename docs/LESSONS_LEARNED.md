# MeshLens lessons learned

**Owner:** Kumar Waibhav Akshat

**Review date:** 14 November 2026

**Release reviewed:** [`5f11b39`](https://github.com/kumarwaibhav/MeshLens/commit/5f11b39fbd989e2b4f6359dc75cda062daf8b9ba)

MeshLens became a useful engineering and evaluation project, but the original idea was conventional: learn normal appearance and flag unusual image content. The work does not establish a new anomaly-detection research method or superiority to leading industrial systems. Its defensible contribution is the implementation around the method: reproducible data roles, local inference, inspectable evidence, explicit failure states, measured limitations, and a working delivery process.

The largest lesson is to settle the problem, data, evaluation and acceptance criteria before investing heavily in a polished application. A complete interface and a successful deployment did not make the original model sufficiently useful.

## What the results actually establish

The historical reconstruction autoencoder detected **11 of 57 defective benchmark images** at its frozen threshold. The active normal-lattice detector reproduced **56 of 57 detections**, with **4 alerts among 21 normal images**. These are different released methods, rather than a cosmetic threshold adjustment to the same autoencoder. The active decision and retained autoencoder evidence must be named separately.

The higher recall does not establish production readiness. The ordinary-image false-alarm rate is **19.05%**. In the defined reflected-translation stress condition, **all 21 normal images were flagged**. The same public benchmark was reused, and its previous outcomes were known during evidence recovery. The restored evaluation is therefore a reproducibility result, not a newly blind or independent factory acceptance study. The 18 gallery images also replay already-measured benchmark cases.

Sources: [active evaluation](../reports/inspection/evaluation.json), [frozen protocol](../reports/inspection/protocol.json), [active model card](MODEL_CARD.md), [historical autoencoder card](AUTOENCODER_MODEL_CARD.md), and [field acceptance procedure](FIELD_VALIDATION.md).

## Incident ledger

“Observed” below means the error or concern appeared in the development record. A correction to software or instructions is distinct from evidence that the underlying product limitation has disappeared.

| Observed issue | Cause or interpretation | Resolution and remaining lesson |
|---|---|---|
| Shared ZIP links opened an access error or failed to download. | The selected sharing/download route was unsuitable for the recipient. A specific backend cause was not established. | A directly downloadable artifact was supplied. Verify access from the recipient's route and retain a small update package beside the full archive. |
| `Expand-Archive` failed while creating `Documents\MeshLens-GitHub`; a later `Set-Location` targeted a nonexistent folder. | The proposed destination was not available. The exact Windows filesystem cause was not diagnosed. | Continue from the already-extracted folder after checking real files. Derive paths from observed locations instead of assuming a Documents directory layout. |
| An update script rejected the selected folder because `.git` was absent. | The update-package directory or outer extracted directory was supplied instead of the existing repository. | Check the project root and repository separately. Scripts should explain which folder is needed and verify it before making changes. |
| Repository fetches transferred approximately 168 MiB and took noticeable time. | Data and model assets made the repository substantial; the shown transfer also depended on available bandwidth. | Keep the research archive and lightweight updates distinct. Evaluate release assets or external dataset acquisition before adding future large files to Git history. |
| `npm run serve` could not use port 4173. | Another process already owned the port. | The server reports the conflict. Follow the documented alternative-port route; do not terminate an unidentified process merely to reclaim a default port. |
| The first screen looked empty and did not explain the task, dataset, testing or new-image route. | Owner feedback and the supplied screenshot showed an onboarding gap. No recruited usability study quantified its prevalence. | Add task-oriented guidance, real examples, dataset roles and capture instructions. Validate comprehension with first-time users, not visual approval alone. |
| “Mobile compatible” risked being inferred from one desktop view. | A screenshot cannot establish reflow, touch usability, assistive-technology support or camera behavior across devices. | Record viewport and interaction checks with their scope. Physical devices and screen readers remain separate acceptance work. |
| The historical autoencoder missed 46 of 57 defects. | The frozen model and threshold were ineffective for many benchmark defects. The record does not isolate each architectural, optimization and scoring contribution through controlled ablations. | Introduce a stronger specialized detector and retain the failed baseline honestly. Compare methods before committing to a model family. |
| Improved benchmark recall still produced false alarms and severe translation sensitivity. | The detector relies on a repeatable mesh capture domain; the stress measurements expose a narrow operating envelope. | Preserve these limitations beside headline metrics. Independent target-line evidence and nuisance-condition acceptance remain open. |
| Frozen CSV and source-file digests could fail after checkout normalization. | A digest covers exact bytes. CRLF/LF conversion can change a file without changing how its text looks. | Preserve frozen CSV bytes and force LF for ordinary text in [`.gitattributes`](../.gitattributes). Verify hashes on a fresh Windows checkout as well as Linux. |
| An interrupted verifier could leave incomplete XML or an old successful report. | Test execution, evidence parsing and publication were not sufficiently isolated in the earlier verification path. | The [verifier](../scripts/verify_project.py) writes a current failed/pending result first, validates JUnit evidence and replaces reports atomically. A past green report must never substitute for a completed current run. |
| Vercel was green while GitHub Actions was red. | Deployment status and repository test status were checked as though they were one result. | Check both systems against the exact commit. Deployment availability does not prove that source, model or dataset checks passed. |
| The timeout regression failed at `stat.exists()` after `os.kill(pid, 0)` succeeded. | The child was reaped between observations. The missing `/proc` file indicated completed cleanup, but the test incorrectly rejected it. | [`5f11b39`](https://github.com/kumarwaibhav/MeshLens/commit/5f11b39fbd989e2b4f6359dc75cda062daf8b9ba) uses bounded process-state polling, accepts both disappearance exceptions and stopped states, and still rejects a running descendant. Deterministic regressions cover these outcomes. |
| “No vulnerabilities” could be read as a permanent or universal guarantee. | Advisory scans are dated, dependency-scoped checks. They cannot establish the absence of unknown flaws or replace penetration testing. | Publish dates, exact scopes, exclusions and historical findings. Re-scan changed dependencies and report skipped packages explicitly. |
| Authorship, authentication and contributor history were easy to conflate. | Commit author metadata, the authenticated pushing account, `.mailmap` and GitHub's historical attribution are separate mechanisms. | Verify the active `kumarwaibhav` account, remote and author before pushing. Preserve history; changing display attribution does not transfer ownership of third-party data or erase earlier contributors. |

## The CI incident in detail

The failed run [`43371910619`](https://github.com/kumarwaibhav/MeshLens/actions/runs/43371910619) reported **210 Python tests passed and one failed**, while all **143 browser tests passed**. Its failing assertion was in the process-cleanup regression, not a reported model-accuracy assertion. The full dataset job was skipped because it depends on the source job.

The first correction removed the separate process-existence and file-existence observations. Review identified a second disappearance window: Linux can raise `ProcessLookupError` if a process is reaped between opening and reading its status file. The final test accepts both `FileNotFoundError` and `ProcessLookupError`, recognizes stopped process states, and gives termination a bounded interval. A sleeping or running descendant still fails the check. The real timeout integration test is explicitly Linux-specific because it inspects `/proc`.

Local verification after the correction passed **215 Python tests and 143 browser tests**, and the real cleanup case passed 12 consecutive repetitions. The subsequent hosted run [`43376785899`](https://github.com/kumarwaibhav/MeshLens/actions/runs/43376785899) passed both the source/frozen-model checks and full research-data audit. This fixes the recorded CI race; it does not resolve the detector's measured false alarms or substitute for field qualification.

The Node.js action-runtime and Ubuntu-image notices in the failed run were maintenance warnings. The detailed failure log, rather than those notices, established the cause. Old failed runs correctly remain in the history after a later correction passes.

Source: [timeout regressions](../tests/test_verification_runner.py) and [workflow dependencies](../.github/workflows/ci.yml). The committed [verification snapshot](../reports/verification.json) predates the final four regression additions; preserve its date and count rather than silently treating it as the later CI artifact.

## Security and accessibility evidence needs a date and scope

The [13 November security review](../reports/inspection/security-review.json) reports zero known advisory findings for the browser and minimal active Python runtime. It separately records development and training scopes. Its training-scope query skipped the CPU Torch package because the scanner could not match that distribution; that component must not be described as successfully audited by that query. The older [31 October summary](../reports/security-audit-summary.json) records five findings in the original training environment. These statements concern different environments and dates, so they must remain distinguishable.

The [accessibility review](design/ACCESSIBILITY_REVIEW.md) records meaningful earlier layout, contrast and automated checks, while its revision section limits how those results apply to the later detector UI. A recovered [browser smoke summary](../reports/inspection/browser-smoke-observations.md) is not a raw automation log or a physical-device study. Fresh screenshots improve presentation; they do not certify WCAG conformance or universal device compatibility.

## What to carry forward

1. **Validate the need before the architecture.** Define a user, a repeated task and a measurable cost of the present process. A familiar model applied to a familiar benchmark is insufficient novelty by itself.
2. **Benchmark early and preserve failures.** Start with simple alternatives, predeclare the holdout and show misses, false alarms, coverage and uncertainty together.
3. **Treat delivery as part of the product.** A recipient must be able to download, find the correct folder, run the software and interpret the first result without repairing assumptions in the instructions.
4. **Make evidence traceable to a commit.** Save the model, environment, input provenance, test artifacts and deployment status with exact identities.
5. **Advance in stages.** Use the [next-project playbook](NEXT_PROJECT_PLAYBOOK.md) to stop or change direction before another large build accumulates around an unproven premise.
