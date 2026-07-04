# Remove Green Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Color view's "Remove green cast" checkbox with a dedicated, independently-undoable "Remove Green" button that applies SCNR on its own.

**Architecture:** Extract SCNR into a reusable `remove_green(img)` core function; wrap it in a first-class `RemoveGreenStep` positioned right after Color in the pipeline order; add a `_remove_green()` main-window handler that appends it as one undoable history step using the existing prefix-safe truncation; swap the panel checkbox for a button. Recipes capture/replay it for free (no serializer change).

**Tech Stack:** Python 3.13 (`.venv`), PySide6 (Qt), pytest / pytest-qt (`QT_QPA_PLATFORM=offscreen`), numpy.

## Global Constraints

- Use `.venv/bin/python` and `.venv/bin/pytest` — the system python is 3.9 and will fail.
- Run Qt tests headless: prefix with `QT_QPA_PLATFORM=offscreen`.
- Green removal is SCNR average-neutral: `green = min(green, (red+blue)/2)`; mono images returned unchanged.
- `remove_green` is a pipeline **operation**, positioned immediately after `"color"` in `PROCESSING_ORDER`, `STEP_NAME["remove_green"] == "Remove Green"`. It is NOT a stepper `Stage` (no entry in `_CORE`/`_IN_APP_TAIL`).
- History truncation is **prefix-safe**: geometry ops form a contiguous leading block; use the existing `MainWindow._leading_kept(entries, keep_names)` — never a total count.
- Apply Color must NOT remove green: it passes `ColorSettings()` (default `remove_green=False`).
- Commit co-author trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Known flaky test: `test_sharpen_changes_image_and_keeps_shape` — rerun alone if it trips; not a regression.

---

### Task 1: Core `remove_green` + `RemoveGreenStep` + factory

**Files:**
- Modify: `seestar_processor/core/color.py` (add `remove_green`, refactor `apply_color` to reuse it)
- Create: `seestar_processor/steps/remove_green_step.py`
- Modify: `seestar_processor/steps/factory.py:18-46` (add `remove_green` branch + import)
- Test: `tests/core/test_color.py`, `tests/steps/test_factory.py`

**Interfaces:**
- Produces: `remove_green(img: AstroImage) -> AstroImage` (core); `RemoveGreenStep` with `name = "Remove Green"`, `apply(img, option=None) -> AstroImage`; `make_step("remove_green", settings) -> RemoveGreenStep`.
- Consumes: `AstroImage` (`core/image.py`), `Step` base (`history/step.py`).

- [ ] **Step 1: Write the failing core tests**

Add to `tests/core/test_color.py`:

```python
def test_remove_green_function_clamps_green():
    from seestar_processor.core.color import remove_green
    data = np.full((8, 8, 3), 0.3, dtype=np.float32)
    data[..., 1] = 0.8  # green excess
    out = remove_green(AstroImage(data))
    assert out.data[..., 1].max() <= 0.3 + 1e-6           # clamped to (r+b)/2
    assert out.data[..., 0].max() <= 0.3 + 1e-6           # red untouched


def test_remove_green_leaves_non_green_pixel_untouched():
    from seestar_processor.core.color import remove_green
    data = np.zeros((2, 2, 3), dtype=np.float32)
    data[..., 0] = 0.5; data[..., 1] = 0.2; data[..., 2] = 0.5   # green already below avg
    out = remove_green(AstroImage(data))
    assert np.allclose(out.data[..., 1], 0.2)                     # unchanged


def test_remove_green_mono_is_noop():
    from seestar_processor.core.color import remove_green
    img = AstroImage(np.full((4, 4), 0.5, dtype=np.float32))
    out = remove_green(img)
    assert out.data.ndim == 2 and np.allclose(out.data, 0.5)


def test_remove_green_preserves_is_linear():
    from seestar_processor.core.color import remove_green
    img = AstroImage(np.full((4, 4, 3), 0.4, dtype=np.float32), is_linear=False)
    assert remove_green(img).is_linear is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/core/test_color.py -q`
Expected: FAIL with `ImportError: cannot import name 'remove_green'`.

- [ ] **Step 3: Add `remove_green` and refactor `apply_color` to reuse it**

In `seestar_processor/core/color.py`, add the function and replace the inline SCNR block. The final file body (from `def apply_color` onward) becomes:

