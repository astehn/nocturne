# Recipes Capture Rotate/Flip — Design

**Date:** 2026-07-04
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved — regression fix, built autonomously under standing authorization.

## Motivation

When the crop step was decoupled, Rotate / Flip H / Flip V became **separate append-only history
ops** (each `_apply_geometry(name, params)` records an entry named "Rotate"/"Flip H"/"Flip V" with
option `""`). But `recipe_from_entries` maps entry names → stage ids via `_NAME_TO_STAGE`, which
only knows `"Crop" → "crop"` — so **Rotate/Flip entries are silently dropped**. A saved recipe
that included a rotation replays the image un-rotated. This is a real correctness regression.

## Decisions

- Make Rotate / Flip H / Flip V **first-class recipe steps** with their own stage ids
  (`"rotate"`, `"flip_h"`, `"flip_v"`), mirroring the existing manual `_NAME_TO_STAGE["Crop"]`
  entry. Keep them **out of `STEP_NAME`/`PROCESSING_ORDER`/pipeline** (they are geometry ops, not
  processing stages) — exactly how "Crop" is already handled.
- Replay reuses the same geometry engine (`CropStep` / `apply_crop_params`) the live app uses, so
  a replayed rotate is identical to a live rotate.
- Each op's parameters are **derived from the stage id** on deserialize (the app only ever does
  90° per Rotate click, `flip_h`/`flip_v` are boolean), so no new data needs to be threaded
  through the empty history option. Multiple clicks = multiple entries = multiple recipe steps
  (two Rotates → 180°), preserving order and count.
- **Crop replay is unchanged** (still autodetects content bounds per image via
  `detect_content_bounds`); this fix only stops rotate/flip from being dropped. Crop-box fidelity
  is a separate, pre-existing behaviour and out of scope.

## Architecture / changes

### `recipe.py`
- Extend the manual geometry map:
  ```python
  _NAME_TO_STAGE["Rotate"] = "rotate"
  _NAME_TO_STAGE["Flip H"] = "flip_h"
  _NAME_TO_STAGE["Flip V"] = "flip_v"
  ```
- `serialize_option`: no change — these fall through to `return option` (the stored `""`); the
  stage id carries the semantics, so the recipe step is `{"stage": "rotate", "option": ""}`.
- `deserialize_option`: reconstruct the `CropParams` from the stage id:
  ```python
  if stage_id == "rotate":
      return CropParams(rotate=90)
  if stage_id == "flip_h":
      return CropParams(flip_h=True)
  if stage_id == "flip_v":
      return CropParams(flip_v=True)
  ```

### `steps/factory.py`
- `make_step` returns the geometry engine for the new ids:
  ```python
  if stage_id in ("rotate", "flip_h", "flip_v"):
      return CropStep()
  ```
  (`CropStep` is already imported.)

### `batch.py`
- **No change.** The generic loop already does
  `option = deserialize_option(sid, ...)` → `make_step(sid)` → `st.apply(img, option)`. Only the
  `if sid == "crop"` branch runs content-bounds detection; rotate/flip skip it (bounds stay
  `None`), so they transform without cropping.

## Data flow

Recipe save: `recipe_from_entries` now maps `"Rotate" → {"stage":"rotate","option":""}` (etc.),
in history order (geometry block first). Replay (`batch.apply_recipe`): `deserialize_option`
builds `CropParams(rotate=90)`, `make_step("rotate")` → `CropStep`, `apply` rotates. Order and
repetition preserved (e.g. Rotate → Crop replays rotate, then autocrops the rotated image —
matching what the user did).

## Error handling

None new. `make_step` still raises `ValueError` for genuinely unknown ids. Deserialize returns a
valid `CropParams` for every geometry id.

## Testing

- **`tests/test_recipe.py`:**
  - `recipe_from_entries([("Rotate",""),("Flip H",""),("Flip V","")])` produces steps with stages
    `["rotate","flip_h","flip_v"]` (none dropped).
  - `deserialize_option("rotate","")` → `CropParams(rotate=90)`; `"flip_h"` → `flip_h=True`;
    `"flip_v"` → `flip_v=True`.
  - A mixed recipe from `[("Rotate",""),("Crop",""),("Stretch",0.5)]` keeps all three in order.
- **`tests/steps/test_factory.py`:** `make_step("rotate"/"flip_h"/"flip_v")` each return a `CropStep`.
- **`tests/test_batch.py`:** `apply_recipe` on a non-square image with a `{"stage":"rotate"}` step
  swaps H/W (90° rotation actually applied); a `{"stage":"flip_h"}` step mirrors columns.
- Full suite green (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`).

## Verification (by eye)

Rotate/flip an image, Save Recipe, run Batch on a folder → outputs are rotated/flipped as in the
saved session (previously they came out un-rotated).
