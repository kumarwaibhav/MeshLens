# Browser inspection observations

The working application was exercised in Chromium on 2026-11-13 against the same restored browser sources and frozen detector. These observations were retained in the conversation before the workspace reset; this document is their recovered summary, rather than a raw browser automation log.

- The real worker reached ready state. The normal example scored 0.56232 within range; the bent example scored 9.14822 and requested review.
- The glue-008 example scored 0.97636 within range and explicitly displayed its known missed-defect label.
- Arrow keys cycled all four evidence tabs with matching selection, focus and canvas descriptions.
- A 320 CSS-pixel same-origin iframe had no horizontal page overflow. All navigation links were 44 pixels high.
- The six-row stress table scrolled locally using the keyboard and had a visible focus outline. The temporary QA page was removed.

This was a desktop browser and narrow iframe check. Physical mobile devices, screen readers, camera hardware and 400% zoom were not tested. The separate numerical parity reports cover all 78 official images and the 18 replay examples.
