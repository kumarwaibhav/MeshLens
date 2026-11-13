# Handoff Spec: MeshLens guided inspection

**Document scope:** the original dated UI record is retained below. The inspection-detector revision at the end updates behavior and review criteria. Current accuracy evidence is in the [active model card](../MODEL_CARD.md); earlier UI checks retain their original scope.

## Overview

A first-time visitor should understand the wire-mesh experiment, run an example, interpret the three views and fixed-limit result, and know how to obtain or capture suitable images. The shipped ONNX checkpoint and numerical contracts remain frozen.

## Layout and responsive behavior

| CSS viewport | Layout and spacing |
|---|---|
| Above 1100px | 1380px maximum page; 48px side gutters; two-column hero; 330px source column; remaining width for evidence |
| 821–1100px | 32px side gutters; 300px source column; wrapped section headings and evidence toolbar |
| 601–820px | 24px side gutters; one-column hero/workspace; image choices become a wrapping grid |
| At most 600px | 16px side gutters; brand and named navigation on separate rows; stacked content and score rows |
| Above 1600px | Bounded content width; only hero padding grows |
| Enlarged text | Intrinsic-size guards, wrapping controls and auto-fit examples prevent page overflow |

The main DOM reading order is retained at every width. No CSS `order` or `display:contents` rearranges the task. The true data table stays inside a named keyboard-focusable horizontal region on narrow screens; surrounding text reflows.

## Measurements and tokens

Use [the token reference](DESIGN_SYSTEM.md). Cards use `--space-6` padding on desktop and `--space-4` on mobile; common gaps use `--space-5`. Primary actions are at least 48px high; core controls are at least `--touch-target` (44px). Focus is a 3px `--color-focus` outline with 4px offset. Body line height is 1.6. The hero uses a fluid heading and a 1:1 image triptych rather than decorative filler.

## Components and interactions

| Element | State / trigger | Behavior |
|---|---|---|
| Start action | Click or Enter | Anchor to the inspection section |
| Sample choice | Enabled click | Cancel camera/replay, verify sample bytes, run one inspection; selected state follows current source |
| Result link | Completed result | Explicit anchor from sample choices to evidence; hidden until a result exists |
| File upload | User chooses a file | Validate bytes and dimensions, decode, inspect; focus evidence heading on success or error notice on failure |
| File picker cancel | No selected file | Preserve the existing result |
| Drop target | Drag enter/leave/drop | Visual boundary feedback; use the same validated loading path |
| Tabs | Click, Left/Right, Home/End | Change only the visualization, preserve score and result; one tab in normal tab order |
| Overlay checkbox | Toggle | Change heatmap rendering only |
| Model retry | Asset/runtime failure | Announce failure and offer initialization retry |
| Camera | Explicit request | Browser permission, one stream, serial frames, selected post-inspection delay |
| Replay | Start/stop | Visit each example once; stop cancels stale reads and prevents new records |
| History | Clear | Clear records, retain current result, show Undo beside the table |
| History Undo | Click | Merge cleared records behind any later records without duplicates; maximum 100 |
| Downloads | Click | Current JSON, model metadata JSON, CSV, PDF or labeled example ZIP |

Advanced camera/replay controls and technical metrics use native disclosures. No hover-only function or required gesture is introduced. Touch users use the same controls.

## Content and model rules

- All 18 samples are already-evaluated benchmark derivatives; no fresh accuracy claim.
- Guided examples show a normal image, a flagged defect and a missed defect.
- Ground truth is revealed after inference and is not a model input.
- Uploads and sampled frames never retrain the network.
- Input bounds: still PNG/JPEG/WebP, ≤12 MiB, 32–4096px per side, ≤16MP; white alpha compositing; full-frame 256×256 resizing.
- The score is not probability. The map is per-image relative error, not validated segmentation.
- Record filenames are limited to 512 characters and rendered with text nodes. Long values wrap; no HTML interpretation.
- History stores records, not images. New photos have no known ground truth in the app.

## Empty, loading and error cases

| Case | Required treatment |
|---|---|
| No image / slow initial download | Educational content and actual static walkthrough remain available; explain the first download; display pending controls |
| Model asset or runtime failure | No fabricated score; error with retry; local image guidance remains accessible |
| Gallery unavailable | Existing upload workflow remains available if the model initialized |
| Invalid or animated image | Describe the input error before model execution; focus error after file-picker submission |
| Stale decode / inference / camera permission | Generation guards discard old work and release superseded resources |
| Storage blocked or full | Keep current inference usable; announce the issue and allow export |
| Missing evaluation asset | Use verified metadata where available; never fabricate missing numbers |
| Long content / text enlargement | Wrap, grow height, retain all actions; table overflow is local |
| Hidden page / navigation away | Stop camera and replay |

## Motion and material

Controls use `--duration-fast` / `--ease-standard` for color transitions; processing has a spinner. Reduced motion removes animations and smooth scrolling. Glass is restricted to sticky navigation. Unsupported blur or reduced transparency uses an opaque surface. Dark appearance follows the system. There are no decorative parallax, morphing, pinch or swipe requirements.

## Accessibility and acceptance

Tab order follows reading order, with a skip link first. Disclosures remain native; the canvas has a dynamic accessible image name, and scores/decisions are text. Selected tabs and sample choices expose state. Normal notices are statuses; input failures are alerts. Upload-result focus occurs only after a user selects a file.

Run `npm test`, `npm run build`, then `node scripts/prepare_ui_review.mjs` for a local-only review fixture at `/__review/index.html`. The regular build excludes that fixture and axe. See the [accessibility audit](ACCESSIBILITY_REVIEW.md) and [revision record](../../reports/UI_REDESIGN.md) for actual verification scope. VoiceOver, NVDA, Safari/iOS, Android hardware and production camera timing are separate acceptance work; do not claim they were tested.

## Inspection detector revision (2026-11-13)

The active texture detector supplies the score and review decision. The trained AE supplies
separate reconstruction evidence. Preserve the earlier layout/token specifications where
unchanged, and apply this interaction/content contract to the detector revision.

| Component | Required behavior |
|---|---|
| Evidence tabs | Original, Detector map, Reconstruction, AE error map; one tab stop; Left/Right and Home/End; tab/panel names track the selected view. |
| Detector result | Show score, frozen threshold and version; label a low score Within calibrated range rather than an acceptance guarantee. |
| Detector map | Describe relative pattern disagreement in adjacent text and the canvas name; intensity is not probability or segmentation truth. |
| Reconstruction views | Explicitly label the historical AE; switching views does not change the active detector decision. |
| Inconclusive input | Show Input needs review with a specific reason; no numeric acceptance decision or successful inspection record. |
| Load/integrity failure | Announce the problem and offer retry; block decisions without silently substituting the AE score. |
| New-image guidance | Explain at least 256px per side, aspect ratio ≤ 1.5, supported formats and comparable mesh scale/focus/light; no hidden crop. |
| Exports/history | Retain the actual version and threshold used for each result; preserve independent evidence and replay labels. |

Wrap all four tab labels at narrow widths and enlarged text. Preserve DOM reading/focus order,
visible focus and 44px core controls. Recheck 320px, landscape, 200% text and text-spacing cases;
the earlier three-tab layout audit does not automatically verify the revised toolbar.
Loading, retry, invalid file, poor pattern, camera denial and stale-request cancellation need
keyboard and screen-reader checks. Physical devices and assistive technologies remain manual
qualification work. The benchmark's known false alarms and missed glue case stay visible.
