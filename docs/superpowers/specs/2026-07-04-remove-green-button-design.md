# Remove Green — Dedicated Button — Design

**Date:** 2026-07-04
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — ready for implementation planning

## Motivation

Green-cast removal (SCNR) is currently a checkbox tied to the **Apply Color** button, so removing
green forces the full neutralize + white-balance. A user who is happy with the current colours
but wants green gone can't do it in isolation. Fix: **remove the checkbox and add a dedicated
"Remove Green" button** on the Color view that applies SCNR directly, as its own undoable step.

## Decisions (from discussion)

- The **"Remove green cast" checkbox is removed**; **Apply Color** does neutralize + white-balance
  only (`ColorSettings(remove_green=False)`).
- A **"Remove Green" button** on the Color view applies SCNR (green clamp) directly, as its own
  **undoable** history step, independent of Apply Color.
- Green removal is a **distinct processing op positioned right after Color** in the pipeline
  order, so later steps preserve it (using the prefix-safe truncation from the crop change).
- It is a **first-class step in the factory**, so Save Recipe / Batch capture and replay it (no
  new recipe gap).
- **Order nuance (accepted):** green sits after Color; Removing Green then re-applying Color
  supersedes the green removal (you'd click Remove Green again). This is natural — white-balance
  can re-introduce green — and matches the app's edit-earlier-truncates-later model.

## Architecture / changes

### `core/color.py`
- Add `remove_green(img: AstroImage) -> AstroImage`: SCNR average-neutral — clamp green to the
  red/blue average; mono returned unchanged.
  ```python
  def remove_green(img: AstroImage) -> AstroImage:
      if not img.is_color:
          return img.copy()
      data = img.data.astype(np.float32).copy()
      avg_rb = (data[..., 0] + data[..., 2]) / 2.0
      data[..., 1] = np.minimum(data[..., 1], avg_rb)
      return AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))
  ```
- Refactor `apply_color` to reuse it (DRY): remove the inline SCNR block; at the end build the
  result AstroImage and `if settings.remove_green: result = remove_green(result)`. Behaviour
  unchanged. `ColorSettings.remove_green` field is retained (used by apply_color + recipes).

### `steps/remove_green_step.py` (new) + `steps/factory.py`
```python
class RemoveGreenStep(Step):
    name = "Remove Green"
    def options(self): return []
    def default_option(self): return ""
    def apply(self, img, option=None):
        return remove_green(img)
```
`factory.make_step`: add `if stage_id == "remove_green": return RemoveGreenStep()`.

### `ui/pipeline.py`
- Insert `"remove_green"` into `PROCESSING_ORDER` right after `"color"`:
  `["background", "color", "remove_green", "stretch", "levels", "saturation", "noise_sharpen",
  "local_contrast", "star_reduction"]`.
- Add `STEP_NAME["remove_green"] = "Remove Green"`.
- `remove_green` is a pipeline *operation*, not a stepper Stage — no entry in `_CORE`/
  `_IN_APP_TAIL`. (An id in `STEP_NAME`/`PROCESSING_ORDER` without a Stage is fine: `_done_ids`
  may add it to the done set harmlessly, and `apply_current` never sees it because no stage has
  that id.)

### `ui/main_window.py`
- New `_remove_green()` handler (mirrors `apply_current`'s truncation for the `remove_green`
  position, using the prefix-safe `_leading_kept`):
  ```python
  def _remove_green(self) -> None:
      if self.project is None or self._busy:
          return
      idx = PROCESSING_ORDER.index("remove_green")
      preceding = set(GEOMETRY_NAMES) | {STEP_NAME[sid] for sid in PROCESSING_ORDER[:idx]}
      self.project.jump_back(self._leading_kept(self.project.entries(), preceding))
      base = self.project.current()
      result = self._step_for("remove_green").apply(base, None)
      self.project.run_step(_PrecomputedStep("Remove Green", result), "")
      self.log_panel.append_entry(format_log_entry("Remove Green", "", rms_delta(base, result)))
      self._status.setText("")
      self._refresh()
  ```
- Wire `on_remove_green=self._remove_green` into the `build_panel(...)` call.

### `ui/step_panels.py` (`stage.kind == "auto"` / Color)
- Remove the "Remove green cast" checkbox.
- "Apply Color" → `on_apply(ColorSettings())` (neutralize + white-balance; `remove_green=False`
  by default).
- Add a "Remove Green" button → `on_remove_green()`.
- `build_panel` gains an `on_remove_green=None` param. Panel attrs: keep `w.apply_btn`, add
  `w.remove_green_btn`; drop `w.remove_green_check`.

### `recipe.py` / `batch.py`
- No `serialize_option`/`deserialize_option` change needed: a `remove_green` recipe step has a
  trivial option (`""`) that falls through. `_NAME_TO_STAGE` auto-includes `"Remove Green" →
  "remove_green"` from `STEP_NAME`. `batch.apply_recipe` replays it via `make_step("remove_green")`.

## Data flow

Remove Green button → `_remove_green` → prefix-safe `jump_back` to the remove_green position →
`RemoveGreenStep.apply` (SCNR) → append `_PrecomputedStep("Remove Green", result)`. One undoable
entry; preserved by later steps; captured/replayed by recipes.

## Error handling

- Guarded on `project is None` / `_busy`. Mono image → SCNR returns it unchanged (no crash).
- No new failure modes; SCNR is a pure numeric clamp.

## Testing

- **core** (`tests/core/test_color.py`): `remove_green` clamps a green-heavy pixel's green to the
  R/B average and leaves a non-green pixel unchanged; mono returned unchanged; `apply_color` with
  `remove_green=True` still clamps green (regression — the DRY refactor preserves behaviour).
- **steps** (`tests/steps/test_new_steps.py` or similar): `RemoveGreenStep().apply(img)` clamps
  green; `make_step("remove_green")` returns a `RemoveGreenStep`.
- **pipeline** (`tests/ui/test_pipeline.py`): `PROCESSING_ORDER` contains `"remove_green"` right
  after `"color"`; `STEP_NAME["remove_green"] == "Remove Green"`.
- **main_window** (`tests/ui/test_main_window.py`): `_remove_green()` records a "Remove Green"
  undoable entry and reduces green; it is preserved after applying a later step (stretch); undo
  reverses it; the Color panel's Apply Color path uses `ColorSettings(remove_green=False)` (no
  green removal on Apply Color).
- **step_panels** (`tests/ui/test_step_panels.py`): the Color panel has a `remove_green_btn` and
  no `remove_green_check`; clicking Remove Green invokes `on_remove_green`; Apply Color invokes
  `on_apply` with a `ColorSettings` whose `remove_green` is False.
- **recipe** (`tests/test_recipe.py` / `tests/test_batch.py`): a recipe built from a "Remove
  Green" entry maps to `{"stage": "remove_green"}` and batch-replays (applies SCNR) without error.

## Verification (by eye, after merge)

Color view: "Apply Color" balances colour (no green change). "Remove Green" clamps the green cast
on its own, undoable. Save a recipe including Remove Green, batch it → green removed on each image.
