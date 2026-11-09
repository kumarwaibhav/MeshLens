# Accessibility Audit: MeshLens guided inspection

**Target:** WCAG 2.1 AA · **Date:** 2026-11-03
**Method:** source review, declared-color calculations, axe-core 4.14.0, real Chromium UI interactions, and responsive iframe viewports.

## Summary

Eight baseline accessibility/usability priorities were identified and addressed. The recorded 24 final layout/axe cases have **zero automated AA violations, zero page-overflow findings, and zero undersized core targets**. This is not a full WCAG conformance certification: automated scans leave manual checks, and physical devices and assistive technologies were not tested.

The 19 ordinary viewport widths were 320, 375, 390, 599, 600, 601, 768, 819, 820, 821, 1024, 1099, 1100, 1101, 1440, 1599, 1600, 1601 and 1920 CSS pixels. All eight help/advanced disclosures were expanded for these width scans. Three further cases tested root text at 200% at 320px, WCAG text-spacing overrides at 390px, and both at 1024px. Two cases exercised the dark token palette at 390px and 1440px. A desktop-style scrollbar takes 15px from the frame's content width; the reports retain both measurements.

## Findings and remediation

### Perceivable

| # | Baseline issue | Criterion | Severity | Change |
|---|---|---|---|---|
| 1 | Secondary labels failed 4.5:1 contrast | 1.4.3 | Major | Semantic readable text colors in light/dark palettes |
| 2 | Some functional labels were only 7–11px | 1.4.4 / usability | Major | 16px base, rem text, enlarged-text QA; no assertion of a WCAG minimum font size |
| 3 | Enlarged text overflowed intrinsic grid/flex widths | 1.4.4, 1.4.10 | Major | Wrapping, minmax/intrinsic-size protection, auto-fit examples |
| 4 | Image meaning needed explanatory alternatives | 1.1.1, 1.3.1 | Moderate | Real-image alt text, dynamically named canvas, textual score/decision and view descriptions |

### Operable

| # | Baseline issue | Criterion | Severity | Change |
|---|---|---|---|---|
| 5 | Focus color was only 2.07:1 on white | 1.4.11, 2.4.7 | Major | 3px focus outline, measured contrast above 3:1 |
| 6 | Tiny controls and tablet-only hidden JSON action | 2.1.1 / usability | Major | Core targets at least 44px, all actions retained, named navigation |

### Understandable and robust

| # | Baseline issue | Criterion | Severity | Change |
|---|---|---|---|---|
| 7 | Visible upload label differed from accessible name | 2.5.3, 4.1.2 | Major | Native button; visible text supplies the accessible name |
| 8 | Upload result/errors could be outside the mobile view | 3.3.1, 3.3.2 / usability | Moderate | Adjacent instructions, post-selection focus on evidence or the actionable alert |

The first implementation scan also found brand and sample accessible-name mismatches. They were removed before the recorded final cases. Sample buttons expose selection state; the sample container has an explicit group role.

## Color contrast check

| Element | Foreground | Background | Ratio | Required | Result |
|---|---|---|---:|---:|---|
| Light body | `#183b33` | `#f7f8f2` | 11.48:1 | 4.5:1 | Pass |
| Light secondary | `#52665a` | `#ffffff` | 6.16:1 | 4.5:1 | Pass |
| Light secondary on soft | `#52665a` | `#eef2e7` | 5.43:1 | 4.5:1 | Pass |
| Primary action | `#ffffff` | `#245c48` | 7.78:1 | 4.5:1 | Pass |
| Light warning | `#855017` | `#fff4df` | 6.10:1 | 4.5:1 | Pass |
| Light focus | `#126c68` | `#ffffff` | 6.23:1 | 3:1 | Pass |
| Light focus on soft | `#126c68` | `#eef2e7` | 5.49:1 | 3:1 | Pass |
| Control boundary on soft | `#7b8b78` | `#eef2e7` | 3.18:1 | 3:1 | Pass |
| Control boundary on white | `#7b8b78` | `#ffffff` | 3.62:1 | 3:1 | Pass |
| Dark body | `#e6eee3` | `#101f1a` | 14.36:1 | 4.5:1 | Pass |
| Dark secondary | `#b6c8b8` | `#182b24` | 8.47:1 | 4.5:1 | Pass |
| Dark secondary on soft | `#b6c8b8` | `#20362c` | 7.35:1 | 4.5:1 | Pass |
| Dark action | `#142b21` | `#b5d9aa` | 9.64:1 | 4.5:1 | Pass |
| Dark warning | `#f2cf91` | `#352a1a` | 9.42:1 | 4.5:1 | Pass |
| Dark focus | `#8ce5df` | `#182b24` | 10.21:1 | 3:1 | Pass |
| Dark control boundary | `#8ba58d` | `#20362c` | 4.84:1 | 3:1 | Pass |
| Hero caption | `#c6d6bd` | `#173c34` | 7.94:1 | 4.5:1 | Pass |
| Hero chip | `#57330d` | `#f4dca8` | 8.30:1 | 4.5:1 | Pass |

