# Next project development playbook

**Owner:** Kumar Waibhav Akshat

**Review date:** 14 November 2026

Use this sequence to choose and develop the next project. It does not select a topic or promise a schedule. Each stage produces evidence needed for the next decision. Keep one decision log stating what was learned, what changed and why the project should continue.

## Stage plan

| Stage | Entry condition | Work and evidence | Exit condition |
|---|---|---|---|
| 1 Problem and user discovery | Several candidate problems can be described in plain language. | Identify the intended user and repeated decision; observe the current workflow; record available workarounds, error consequences and access to people who can assess a result. | A named user/task, a documented baseline and a testable benefit. Stop or narrow an idea whose value cannot be checked. |
| 2 Novelty and feasibility | The task has a defensible need. | Compare existing products, open-source projects and research methods. Identify the specific unresolved gap, permissions, deployment constraints and expected evaluation cost. | A written differentiation claim supported by comparisons, with explicit nonclaims. A different model name or interface theme alone is insufficient. |
| 3 Data and acceptance design | The gap can be measured. | Secure lawful data access and labels; record provenance, physical-entity lineage and permitted uses. Define independent development, calibration and holdout roles. Agree error costs, coverage, latency and operating conditions before experiments. | A validated data inventory, leakage controls and frozen acceptance protocol. Unresolved permission or label-quality blockers prevent model development. |
| 4 Baseline and experiment design | Data and measurement are viable. | Run a simple non-ML or statistical baseline where relevant, then a small set of justified alternatives. Track configurations, preprocessing, seeds and training cost. Select on development evidence. | A reproducible baseline and a candidate improvement that matters for the task. Document negative results; stop if added complexity offers no useful gain. |
| 5 Frozen evaluation | A candidate and its selection rationale are recorded. | Freeze code, weights, threshold, input contract and evaluation protocol. Evaluate the holdout once for the release; measure misses, false alarms, inconclusive cases, uncertainty and nuisance-condition behavior. | Results satisfy the predeclared criteria, or an explicit restricted scope is accepted. A failed holdout that changes the system requires a new untouched holdout. |
| 6 Product workflow and interaction | The candidate has a justified operating scope. | Build the shortest complete user journey, including data sourcing, loading, empty/error states, explanations, export and recovery. Test keyboard use, reflow, enlarged text and representative devices. | Intended users can complete and explain the task; acceptance records identify tested devices, accessibility methods and remaining gaps. A file picker or screenshot alone is insufficient. |
| 7 Reliable delivery and security review | The complete workflow is implemented. | Test a fresh checkout and install on supported environments; validate assets and input bounds; audit dependency scopes; exercise resource cleanup, failure recovery and safe deployment. Check CI and hosting separately for the same commit. | Reproducible build, passing required tests, dated security findings with disposition, and an observed deployment. Known limitations remain visible. |
| 8 Handoff and continuing operation | The delivered release meets its declared scope. | Publish README, architecture, model/data cards, operating guide, screenshots, incident lessons and a release inventory. Define monitoring, ownership, rollback and requalification triggers. | Another person can reproduce a result and explain its limits using the documentation. Field claims require independent acceptance evidence and continuing monitoring. |

Stages can overlap where dependencies allow, but UI polish should not postpone the first useful model comparison. Give parallel contributors bounded file ownership and shared contracts. Integrate their outputs against the same source revision before proceeding.

## Compare ideas before committing to one

For each candidate, record the same evidence: a real user problem, access to representative data, a clear gap in existing solutions, a meaningful baseline, a feasible deployment path and a way to measure value. Mark each as **demonstrated**, **partly supported** or **unresolved**. Do not let a high aggregate score hide a failed permission, feasibility or safety requirement.

Ask whether the contribution is a new method, an improved workflow, a better evaluation, or an implementation for a genuinely underserved setting. Use the category the evidence supports. A strong portfolio project can demonstrate engineering judgment without claiming research novelty; a research claim needs appropriate comparisons and controlled evidence.

## Define value in the user's units

Measure the current process before estimating savings. For an inspection task, record review time, rejected clean parts, missed defects and the cost of operating the system. For another domain, choose equivalent task-specific quantities rather than carrying over “accuracy” by habit.

One useful calculation is:

`net benefit per 1000 cases = baseline operating cost - (new operating cost + review cost + measured error cost)`

Estimate each term from observed case frequencies and agreed unit costs. Report assumptions and uncertainty; do not invent financial savings or throughput. Include inconclusive cases in review demand and keep repeated observations of the same real entity out of independent sample counts. Compare quality, latency and cost together so a tiny score improvement cannot conceal an impractical workflow.

## Release acceptance record

Each release should retain:

- The problem statement, intended users, permitted scope and acceptance criteria.
- Data ownership, license, collection lineage, labels and split manifests.
- Experiment decisions and a frozen model, threshold, preprocessing and source identity.
- Holdout results with support counts, uncertainty, coverage and failure examples.
- Test reports tied to the exact commit, including incomplete or failed executions.
- Dependency audit date, scope, skipped components and unresolved findings.
- Deployment identity, actual user-journey evidence and supported environments.
- Reproduction instructions, rollback route and conditions requiring new evaluation.

Use the [MeshLens retrospective](LESSONS_LEARNED.md) as a concrete record of why these checks exist. The goal is to discover a weak premise or delivery assumption while changing it is still inexpensive.
