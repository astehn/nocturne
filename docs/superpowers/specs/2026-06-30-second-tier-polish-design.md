# Second-Tier Polish — Design

## Context
Four backlog polish items. Engine/flow reused; one new in-app stage (local contrast) and
an interactive compare mode in the preview.

## Decisions (approved 2026-06-30)
- **Masked saturation:** make `saturate` lightness-aware (protect highlights/stars). No new stage.
- **Local Contrast:** new post-stretch step (after Noise & Sharpen, before Star Reduction),
  CLAHE on luminance, light/medium/strong.
- **Before/After:** replace the toggle with a **draggable split divider** in the preview.
- **Target presets:** a Target dropdown in the Stretch panel that sets the slider default.

## 1. Masked saturation
`core/saturation.saturate(img, amount)`: per-pixel factor `1 + amount*(1 - lum)` where
`lum = mean over channels`. Bright pixels (lum→1) get ~no boost; shadows/midtones full.
`out = clip(lum + (data - lum) * factor, 0, 1)`. Mono unchanged (no-op). Signature unchanged.

## 2. Local Contrast (CLAHE)
- `core/local_contrast.py: enhance(img, amount)`:
  - `lum = data.mean(axis=2)` (color) or the data (mono), clipped [0,1].
  - `clahe = skimage.exposure.equalize_adapthist(lum, clip_limit=0.01)`.
  - `new_lum = lum*(1-amount) + clahe*amount`.
  - color: `ratio = new_lum / max(lum, 1e-6)`; `out = clip(data * ratio[...,None], 0, 1)`.
  - mono: `out = clip(new_lum, 0, 1)`. Preserve is_linear/metadata.
- `steps/local_contrast.py: LocalContrastStep` — options light/medium/strong → {0.3,0.6,0.9}.
- Pipeline: insert `Stage("local_contrast","Local Contrast","process")` in `_IN_APP_TAIL`
  after `noise_sharpen`, before `star_reduction`. Add to `STEP_NAME` and `PROCESSING_ORDER`.
- Panel: reuse `process` kind; add `_PROCESS_OPTIONS["local_contrast"]=["light","medium","strong"]`
  and a description. `main_window._step_for("local_contrast") -> LocalContrastStep()`.

## 3. Before/After draggable split divider
- `ui/image_view.py`: compare mode.
  - `set_compare(qimage | None)`: when given, create `_compare_item` (QGraphicsPixmapItem of
    the "before") clipped to the left of a divider via a parent `QGraphicsRectItem` with
    `ItemClipsChildrenToShape`; add a movable vertical divider handle. When None, tear it down.
  - `_split_x` defaults to image-width/2; dragging the divider updates the clip rect width.
  - `compare_active() -> bool` for tests.
- `main_window`: the existing Before/After action becomes a checkable toggle that calls
  `image_view.set_compare(to_qimage(before))` (where `before = project.before_after()[0]`) when
  checked, and `set_compare(None)` when unchecked. Remove the old whole-image swap in `_refresh`
  (the `_before_after` branch); compare is now overlay-based and independent of step rendering.

## 4. Per-target stretch presets
- `ui/step_panels.py` stretch panel: add a `Target` `QComboBox`
  (`Auto / Nebula / Galaxy / Cluster`); on change, set the aggressiveness slider to a default
  (`Auto 0.5, Nebula 0.6, Galaxy 0.4, Cluster 0.5`). Apply still emits `slider/100`.
  Expose `target_box`. A module map `STRETCH_TARGET_DEFAULTS` holds the values.

## Testing
- `core`: masked saturation — a bright (high-lum) colored pixel gains less chroma than a
  mid-lum one; mid still increases; mono no-op. `local_contrast.enhance` — changes the image,
  keeps shape/dtype/range/is_linear; mono path works.
- `ui`: stretch Target dropdown sets the slider (Nebula → 60); Local Contrast panel emits
  strength; `ImageView.set_compare(img)` → `compare_active()` True and a compare item exists,
  `set_compare(None)` tears down; pipeline in-app order includes `local_contrast`; main_window
  `_step_for("local_contrast")` is a LocalContrastStep; Before/After toggle calls set_compare.

## Out of scope
Saving compare state; non-luminance local contrast; more target types.
