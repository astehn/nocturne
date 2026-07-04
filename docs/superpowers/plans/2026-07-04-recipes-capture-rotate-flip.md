# Recipes Capture Rotate/Flip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop recipes from silently dropping Rotate/Flip H/Flip V history ops — make them first-class recipe steps that replay through the same geometry engine.

**Architecture:** Add `"rotate"/"flip_h"/"flip_v"` to `recipe.py`'s manual geometry name→id map and to `deserialize_option` (rebuilding the right `CropParams` from the stage id); return `CropStep` for them in `make_step`. `batch.apply_recipe`'s generic loop replays them with no change.

**Tech Stack:** Python 3.13 (`.venv`), pytest (`QT_QPA_PLATFORM=offscreen` only for the Qt suite; recipe/batch/factory tests are headless-safe without it but the flag is harmless).

## Global Constraints

- Use `.venv/bin/python` / `.venv/bin/pytest`; system python is 3.9 and will fail.
- Rotate = 90° clockwise per op; Flip H/V are boolean — parameters derived from the stage id (history option is `""`).
- Rotate/Flip stay OUT of `STEP_NAME`/`PROCESSING_ORDER`/pipeline (geometry ops, like the existing "Crop"). Only `recipe.py` and `factory.py` change; `batch.py` does NOT change.
- Crop replay behaviour is unchanged (still autodetects content bounds); do not alter it.
- Replay must use the same `CropStep`/`apply_crop_params` engine the live app uses.
- Commit co-author trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Known flake (Qt suite only): `test_sharpen_changes_image_and_keeps_shape`.

---

### Task 1: Map and replay rotate/flip geometry ops in recipes

**Files:**
- Modify: `seestar_processor/recipe.py` (`_NAME_TO_STAGE` ~line 10-11; `deserialize_option` ~line 35-43)
- Modify: `seestar_processor/steps/factory.py` (`make_step`, after the `crop` branch ~line 21-22)
- Test: `tests/test_recipe.py`, `tests/steps/test_factory.py`, `tests/test_batch.py`

**Interfaces:**
- Produces: `_NAME_TO_STAGE` maps `"Rotate"→"rotate"`, `"Flip H"→"flip_h"`, `"Flip V"→"flip_v"`; `deserialize_option("rotate","")→CropParams(rotate=90)` (etc.); `make_step("rotate"/"flip_h"/"flip_v")→CropStep`.
- Consumes: `CropParams` (`core/crop.py`), `CropStep` (`steps/crop.py`, already imported in factory).

- [ ] **Step 1: Write the failing recipe tests**

Add to `tests/test_recipe.py`:

```python
def test_rotate_flip_entries_map_and_replay_params():
    from seestar_processor.recipe import recipe_from_entries
    rec = recipe_from_entries([("Rotate", ""), ("Flip H", ""), ("Flip V", "")])
    assert [s["stage"] for s in rec.steps] == ["rotate", "flip_h", "flip_v"]
    assert deserialize_option("rotate", "").rotate == 90
    assert deserialize_option("flip_h", "").flip_h is True
    assert deserialize_option("flip_v", "").flip_v is True


def test_mixed_geometry_recipe_keeps_order():
    from seestar_processor.recipe import recipe_from_entries
    rec = recipe_from_entries([("Rotate", ""), ("Crop", ""), ("Stretch", 0.5)])
    assert [s["stage"] for s in rec.steps] == ["rotate", "crop", "stretch"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_recipe.py -q -k "rotate_flip or mixed_geometry"`
Expected: FAIL — `rec.steps` drops Rotate/Flip (empty/short list), and `deserialize_option("rotate","")` returns the raw `""` (no `.rotate`).

- [ ] **Step 3: Extend `_NAME_TO_STAGE` and `deserialize_option`**

In `seestar_processor/recipe.py`, after the existing `_NAME_TO_STAGE["Crop"] = "crop"` line add:

```python
_NAME_TO_STAGE["Rotate"] = "rotate"
_NAME_TO_STAGE["Flip H"] = "flip_h"
_NAME_TO_STAGE["Flip V"] = "flip_v"
```

In `deserialize_option`, add these branches before the final `return value` (and after the `levels` branch):