```python
def remove_green(img: AstroImage) -> AstroImage:
    """SCNR (average neutral): clamp green to the red/blue average. Mono unchanged."""
    if not img.is_color:
        return img.copy()
    data = img.data.astype(np.float32).copy()
    avg_rb = (data[..., 0] + data[..., 2]) / 2.0
    data[..., 1] = np.minimum(data[..., 1], avg_rb)
    return AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))


def apply_color(img: AstroImage, settings: ColorSettings) -> AstroImage:
    if not img.is_color:
        return img.copy()  # nothing to balance on a single channel

    data = img.data.astype(np.float32).copy()

    if settings.neutralize_background:
        # Align each channel's background (median) to the lowest channel so the
        # background becomes colour-neutral.
        meds = [float(np.median(data[..., c])) for c in range(3)]
        target = min(meds)
        for c in range(3):
            data[..., c] = np.clip(data[..., c] - (meds[c] - target), 0.0, 1.0)

    if settings.white_balance:
        # Grey-world: scale channels so their means match.
        means = [float(data[..., c].mean()) for c in range(3)]
        gray = float(np.mean(means))
        for c in range(3):
            if means[c] > 1e-6:
                data[..., c] = np.clip(data[..., c] * (gray / means[c]), 0.0, 1.0)

    result = AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))
    if settings.remove_green:
        result = remove_green(result)
    return result
```

(`ColorSettings` and imports at the top of the file are unchanged.)

- [ ] **Step 4: Run the core tests (new + existing regression) to verify they pass**

Run: `.venv/bin/pytest tests/core/test_color.py -q`
Expected: PASS — including the existing `test_remove_green_clamps_green_excess` (proves the `apply_color` DRY refactor preserved behaviour).

- [ ] **Step 5: Write the failing step/factory tests**

Add to `tests/steps/test_factory.py` (extend the import line and `test_make_step_types`):

```python
from seestar_processor.steps.remove_green_step import RemoveGreenStep
```
and inside `test_make_step_types`, add:
```python
    assert isinstance(make_step("remove_green", s), RemoveGreenStep)
```

Add to `tests/steps/test_new_steps.py`:

```python
def test_remove_green_step_clamps_green():
    import numpy as np
    from seestar_processor.core.image import AstroImage
    from seestar_processor.steps.remove_green_step import RemoveGreenStep
    data = np.full((4, 4, 3), 0.3, dtype=np.float32)
    data[..., 1] = 0.9
    out = RemoveGreenStep().apply(AstroImage(data))
    assert out.data[..., 1].max() <= 0.3 + 1e-6
```

- [ ] **Step 6: Run to verify they fail**

Run: `.venv/bin/pytest tests/steps/test_factory.py tests/steps/test_new_steps.py -q`
Expected: FAIL with `ModuleNotFoundError: seestar_processor.steps.remove_green_step`.

- [ ] **Step 7: Create the step and wire the factory**

Create `seestar_processor/steps/remove_green_step.py`:

```python
from __future__ import annotations

from ..core.color import remove_green
from ..core.image import AstroImage
from ..history.step import Step


class RemoveGreenStep(Step):
    name = "Remove Green"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option=None) -> AstroImage:
        # SCNR green removal; option is unused (no parameters).
        return remove_green(img)
```

In `seestar_processor/steps/factory.py`, add the import alongside the others:
```python
from .remove_green_step import RemoveGreenStep
```
and add the branch after the `color` branch (line ~28):
```python
    if stage_id == "remove_green":
        return RemoveGreenStep()
```

- [ ] **Step 8: Run the step/factory tests to verify they pass**

Run: `.venv/bin/pytest tests/steps/test_factory.py tests/steps/test_new_steps.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add seestar_processor/core/color.py seestar_processor/steps/remove_green_step.py \
        seestar_processor/steps/factory.py tests/core/test_color.py \
        tests/steps/test_factory.py tests/steps/test_new_steps.py
git commit -m "feat: core remove_green SCNR function + RemoveGreenStep + factory"
```

---

### Task 2: Pipeline position, main-window handler, panel button, recipe replay

**Files:**
- Modify: `seestar_processor/ui/pipeline.py:32-45` (`STEP_NAME`, `PROCESSING_ORDER`)
- Modify: `seestar_processor/ui/main_window.py` (add `_remove_green` handler near `_apply_geometry` ~line 403; wire `on_remove_green` into `build_panel` ~line 529)
- Modify: `seestar_processor/ui/step_panels.py:41-54` (add `on_remove_green` param), `:141-157` (auto branch: drop checkbox, add button)
- Test: `tests/ui/test_pipeline.py`, `tests/ui/test_main_window.py`, `tests/ui/test_step_panels.py`, `tests/test_recipe.py`, `tests/test_batch.py`

**Interfaces:**
- Consumes: `remove_green` position via `PROCESSING_ORDER.index("remove_green")`; `RemoveGreenStep` via `self._step_for("remove_green")`; `_leading_kept`, `_PrecomputedStep`, `format_log_entry`, `rms_delta` (all already in main_window).
- Produces: `MainWindow._remove_green()`; `build_panel(..., on_remove_green=...)` with `w.remove_green_btn` (and no `w.remove_green_check`).