Ratios use WCAG sRGB relative luminance. Decorative card dividers are distinct from meaningful control boundaries. Native checkbox/select behavior also depends on the browser. The translucent navigation is 94% opaque in light mode and 95% in dark mode; content cards remain opaque, and reduced-transparency/unsupported-blur fallbacks are defined.

## Keyboard navigation

| Element | Navigation and activation | Verification |
|---|---|---|
| Skip link and named navigation | Tab, Enter; visible focus | Semantics/source reviewed |
| Upload | Native Enter/Space activation; chooser cancel keeps prior result | Native button; real file choice checked |
| Visualization tabs | Left/Right, Home, End; one active tab stop | Real browser Home, End and ArrowRight checked; handler regression coverage retained |
| Disclosures | Tab, Enter/Space | Native details; all eight opened in browser |
| Error notice | Focus after user-selected invalid file; alert role | Real malformed PNG checked |
| History | Named focusable scroll region; native export/clear/Undo actions | Software lifecycle checks; semantic table reviewed |

## Screen-reader review

| Element | Exposed structure | Remaining work |
|---|---|---|
| Canvas | Named image inside named tabpanel | Verify actual announcements with VoiceOver/NVDA |
| Result | Polite atomic region with a textual decision | Verify timing and duplicate-announcement behavior |
| Upload failure | Focused alert with specific error text | Verify announcement order on assistive technology |
| Table | Caption, column headers, named scroll region | Test horizontal traversal on a phone and with a screen reader |

The browser accessibility tree was inspected. This is not equivalent to a VoiceOver or NVDA session.

## Manual follow-up and scope

- Test physical iOS Safari and Android Chromium, including file selection, safe areas, orientation and memory pressure.
- Test VoiceOver/NVDA, zoom using browser controls, forced colors and system reduced-transparency/motion preferences.
- The 200% test used root font resizing; it was not a physical-device Dynamic Type or actual 400% browser-zoom test. The 320px reflow case covers a relevant narrow layout.
- Dark tests applied the actual CSS dark rules through the local review fixture; no claim that OS appearance switching was exercised.
- axe incompletes include symbolic icons and table cells outside the horizontally visible region. Their palette, names, structure and text were reviewed; they are not silently counted as automated passes.
- Physical camera permission/hardware and production throughput remain outside this review.

**44×44px is this design's target. WCAG 2.1 SC 2.5.5 is Level AAA, not AA.** Inline prose links are not treated as standalone core controls in that measurement.

Raw records: [browser scans](../../reports/ui-redesign-browser-scans.json), [contrast](../../reports/ui-redesign-contrast.json).

## Primary references

- [WCAG 2.1](https://www.w3.org/TR/WCAG21/)
- [Reflow](https://www.w3.org/WAI/WCAG21/Understanding/reflow/)
- [Text spacing](https://www.w3.org/WAI/WCAG21/Understanding/text-spacing/)
- [Target size, AAA](https://www.w3.org/WAI/WCAG21/Understanding/target-size/)
- [Tabs pattern](https://www.w3.org/WAI/ARIA/apg/patterns/tabs/)
- [Apple accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- [Apple materials](https://developer.apple.com/design/human-interface-guidelines/materials)

Apple guidance informed a web interpretation. This page does not use native SwiftUI or UIKit APIs.
