# Seestar Processor — v1.1 UI Overhaul Design

## Context

v1 shipped a working pipeline (Load → Background → Stretch → Export) but its window
collapsed into a single panel with both Apply buttons and **no Next/Back navigation** —
contradicting the original spec ("one step at a time, not one massive view"). After
running v1, the user asked for three things:

1. A more appealing, intuitive UI.
2. Zoom/pan on the loaded image.
3. A way to advance through the steps (the missing guided flow).

This overhaul is **presentation-only**: the processing engine, history, tools, steps,
and export are reused unchanged. It restructures `ui/` into focused widgets and adds a
dark theme.

## Decisions (from brainstorming, approved 2026-06-30)

- **Flow model:** left vertical **stepper** + large central **zoom/pan preview** +
  **Back / Next** buttons. One stage's controls visible at a time.
- **Theme:** dark, low-distraction, with a subtle accent on the active step and primary
  buttons (image is the focal point).
- **Stepper scope:** show the **full pipeline** with future stages disabled —
  `Load · Crop · Background · Color · Deconvolution · Noise · Stretch · Final Fixes · Export`.
  Functional now: Load, Background, Stretch, Export. Disabled placeholders:
  Crop, Color, Deconvolution, Noise, Final Fixes.

## Architecture (new/changed files under `seestar_processor/ui/`)

- **`pipeline.py`** — `Stage` dataclass (`id`, `label`, `enabled`, `kind`) and the ordered
  `PIPELINE` list. `kind ∈ {"load","process","stretch","export","placeholder"}`.
  Helpers: `enabled_stages()`, `next_enabled(index)`, `prev_enabled(index)`.
- **`stepper.py`** — `Stepper(QWidget)`: renders all stages; highlights the active one
  (accent), greys disabled ones (non-clickable), emits a `stageSelected(index)` signal
  when an enabled stage is clicked.
- **`image_view.py`** — `ImageView(QGraphicsView)`: shows a `QGraphicsPixmapItem`;
  wheel = zoom-to-cursor, drag = pan; `set_image(QImage)`, `fit()`, `actual_size()`;
  auto-fit on first image.
- **`step_panels.py`** — builds the right-hand control widget for the current stage:
  Load (Open button + file info), Background/Stretch (Small/Medium/Large segmented
  control + Apply), Export (TIFF/JPEG choice + Export), placeholder ("Coming soon").
- **`theme.py`** — `apply_dark_theme(app)`: a Qt stylesheet (deep-grey palette, accent
  color, consistent spacing/typography).
- **`main_window.py`** (slimmed) — owns the `Project`, tracks `current_stage`, wires
  Back/Next (move across enabled stages via `pipeline` helpers), connects
  `Stepper.stageSelected` → navigate (backward jumps call `Project.jump_back`), and
  swaps the right panel per stage. Toolbar keeps Open, Settings, Undo, Redo,
  Before/After, Export.

Reused unchanged: `core/*`, `history/*`, `tools/*`, `steps/*`, `ui/preview.to_qimage`,
`settings`, `settings_dialog`.

## Behavior

- **Navigation:** Back/Next move `current_stage` to the prev/next *enabled* stage
  (disabled stages skipped); clamps at first/last. Clicking an enabled stage in the
  stepper navigates to it; navigating backward past applied work uses the existing
  `Project.jump_back` semantics.
- **Per-stage controls:** only the current stage's panel is shown. Background's Apply is
  disabled unless `graxpert_valid(settings)` and an image is loaded.
- **Zoom/pan:** wheel zoom to cursor, drag to pan, Fit/100% buttons, fit-to-window when a
  new image loads.

## Testing

pytest-qt smoke + logic tests (no GraXpert binary needed):
- `pipeline`: `next_enabled`/`prev_enabled` skip disabled stages and clamp at ends.
- `stepper`: emits `stageSelected` only for enabled stages; disabled rows non-clickable.
- `image_view`: constructs, `set_image` sets a pixmap item, `fit()`/`actual_size()` run.
- `main_window`: Next advances past disabled stages; the right panel matches the current
  stage; the existing open→apply→undo flow still works and the step list stays in sync.
- Theme: `apply_dark_theme` runs without error and sets a non-empty stylesheet.

Visual polish itself is verified by the user running the app.

## Out of scope

Implementing the disabled stages (Crop/Color/Decon/Noise/Final Fixes) — those remain
M2+. This overhaul only restructures the UI and adds zoom/pan + dark theme.
