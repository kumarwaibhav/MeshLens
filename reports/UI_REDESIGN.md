# MeshLens guided-inspection revision

**Date:** 2026-11-03 · **Base:** `2bc82316c83ef686f6975eec7b0ae0ee74e47c47`

## Changed behavior

The first screen explains wire-mesh reconstruction and shows three real frozen-model outputs. The workspace guides a normal example, a detected defect and a missed defect; known labels are revealed only after inference. A labeled 18-image ZIP, capture checklist, official dataset route, partition explanation, recall-first results and inline explanations make the project usable without prior ML knowledge.

The fixed sidebar is replaced by wrapping named navigation. Responsive source/evidence layouts, readable contrast, native controls, 44px core targets, keyboard tabs, post-upload focus, a result jump link and inline history Undo address accessibility and small-screen issues. Glass is limited to navigation with opaque fallbacks. Model weights, preprocessing, scoring and threshold remain unchanged.

## Verification completed for this revision

| Check | Result |
|---|---|
| JavaScript regression suite | 89 passed |
| New educational-asset Python checks | 3 passed |
| Actual WebAssembly inference | All 78 official test images; zero changed decisions; max score difference 3.0069225824547186e-9 versus Python ORT |
| Static production build | Passed; 18 verified sample assets |
| Browser layout + axe cases | 24 recorded cases; zero automated AA violations, no page overflow, no core target below 44px |
| Declared palette contrast | 18 representative pairs pass their text/control targets |
| Actual browser model examples | Normal 0.01567 / within range; known bent 0.02586 / review; missed bent 0.01761 / within range with explicit missed-defect explanation |
| Local image through real chooser | Produced 0.02586 / review, focused evidence, no invented ground-truth label |
| Malformed local PNG through chooser | Focused actionable alert; prior valid result retained |
| Visualization keyboard interaction | Home, End, ArrowRight selected and focused the expected tabs |
| Example ZIP content | All 18 image hashes match frozen gallery; labels, expected results, source paths and original data terms included |

All eight disclosures were expanded for 19 normal-width scans, including breakpoint boundaries. Additional cases covered text enlargement, text spacing and the dark token palette. Detailed scope and manual follow-up appear in the [accessibility audit](../docs/design/ACCESSIBILITY_REVIEW.md).

The historical full Python training/workflow suite was not rerun in this UI-only environment; the unchanged frozen assets and original audit reports remain available. Physical camera hardware, production line speed, every browser/device model and screen-reader operation are not verified by these checks. Export payload generation and example ZIP bytes have software/content checks; browser download transfer should be smoke-tested on the final deployed domain.

## Model boundary

The model remains `meshlens-ae-b8d984eef4d4`. ONNX SHA256 is `8b846f0b029c3f6c11b15f47c2ebd10aa059296959bdbbb549e7cf15c7bccfd4`.
The fixed threshold remains `0.02402208368407517`, strictly greater for review. The frozen test result is still 11 flagged defects, 46 missed defects, 21 correct normal decisions and 0 false alarms. No retraining, retuning or improvement in model accuracy is claimed.

## Reproduction

```bash
npm ci
npm test
npm run build
npm run serve
```

Optional educational-asset reproduction uses the existing inference dependencies:

```bash
python scripts/make_walkthrough.py
python -m unittest discover -s tests -p test_walkthrough_assets.py -v
```

For local browser review, run `node scripts/prepare_ui_review.mjs` after building and visit `/__review/index.html`. A clean `npm run build` removes that local-only fixture and axe from the release. It is not a production feature.

## Review documents

- [Design critique](../docs/design/DESIGN_CRITIQUE.md)
- [Research synthesis](../docs/design/RESEARCH_SYNTHESIS.md)
- [Accessibility review](../docs/design/ACCESSIBILITY_REVIEW.md)
- [Design system](../docs/design/DESIGN_SYSTEM.md)
- [Developer handoff](../docs/design/DESIGN_HANDOFF.md)
- [Primary references](../docs/design/REFERENCES.md)
