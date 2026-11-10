# INDX Colour Studio design

Implemented in `frontend/src/Hybrid.svelte` and `frontend/src/hybrid.css`.
The hybrid page uses light controls and explicitly dark modelling canvases;
the upstream desktop application's theme is unchanged. No external fonts,
tracking, model uploads to third parties, or new design dependencies.

## Reference and capture

Reference: https://idither.com/job?U3ZpXAMBx&row=0
Inspected on 2026-11-10 using a fresh Firecrawl branding/text capture and a
full-page screenshot (1920 × 3624). The actual screenshot was inspected.
The reference's WebGL model was blank during the capture, so it establishes
layout and controls, not rendered model quality. This is an independent design,
not a reproduction of its proprietary assets or algorithms.

The reference uses a dark modelling surface, rounded control groups, prominent
filament swatches, collapsible advanced controls and a model-first two-column
layout. Captured branding reports background `#080A0F`, body text `#9AA6B5`,
button surfaces `#171E27` / `#171D27`, system sans-serif stacks, a 34 px heading,
4 px spacing base and roughly 8–10 px button/card radii. Values come from the
branding extraction; exact site-wide coverage was not established. Its screenshot
also shows cyan/magenta/yellow accents and dense result cards. No reference mobile,
hover or animated states were inspected.

## Our direction

Keep the model prominent, with a warmer and calmer surrounding workspace. Colours
below are implementation choices rather than extracted reference values.

| Role | Value |
| --- | --- |
| Workspace | `#F5F4F0` |
| Controls and cards | `#FCFCF9` |
| Main text | `#252A2B` |
| Secondary text | `#656D65` |
| Primary action | `#C34D27` with white text |
| Focus ring | `#C74B25` |
| Quiet border | `#DFDFD8` |
| Modelling stage | `#222B2D` to `#303A3A` |
| Stage headings | `#273032` |
| Stage text | `#EBEDE5` |

Use the existing system font stack and Lucide icons. The custom nine-cell mark
suggests discrete filament regions; it is CSS, with no downloaded image asset.
Use 6–7 px control radii and 10–11 px stage/card radii. Primary actions remain
orange; selected palette swatches always show the actual project tool colours.

## Layout and interaction

- Desktop: fixed-width 292 px control column (310 px on large desktops),
  independently scrolling settings and persistent save/preview actions.
- Project and eight physical tool assignments precede print settings. PETG is
  clearly reserved for support; unused tools stay visible and unassigned.
- Main area: project heading/status, Compare/Source/Result view switch, linked
  model canvases, palette summary, correction controls, then print summary.
- Focused source/result modes enlarge that view without replacing the project or
  changing camera state. Reset view intentionally reinitializes both cameras.
- Corrections have individual removable source/target swatch chips. Unsaved edits
  visibly mark the preview stale and label old print estimates/downloads as previous.
- Print summary uses actual native slicer estimates. Preview colour remains
  explicitly uncalibrated and physical print status remains separate.
- Below 760 px, settings follow the preview. At 480 px and below, comparison
  canvases stack; all eight assignments and actions remain available.
- Keyboard focus is visible. Buttons have accessible names; the view switch uses
  pressed-state buttons. Reduced-motion preferences suppress UI transitions.

## Assets and checks

No reference images, logos or fonts are reused. The reference screenshot and QA
screenshots remain in ignored `.local/`, not in the published source repository.
Browser checks use the real HTTPS studio and existing native test project.
Responsive widths are checked at 390, 1280 and 1920 px, including horizontal
bounds, both model previews, view switching and support-tool protection.
See `docs/Validation.json` for the recorded checks. Visual polish does not establish
better physical colour accuracy than iDither; that requires comparative test prints.
