# Research Synthesis: MeshLens first-visit comprehension

**Document scope:** the original dated UI record is retained below. The inspection-detector revision at the end updates behavior and review criteria. Current accuracy evidence is in the [active model card](../MODEL_CARD.md); earlier UI checks retain their original scope.

**Method:** stakeholder feedback, supplied screenshot, source inspection and experiment-record review
**Feedback contributors:** 1 project owner; no recruited participant study
**Date:** 2026-11-03

## Executive summary

The owner reported that the opening screen looked empty and did not explain the purpose, data, testing, or route to trying new images. The supplied desktop screenshot supported the observation that abstract hero copy and an illustration dominated the first view. Source review identified sparse onboarding and concrete contrast/tablet-layout issues. These observations informed an implemented redesign; they do not establish how a representative user population will behave.

## Key themes

### 1. A newcomer needs a task, not only a model interface

**Evidence:** the owner wrote, “I literally … am not understanding a single thing,” followed by questions about the project and workflow. The screenshot showed a generic headline before the evidence controls.

**Interpretation:** unfamiliar terms appear before a clear mental model.
**Opportunity:** explain choose → reconstruct → compare → review using real outputs.

### 2. Data provenance and test meaning need to be visible

**Evidence:** explicit questions about the dataset and what is being tested. The frozen project records contain distinct fit, tune, calibration and test roles.

**Interpretation:** the original presentation did not communicate the difference between developing a model, measuring it and replaying an example.
**Opportunity:** show the four partitions and explain that all 18 examples belong to the already-measured test set.

### 3. Bring-your-own-data needs a practical starting point

**Evidence:** the owner asked how someone could test new data and where to obtain it.

**Interpretation:** a file input alone does not make a domain-specific model usable.
**Opportunity:** add suitable-image guidance, a labeled download kit, an official dataset link and independent-capture instructions.

### 4. Responsive claims require evidence

**Evidence:** the owner explicitly asked about mobile and different screens. Source review found a tablet-only hidden action and small controls.

**Interpretation:** a single desktop screenshot cannot establish mobile usability.
**Opportunity:** test multiple CSS widths, enlarged text, spacing overrides, control sizes and actual interactions.

## Insights → opportunities

| Insight | Implemented opportunity | Expected impact | Effort |
|---|---|---|---|
| Purpose is unclear | Real three-view hero and short task explanation | High | Medium |
| Inputs are unfamiliar | Three-example path and downloadable labeled kit | High | Medium |
| Test results can mislead | Recall-first results and a missed-defect example | High | Medium |
| New photos need domain guidance | Capture checklist and independent-validation explanation | High | Low |
| Width checks alone miss resize issues | Text enlargement, spacing and breakpoint QA | High | Medium |

Impact labels are prioritization judgments, not measured outcomes.

## User needs to validate next

| Proposed audience | Likely need | Evidence status |
|---|---|---|
| First-time portfolio visitor | Understand the problem within the first screen | Inferred from owner feedback |
| ML learner or reviewer | Trace data roles, model output and honest failure cases | Inferred; supported by project artifacts |
| Someone trying their own mesh | Know what to capture and how to interpret the result | Directly requested |

No segment sizes or prevalence percentages are known.

## Recommendations and next research

1. Ask first-time visitors to explain the task and result in their own words.
2. Observe someone downloading an example and uploading it without guidance.
3. Check whether “within range” is correctly understood as compatible with a missed defect.
4. Test the same tasks with keyboard, VoiceOver/NVDA, and a physical small-screen device.

Record completion time, errors and comprehension before claiming a usability improvement. This revision's browser checks verify behavior and layout, not user comprehension.

## Inspection detector revision (2026-11-13)

Additional input is the project owner's accuracy concern and recorded model experiments.
It is not a new recruited-participant study. The owner questioned 11/57 defect detections,
which motivates stronger measurement and a more specialized detector, while leaving actual
first-visit comprehension to be tested with representative users.

| Observation | Product implication | Research question |
|---|---|---|
| The active method and AE have different roles | Name the detector map and AE views separately. | Can a new visitor identify which method supplies the decision? |
| High recall can coexist with false alarms | Show both rates with their support counts and limitations. | Can a visitor explain what a normal-image alert means? |
| Benchmark replays are already measured | Label examples and explain independent part collection. | Can a visitor distinguish trying the UI from validating a model? |
| Unsuitable photos need abstention | Provide an actionable input-review reason. | Can users recover with a better photo without treating rejection as a normal part? |

Separate these questions from claims about measured user success. Future usability sessions
should include narrow screens, keyboard users and people unfamiliar with anomaly detection.
