# Crop — Decouple Rotate/Flip from Apply Crop — Design

**Date:** 2026-07-04
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved (autonomous — user gave standing authorization to design, build, and merge;
design presented and approved before the user stepped away).

## Motivation

In the Crop step, Rotate/Flip are **staged state**: nothing happens until you press **Apply
Crop**, which bundles bounds + rotate + flip into one operation. After applying, the crop
overlay stays armed and the flip toggles stay checked — so flipping and pressing Apply Crop
again **re-crops the image to the stale overlay** in addition to flipping. That's a real
functional break. Fix: make Rotate/Flip **immediate-action buttons** (each transforms the image
now, as its own undoable step), and make **Apply Crop do only the crop**.

## Decisions (from discussion)

- **Rotate 90° / Flip H / Flip V = immediate buttons.** Each transforms the whole current image
  right away and records **its own undoable history step**. Flip buttons are momentary (not
  sticky toggles).
- **Apply Crop crops only** (to the overlay box), also its own undoable step.
- **Overlay resets** to the new image's detected content box after every geometry op (so it's
  never left armed at a stale position).
- **History model:** each geometry op is an independent, order-preserving, individually-undoable
  step (append-only), and later *processing* steps preserve all geometry.
- **Deferred (to TODO):** a "framing/preview stretch" toggle for cropping faint linear images —
  the user will gather concrete data across stacks first.

## Scope

**In scope:** decouple rotate/flip/crop into immediate append-only geometry ops; make processing
steps preserve geometry; reset the overlay after each op; update tests. Add the preview-stretch
idea to `TODO.md` as deferred.

**Out of scope:** the preview/framing stretch (deferred); any change to the processing steps
themselves; async for geometry (fast numpy ops → synchronous).

## Architecture / changes

### `ui/pipeline.py`
- **Remove `"crop"` from `PROCESSING_ORDER`** (it is no longer a truncating "position"). Also
  remove `"crop"` from `STEP_NAME` (STEP_NAME becomes the processing steps only).
- Add `GEOMETRY_NAMES = ("Crop", "Rotate", "Flip H", "Flip V")` — the append-only geometry ops.
- The Crop **Stage** stays in `_CORE` (it's still a UI stage); only its `PROCESSING_ORDER`/
  `STEP_NAME` membership changes.

### `ui/main_window.py`
- **`apply_current`**: the `preceding` set for a processing step becomes
  `set(GEOMETRY_NAMES) | {STEP_NAME[sid] for sid in PROCESSING_ORDER[:index(stage_id)]}` — so
  applying Background/Color/etc. preserves **all** geometry entries (Crop/Rotate/Flips) and
  truncates only later *processing*. Remove the now-dead `if stage_id == "crop":
  self._setup_crop_overlay()` from the `done` callback (crop no longer routes through here).
- **New geometry engine + handlers** (all synchronous, append via `_PrecomputedStep`, then
  refresh + reset overlay):
  ```python
  def _apply_geometry(self, name, params):
      if self.project is None or self._busy:
          return
      result = self._step_for("crop").apply(self.project.current(), params)  # CropStep wraps apply_crop_params
      self.project.run_step(_PrecomputedStep(name, result), "")
      self.log_panel.append_entry(format_log_entry(name, "", None))
      self._status.setText("")
      self._refresh()
      self._setup_crop_overlay()

  def _rotate(self):  self._apply_geometry("Rotate", CropParams(rotate=90))
  def _flip_h(self):  self._apply_geometry("Flip H", CropParams(flip_h=True))
  def _flip_v(self):  self._apply_geometry("Flip V", CropParams(flip_v=True))
  ```
- **`_apply_crop`** slims to bounds-only: read `image_view.crop_bounds()`; if the box equals the
  full frame (no real crop) do nothing; else `self._apply_geometry("Crop", CropParams(bounds=
  (top, bottom, left, right)))`.
- **`_done_ids`**: mark the `crop` stage done if any geometry op was applied —
  `if any(g in applied for g in GEOMETRY_NAMES): done.add("crop")` (STEP_NAME no longer carries
  "crop").
- Wire the new callbacks into `build_panel` (`on_rotate=self._rotate`, `on_flip_h=self._flip_h`,
  `on_flip_v=self._flip_v`).

### `ui/step_panels.py` (crop branch)
- Rotate button → calls `on_rotate()` on each click (immediate; drop the staged `w.rotate` and
  the text-cycling).
- Flip H / Flip V buttons → **not checkable**; call `on_flip_h()` / `on_flip_v()` on click.
- Aspect dropdown and Apply Crop unchanged in role (aspect shapes the overlay box via
  `on_crop_change`; Apply Crop → `on_crop_apply()` crops only).
- `build_panel` gains `on_rotate`, `on_flip_h`, `on_flip_v` params; drops the `w.rotate` /
  `flip_h_btn.isChecked()` staging (the buttons are actions now). Keep `w.rotate_btn`,
  `w.flip_h_btn`, `w.flip_v_btn`, `w.apply_btn`, `w.aspect_box` attributes for tests.

### Reuse / no dead code
`CropStep` (via `_step_for("crop")` / `make_step`) stays the single geometry engine —
`CropStep.apply(img, CropParams(...))` already wraps `core.crop.apply_crop_params`, so rotate/
flip/crop all go through it. The factory entry and `test_step_for_types` remain valid.

## Data flow

Rotate/Flip button → `_rotate`/`_flip_*` → `_apply_geometry(name, params)` → CropStep applies →
append `_PrecomputedStep(name, result)` → refresh + reset overlay. Apply Crop → `_apply_crop`
→ same path with a bounds-only `CropParams`. Each is one history entry; Undo reverses one op.

## Error handling

- Geometry guarded on `project is None` / `_busy` (returns, no crash).
- Apply Crop with the box at the full frame → no-op (no junk history entry).
- Applying a processing step after geometry preserves the geometry (via the `preceding` union).

## Testing

- **pipeline** (`tests/ui/test_pipeline.py`): `PROCESSING_ORDER` no longer contains `"crop"`
  (now starts `["background", ...]`); `STEP_NAME` has no `"crop"` key; `GEOMETRY_NAMES ==
  ("Crop", "Rotate", "Flip H", "Flip V")`.
- **main_window** (`tests/ui/test_main_window.py`):
  - `_apply_geometry("Crop", CropParams(bounds=(4,20,4,20)))` changes dimensions to the box (the
    old `test_apply_crop_with_params_changes_dimensions` is rewritten to this path).
  - `_rotate()` adds a "Rotate" history entry and swaps H/W dimensions (90°).
  - **Regression:** after a crop, calling `_flip_h()` **does not change the dimensions** (flip
    doesn't re-crop) and the last entry is "Flip H".
  - A processing step after geometry preserves it: crop then `apply_current` a stretch → entries
    contain "Crop" and "Stretch", dimensions still cropped.
  - Undo after crop→rotate reverses **one** op (back to the cropped, un-rotated image).
  - `crop` stage is marked done (`_done_ids`) after any geometry op.
- **step_panels** (`tests/ui/test_step_panels.py`): the crop panel's flip buttons are **not
  checkable**; clicking rotate/flip invokes the injected `on_rotate`/`on_flip_h`/`on_flip_v`;
  Apply Crop invokes `on_crop_apply`.

## Verification (by eye, after merge)

Open an image → Crop: click Flip H → image mirrors immediately (no crop). Drag the box, Apply
Crop → crops only. Rotate 90° → rotates immediately. Undo steps back one operation at a time.
Do Background after cropping → the crop is preserved.