- [ ] **Step 1: Write the failing pipeline test**

Add to `tests/ui/test_pipeline.py`:

```python
def test_remove_green_positioned_after_color():
    from seestar_processor.ui.pipeline import PROCESSING_ORDER, STEP_NAME
    assert STEP_NAME["remove_green"] == "Remove Green"
    i = PROCESSING_ORDER.index("remove_green")
    assert PROCESSING_ORDER[i - 1] == "color"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/ui/test_pipeline.py -q`
Expected: FAIL with `KeyError: 'remove_green'`.

- [ ] **Step 3: Add `remove_green` to the pipeline order**

In `seestar_processor/ui/pipeline.py`, update the two collections:

```python
STEP_NAME = {
    "background": "Background",
    "color": "Color",
    "remove_green": "Remove Green",
    "stretch": "Stretch",
    "levels": "Levels",
    "saturation": "Saturation",
    "noise_sharpen": "Noise & Sharpen",
    "local_contrast": "Local Contrast",
    "star_reduction": "Star Reduction",
}
PROCESSING_ORDER = [
    "background", "color", "remove_green", "stretch", "levels", "saturation",
    "noise_sharpen", "local_contrast", "star_reduction",
]
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/ui/test_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Write the failing main-window tests**

Add to `tests/ui/test_main_window.py` (reuse the module's existing `_window` / `_make_fits` helpers and `_go_to_id`):

```python
def test_remove_green_records_undoable_entry_and_reduces_green(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("color")
    before = win.project.current()
    green_before = float(before.data[..., 1].mean()) if before.data.ndim == 3 else 0.0
    win._remove_green()
    names = [n for n, _ in win.project.entries()]
    assert names[-1] == "Remove Green"
    after = win.project.current()
    if after.data.ndim == 3:
        assert float(after.data[..., 1].mean()) <= green_before + 1e-6
    win.project.undo()
    assert [n for n, _ in win.project.entries()] and \
        [n for n, _ in win.project.entries()][-1] != "Remove Green"


def test_remove_green_preserved_after_later_step(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("color")
    win._remove_green()
    win._go_to_id("stretch")
    win.apply_current(0.5)
    names = [n for n, _ in win.project.entries()]
    assert "Remove Green" in names and "Stretch" in names
    assert names.index("Remove Green") < names.index("Stretch")
```

If the module's helpers are named differently (e.g. `_win`, `_fits`), match the file's existing convention — read the top of `tests/ui/test_main_window.py` first and mirror it.

- [ ] **Step 6: Run to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q -k remove_green`
Expected: FAIL with `AttributeError: 'MainWindow' object has no attribute '_remove_green'`.

- [ ] **Step 7: Add the `_remove_green` handler and wire the panel callback**

In `seestar_processor/ui/main_window.py`, add this method next to `_apply_geometry` (after the `_flip_v` handlers, ~line 421):

```python
    def _remove_green(self) -> None:
        if self.project is None or self._busy:
            return
        idx = PROCESSING_ORDER.index("remove_green")
        preceding = set(GEOMETRY_NAMES) | {
            STEP_NAME[sid] for sid in PROCESSING_ORDER[:idx]
        }
        self.project.jump_back(self._leading_kept(self.project.entries(), preceding))
        base = self.project.current()
        result = self._step_for("remove_green").apply(base, None)
        self.project.run_step(_PrecomputedStep("Remove Green", result), "")
        self.log_panel.append_entry(format_log_entry("Remove Green", "", rms_delta(base, result)))
        self._status.setText("")
        self._refresh()
```

In `_rebuild_panel` (the `build_panel(...)` call ~line 529), add the new callback argument alongside `on_rotate=...`:

```python
            on_remove_green=self._remove_green,
```

- [ ] **Step 8: Write the failing step_panels tests (rewrite the checkbox test)**

In `tests/ui/test_step_panels.py`, REPLACE `test_auto_panel_emits_color_settings_with_green` (lines ~65-74) with:

```python
def test_auto_panel_apply_color_has_no_green(qtbot):
    from seestar_processor.core.color import ColorSettings
    got = []
    w = build_panel(_stage("color"), on_apply=got.append)
    qtbot.addWidget(w)
    assert w.panel_kind == "auto"
    assert not hasattr(w, "remove_green_check")
    w.apply_btn.click()
    assert len(got) == 1 and isinstance(got[0], ColorSettings)
    assert got[0].remove_green is False


def test_auto_panel_remove_green_button_invokes_callback(qtbot):
    calls = []
    w = build_panel(_stage("color"), on_remove_green=lambda: calls.append(True))
    qtbot.addWidget(w)
    w.remove_green_btn.click()
    assert calls == [True]
```

- [ ] **Step 9: Run to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_step_panels.py -q -k "auto_panel"`
Expected: FAIL (`build_panel() got an unexpected keyword argument 'on_remove_green'` / no `remove_green_btn`).

- [ ] **Step 10: Update the panel — add param, swap checkbox for button**

In `seestar_processor/ui/step_panels.py`, add the parameter to `build_panel`'s signature (after `on_export=None,`):

```python
    on_remove_green=None,
```

Replace the `elif stage.kind == "auto":` branch (lines ~141-157) with:

```python
    elif stage.kind == "auto":
        lay.addWidget(_desc_label(
            "Automatic background neutralization and white balance."
        ))
        apply_btn = QPushButton("Apply Color")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(ColorSettings()))
        remove_green_btn = QPushButton("Remove Green")
        remove_green_btn.setEnabled(apply_enabled)
        if on_remove_green is not None:
            remove_green_btn.clicked.connect(lambda: on_remove_green())
        lay.addWidget(apply_btn)
        lay.addWidget(remove_green_btn)
        w.apply_btn = apply_btn
        w.remove_green_btn = remove_green_btn
```

(If `QCheckBox` is now unused anywhere else in the file, drop it from the imports; verify with a grep before removing.)

- [ ] **Step 11: Run the panel + main-window tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_step_panels.py tests/ui/test_main_window.py -q`
Expected: PASS.

- [ ] **Step 12: Write the failing recipe/batch replay test**

Add to `tests/test_recipe.py`:

```python
def test_remove_green_entry_maps_and_serializes():
    from seestar_processor.recipe import recipe_from_entries
    rec = recipe_from_entries([("Color", None), ("Remove Green", "")])
    stages = [s["stage"] for s in rec.steps]
    assert "remove_green" in stages
```

Add to `tests/test_batch.py` (mirror the file's existing `apply_recipe` test style — read an existing test first for the `Recipe`/`Settings`/base-image setup, then):

```python
def test_batch_replays_remove_green():
    import numpy as np
    from seestar_processor.core.image import AstroImage
    from seestar_processor.recipe import Recipe
    from seestar_processor.settings import Settings
    from seestar_processor.batch import apply_recipe
    data = np.full((4, 4, 3), 0.3, dtype=np.float32)
    data[..., 1] = 0.9
    rec = Recipe(steps=[{"stage": "remove_green", "option": ""}])
    out = apply_recipe(AstroImage(data), rec, Settings())
    assert out.data[..., 1].max() <= 0.3 + 1e-6
```

- [ ] **Step 13: Run to verify they pass (no serializer change needed)**

Run: `.venv/bin/pytest tests/test_recipe.py tests/test_batch.py -q`
Expected: PASS — `recipe_from_entries` maps `"Remove Green" → "remove_green"` automatically (via `STEP_NAME`), `serialize_option`/`deserialize_option` fall through to the trivial `""` option, and `batch.apply_recipe` replays it through `make_step`.

- [ ] **Step 14: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass (rerun `test_sharpen_changes_image_and_keeps_shape` alone if it trips — known flake).

- [ ] **Step 15: Commit**

```bash
git add seestar_processor/ui/pipeline.py seestar_processor/ui/main_window.py \
        seestar_processor/ui/step_panels.py tests/ui/test_pipeline.py \
        tests/ui/test_main_window.py tests/ui/test_step_panels.py \
        tests/test_recipe.py tests/test_batch.py
git commit -m "feat: dedicated Remove Green button (own undoable step, recipe-able)"
```

---

## Self-Review

- **Spec coverage:** core `remove_green` + DRY refactor (T1 S3), `RemoveGreenStep` + factory (T1 S7), pipeline position after Color (T2 S3), `_remove_green` handler with prefix-safe truncation (T2 S7), panel checkbox→button + Apply Color no-green (T2 S10), recipe/batch replay verified (T2 S12-13) — all covered.
- **Placeholders:** none — every code step carries full code.
- **Type consistency:** `remove_green(AstroImage)->AstroImage`, `RemoveGreenStep.apply(img, option=None)`, `make_step("remove_green")`, `PROCESSING_ORDER`/`STEP_NAME` keys, and `on_remove_green`/`remove_green_btn` names are used identically across tasks and tests.
- **Order nuance (documented, intended):** green sits after Color; applying Color after Remove Green truncates the green step (edit-earlier-truncates-later) — the user re-clicks Remove Green. Accepted in the spec.
