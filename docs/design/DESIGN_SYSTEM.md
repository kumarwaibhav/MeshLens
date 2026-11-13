# Design System: MeshLens

**Document scope:** the original dated UI record is retained below. The inspection-detector revision at the end updates behavior and review criteria. Current accuracy evidence is in the [active model card](../MODEL_CARD.md); earlier UI checks retain their original scope.

**Revision:** 2026-11-03 · **Implementation:** plain HTML, CSS and ES modules

## Principles

Make the inspection understandable, keep evidence readable, preserve user control, and show the model's measured limits. The mesh-specific signature is a real three-view image sequence, restrained green surfaces, technical numeric labels and a warm review state.

## Semantic tokens

| Token | Light / dark value | Use |
|---|---|---|
| `--color-bg` | `#f7f8f2` / `#101f1a` | Page |
| `--color-surface` | `#ffffff` / `#182b24` | Opaque cards |
| `--color-soft` | `#eef2e7` / `#20362c` | Supporting surfaces |
| `--color-ink` | `#183b33` / `#e6eee3` | Primary text |
| `--color-muted` | `#52665a` / `#b6c8b8` | Secondary text |
| `--color-primary` | `#245c48` / `#b5d9aa` | Actions and links |
| `--color-control-border` | `#7b8b78` / `#8ba58d` | Meaningful secondary-control boundaries |
| `--color-border` | `#d7ded2` / `#425a4a` | Decorative card dividers |
| `--color-focus` | `#126c68` / `#8ce5df` | Visible focus |
| `--color-warning` | `#855017` / `#f2cf91` | Review and limitation text |
| `--color-warning-bg` | `#fff4df` / `#352a1a` | Review surface |
| `--font-body-size` | `1rem` | 16px default base |
| `--font-small` | `.875rem` | 14px supporting copy |
| `--font-body` | System sans-serif stack | No external font request |
| `--font-mono` | System monospace stack | Scores and metadata |
| `--space-1` … `--space-16` | .25, .5, .75, 1, 1.25, 1.5, 2, 2.5, 3, 4rem | Spacing scale |
| `--radius-sm/md/lg` | .5 / 1 / 1.5rem | Controls, cards, hero |
| `--touch-target` | 44px | Core interactive controls |
| `--duration-fast` | 160ms | Color/background transitions |
| `--ease-standard` | `cubic-bezier(.2,.7,.3,1)` | Control transitions |
| `--content-width` | 1380px | Maximum content width |

The dark palette follows the system preference. The hero's fixed dark-green evidence surface retains its own measured light text colors. Dataset bars use categorical colors with text labels; bars are not the sole source of information. Numerical residual colors belong to the model visualization, not the interface semantic palette.

## Component inventory and completeness

| Component | Variants and states | Behavior / accessibility |
|---|---|---|
| Action | Primary, secondary, text, icon; hover/focus/disabled | Native button or link; explicit accessible name |
| Navigation | Default, current section, wrapped | Named links; no icon-only mobile navigation |
| Sample choice | Default, selected, unavailable | Native button; `aria-pressed`; known label only after inference |
| Upload | Default, drag-over, unavailable, error | Native button, labeled file input, validated header before decode |
| Visualization tabs | Selected, unselected, disabled | Roving tabindex; arrows, Home, End; named tabpanel |
| Result | Waiting, processing, within range, review, failure | Textual decision and polite live region |
| Notice | Informational, actionable error, retry | Status or alert role; no unsafe HTML |
| History | Empty, populated, cleared, restored | Semantic table, bounded storage, CSV, inline Undo |
| Disclosure | Closed, open | Native details/summary; Enter/Space |
| Camera/replay | Stopped, pending, active, error | Explicit action; serial processing; stop/cancellation guards |
| Model status | Loading, ready, failed | Text and status role, not color alone |
| Dataset/results | Loading values, available, optional detail | Defined metrics, visible limitations and provenance |

## Token audit

Semantic colors, common spacing, radii, type families, target size and motion are centralized. Some exact type sizes, component measurements, responsive thresholds and image-visualization colors are intentional local values. This is a documented web system, not a claim of 100% token coverage or an objectively scored system audit.

## Rules for extension

- Reuse semantic tokens; use warning for a review signal, never for proven defect classification.
- Keep all core actions available when layouts collapse.
- Add both textual and visual feedback; retain keyboard operation.
- Document new loading, empty, disabled and error states beside the component.
- Keep the model/checksum contract independent from presentation changes.
- Treat 44px as the project's usability target. WCAG 2.1 SC 2.5.5 is AAA, not AA.

Glass is a restrained CSS navigation treatment with opaque and reduced-transparency fallbacks. The project does not call native SwiftUI/UIKit Liquid Glass APIs.

## Inspection detector revision (2026-11-13)

Reuse the existing semantic tokens and interaction patterns. Review means a request for
human inspection; Within calibrated range is not a certified pass. Input needs review is an
inconclusive state with its own explanation, not a normal score. Readiness, loading, disabled,
retry and error states must remain explicit and readable.

Use the same tab component for Original, Detector map, Reconstruction and AE error map.
Keep the active detector's numerical provenance separate from AE visualization labels.
The numerical heatmap palette remains separate from semantic warning/success colors.

This implementation is HTML/CSS/JavaScript. Optional glass-like navigation effects require
an opaque fallback, readable contrast and reduced-motion support. Avoid stacking blur across
inspection evidence or making transparency necessary to read text. Native iOS APIs are not
part of this web implementation.