```python
    if stage_id == "rotate":
        return CropParams(rotate=90)
    if stage_id == "flip_h":
        return CropParams(flip_h=True)
    if stage_id == "flip_v":
        return CropParams(flip_v=True)
```

(`serialize_option` needs no change: rotate/flip fall through to `return option`, storing `""`.)

- [ ] **Step 4: Run to verify the recipe tests pass**

Run: `.venv/bin/pytest tests/test_recipe.py -q`
Expected: PASS (including the existing `test_recipe_from_entries_maps_and_skips` and `test_crop_serialize_drops_bounds`).

- [ ] **Step 5: Write the failing factory test**

In `tests/steps/test_factory.py`, extend `test_make_step_types` with:

```python
    assert isinstance(make_step("rotate", s), CropStep)
    assert isinstance(make_step("flip_h", s), CropStep)
    assert isinstance(make_step("flip_v", s), CropStep)
```

(`CropStep` is already imported in that test file.)

- [ ] **Step 6: Run to verify it fails**

Run: `.venv/bin/pytest tests/steps/test_factory.py -q`
Expected: FAIL — `make_step("rotate", s)` raises `ValueError`.

- [ ] **Step 7: Add the factory branch**

In `seestar_processor/steps/factory.py`, immediately after the `if stage_id == "crop": return CropStep()` block, add:

```python
    if stage_id in ("rotate", "flip_h", "flip_v"):
        return CropStep()  # geometry ops replay through the same engine
```

- [ ] **Step 8: Run to verify the factory test passes**

Run: `.venv/bin/pytest tests/steps/test_factory.py -q`
Expected: PASS.

- [ ] **Step 9: Write the failing batch replay test**

Add to `tests/test_batch.py` (mirrors the existing `_fits`/`apply_recipe` style at the top of the file):

```python
def test_apply_recipe_replays_rotate_and_flip():
    # Non-square so a 90° rotation is observable as an H/W swap.
    data = np.zeros((20, 30, 3), np.float32)
    data[:, 0, :] = 0.9                      # bright left column (col 0)
    r = Recipe(steps=[{"stage": "rotate", "option": ""}])
    out = apply_recipe(AstroImage(data), r, Settings())
    assert out.data.shape[:2] == (30, 20)    # 90° rotate swapped H and W

    r2 = Recipe(steps=[{"stage": "flip_h", "option": ""}])
    out2 = apply_recipe(AstroImage(data), r2, Settings())
    assert out2.data.shape[:2] == (20, 30)   # flip keeps shape
    # column 0 became the last column after horizontal flip
    assert float(out2.data[:, -1, :].mean()) > float(out2.data[:, 0, :].mean())
```

- [ ] **Step 10: Run to verify it fails, then passes**

Run: `.venv/bin/pytest tests/test_batch.py -q`
Expected: it FAILS before Steps 3/7 are in (it isn't — they are, so this test should PASS now). If Steps 3 and 7 are already applied, expect PASS. (If you are running strictly TDD, note this test depends only on Steps 3+7 which are done; confirm PASS.)

- [ ] **Step 11: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass (rerun the known sharpen flake alone if it trips).

- [ ] **Step 12: Commit**

```bash
git add seestar_processor/recipe.py seestar_processor/steps/factory.py \
        tests/test_recipe.py tests/steps/test_factory.py tests/test_batch.py
git commit -m "fix: recipes capture and replay rotate/flip geometry ops"
```

---

## Self-Review

- **Spec coverage:** name→id map (Step 3), param reconstruction (Step 3), factory replay (Step 7), batch replay verified (Step 9), order preserved (Step 1 mixed test) — covered. `batch.py` correctly untouched.
- **Placeholders:** none.
- **Type consistency:** `CropParams(rotate=90)`/`CropParams(flip_h=True)`/`CropParams(flip_v=True)` and stage ids `"rotate"/"flip_h"/"flip_v"` used identically across recipe, factory, and tests.
- **Regression guard:** existing `test_recipe_from_entries_maps_and_skips` (Crop still maps, Unknown still skipped) and `test_apply_recipe_crop_uses_detected_bounds` (crop autocrop unchanged) must stay green — the new branches don't touch the crop path.
