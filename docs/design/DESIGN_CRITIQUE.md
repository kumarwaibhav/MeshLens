# Design Critique: MeshLens web experience

**Revision:** 2026-11-03 · **Baseline:** `2bc82316c83ef686f6975eec7b0ae0ee74e47c47` · **Stage:** implemented refinement

## Overall impression

The original cream-and-green palette, local inference and three evidence views gave the project a useful foundation. Its abstract headline and decorative hero occupied the first screen before explaining the material, task, or result. The revision uses real frozen-model outputs and a guided task to make the purpose visible immediately.

## Usability

| Finding | Severity | Implemented change |
|---|---|---|
| A newcomer cannot identify the inspection task from the headline | Critical | Wire-mesh explanation plus actual original/reconstruction/residual triptych |
| Dataset, training, testing and upload behavior are unclear | Critical | Four data roles, counts, plain-language scoring, and explicit inference-versus-training explanation |
| Visitors have no suitable image or instructions for finding one | Critical | Downloadable 18-image kit, official source link and new-photo capture checklist |
| Measured examples can be mistaken for independent validation | Major | Replay labels beside controls and downloads; separate independent-data guidance |
| A normal-looking result can hide a real defect | Major | Guided missed-defect example and explicit post-inference explanation |
| Tablet styles hide the JSON action and remove visible navigation labels | Major | Every record action remains available; named navigation wraps |
| On mobile, results can be far below the chosen sample | Major | Result jump link and a user-initiated upload flow that focuses evidence or an actionable error |
| Clearing history gives little recovery context | Moderate | Inline feedback and Undo beside the history table |

## Visual hierarchy

- **First attention:** a clear task statement and three actual model views, followed by one primary starting action.
- **Reading flow:** purpose → try an image → get suitable data → understand partitions → assess results → inspect the method.
- **Emphasis:** defect recall and confusion counts precede optional technical metrics. Precision is explained together with misses.
- **Whitespace:** a bounded 1380px content area replaces the fixed sidebar and empty illustration. Spacing separates tasks without isolating controls.

## Consistency

| Element | Original issue | Revision |
|---|---|---|
| Controls | Mixed tiny icon, button and tab sizes | Shared minimum 44px target and focus treatment |
| Type | Numerous 7–11px functional labels | 16px base, readable explanatory copy, rem-based scaling |
| Feedback | Green could imply defect-free approval | Text says “Within learned range”; known misses are explicit |
| Materials | Decorative styling competed with evidence | Opaque evidence cards; restrained translucent navigation |
| Vocabulary | Threshold, residual and inference assumed knowledge | Fixed-limit explanation; technical terms defined in context |

## Accessibility

The baseline had measured contrast failures in navigation, labels, normal decisions and focus outlines. The revision introduces semantic colors, native upload buttons, visible labels, keyboard tab navigation, textual results, and reflow protection. See [the measured audit](ACCESSIBILITY_REVIEW.md) for evidence and limitations.

## What works well

- Real local inference, frozen numerical contracts and cancellation safeguards were retained.
- The image views remain central; explanations help interpret them rather than replacing evidence.
- Scope and failures remain visible, including the 46 missed defects and lighting sensitivity.

## Priority recommendations

1. **Teach through a real inspection.** Implemented with three contrasting examples and adjacent explanations.
2. **Make new-data testing concrete.** Implemented with a labeled kit and capture/validation guidance.
3. **Validate accessibility beyond layout.** Automated and browser interaction checks are recorded; physical-device and assistive-technology testing remain necessary.

No conversion improvement, user-study result or production-readiness claim is inferred from this redesign.
