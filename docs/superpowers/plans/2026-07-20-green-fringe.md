# Remove Green Fringe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Remove Green Fringe" finishing step — a strength-controlled green-excess suppression that removes the green fringe/halo around stars without touching red, blue, or neutral tones.

**Architecture:** A pure-numpy `remove_green_fringe(img, strength)` in `nocturne/core/color.py` (green-excess SCNR scaled by strength; `strength=1` equals the existing `remove_green`) drives a new `green_fringe` pipeline stage after Saturation, wired through the same slider + live-preview + generic-commit pattern as Recover Core / Local Contrast.

**Tech Stack:** Python, NumPy, PySide6, pytest. No new third-party dependency.

## Global Constraints

- `remove_green_fringe(img: AstroImage, strength: float) -> AstroImage`; `strength` clamped to `[0,1]`; `strength == 0` is an exact no-op; mono (`not img.is_color`) is an exact no-op.
- Algorithm: `avg_rb = (R + B) / 2`; `excess = max(G - avg_rb, 0)`; `G_new = G - strength * excess`. Red and blue are never modified. Output clipped `[0,1]` float32; `is_linear`/`metadata` preserved.
- At `strength == 1`, output equals the existing `nocturne.core.color.remove_green` (average-neutral SCNR) on any image.
- Stage id `green_fringe`, display name `"Remove Green Fringe"`, panel `kind == "green_fringe"`, placed AFTER `saturation` and BEFORE `noise_sharpen` in `_IN_APP_TAIL`, `STEP_NAME`, `PROCESSING_ORDER`, and added to `POST_STRETCH_IDS`.
- Recipe option is a float (add `green_fringe` to the existing float branch).
- Follow existing patterns: step wrapper mirrors `steps/local_contrast.py`; panel + preview wiring mirror the Recover Core slider step.

---

### Task 1: Core `remove_green_fringe`

**Files:**
- Modify: `nocturne/core/color.py`
- Test: `tests/core/test_green_fringe.py`

**Interfaces:**
- Consumes: `nocturne.core.image.AstroImage`; the existing `nocturne.core.color.remove_green` (for the equivalence test).
- Produces: `remove_green_fringe(img: AstroImage, strength: float) -> AstroImage`.

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_green_fringe.py`:

```python
import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.color import remove_green_fringe, remove_green


def _px(r, g, b, h=4, w=4):
    a = np.zeros((h, w, 3), np.float32)
    a[..., 0] = r
    a[..., 1] = g
    a[..., 2] = b
    return AstroImage(a, is_linear=False)


def test_strength_zero_is_noop():
    img = _px(0.2, 0.8, 0.3)
    assert np.allclose(remove_green_fringe(img, 0.0).data, img.data)


def test_green_excess_reduced_red_blue_untouched():
    img = _px(0.2, 0.8, 0.3)                 # avg_rb = 0.25, excess = 0.55
    out = remove_green_fringe(img, 0.5).data
    assert out[0, 0, 1] < 0.8                # green pulled down
    assert np.isclose(out[0, 0, 1], 0.8 - 0.5 * 0.55)   # G - strength*excess
    assert np.isclose(out[0, 0, 0], 0.2)     # red untouched
    assert np.isclose(out[0, 0, 2], 0.3)     # blue untouched


def test_neutral_and_red_dominant_untouched():
    grey = _px(0.5, 0.5, 0.5)                # excess 0
    red = _px(0.8, 0.3, 0.4)                 # G < avg_rb -> excess 0
    assert np.allclose(remove_green_fringe(grey, 1.0).data, grey.data)
    assert np.allclose(remove_green_fringe(red, 1.0).data, red.data)


def test_strength_one_equals_remove_green():
    rng = np.random.default_rng(0)
    img = AstroImage(rng.random((16, 16, 3)).astype(np.float32), is_linear=False)
    assert np.allclose(remove_green_fringe(img, 1.0).data, remove_green(img).data)


def test_range_dtype_and_metadata():
    img = AstroImage(np.full((8, 8, 3), 0.6, np.float32),
                     is_linear=False, metadata={"k": 1})
    img.data[..., 1] = 0.9                    # green excess
    out = remove_green_fringe(img, 0.7)
    assert out.data.dtype == np.float32
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0
    assert out.is_linear is False and out.metadata == {"k": 1}


def test_mono_is_noop():
    img = AstroImage(np.full((8, 8), 0.5, np.float32))
    assert np.allclose(remove_green_fringe(img, 1.0).data, img.data)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/core/test_green_fringe.py -q`
Expected: FAIL — `ImportError: cannot import name 'remove_green_fringe'`.

- [ ] **Step 3: Write the implementation**

In `nocturne/core/color.py`, add this function directly after `remove_green` (around line 24):

```python
def remove_green_fringe(img: AstroImage, strength: float) -> AstroImage:
    """Suppress green *excess* (average-neutral SCNR scaled by `strength`).

    Reduces green only where it exceeds the red/blue average — the definition of
    a green fringe — leaving red, blue, and neutral/red/blue-dominant pixels
    untouched. `strength` 0 = no-op; `strength` 1 == `remove_green` (full
    average-neutral SCNR). Mono images are unchanged.
    """
    strength = float(np.clip(strength, 0.0, 1.0))
    if not img.is_color or strength == 0.0:
        return img.copy()
    data = img.data.astype(np.float32).copy()
    avg_rb = (data[..., 0] + data[..., 2]) / 2.0
    excess = np.maximum(data[..., 1] - avg_rb, 0.0)
    data[..., 1] = data[..., 1] - strength * excess
    return AstroImage(np.clip(data, 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/core/test_green_fringe.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add nocturne/core/color.py tests/core/test_green_fringe.py
git commit -m "feat: remove_green_fringe — strength-controlled green-excess SCNR"
```

---

### Task 2: Register the Remove Green Fringe stage

**Files:**
- Create: `nocturne/steps/green_fringe.py`
- Modify: `nocturne/steps/factory.py`
- Modify: `nocturne/ui/pipeline.py`
- Modify: `nocturne/recipe.py`
- Modify: `nocturne/ui/help_content.py`
- Test: `tests/steps/test_factory.py`, `tests/ui/test_pipeline.py`, `tests/test_recipe.py`

**Interfaces:**
- Consumes: `remove_green_fringe` (Task 1); `nocturne.history.step.Step`.
- Produces: `GreenFringeStep` (`name = "Remove Green Fringe"`, `apply(img, option)` → `remove_green_fringe`); stage id `"green_fringe"` in `path_stages()`, `STEP_NAME`, `PROCESSING_ORDER` (after `saturation`, before `noise_sharpen`), and `POST_STRETCH_IDS`; `make_step("green_fringe", ...)` → `GreenFringeStep`; recipe round-trips a float.

- [ ] **Step 1: Write / update the failing tests**

Add to `tests/steps/test_factory.py`:

```python
def test_make_step_green_fringe():
    from nocturne.steps.factory import make_step
    from nocturne.steps.green_fringe import GreenFringeStep
    from nocturne.settings import Settings
    assert isinstance(make_step("green_fringe", Settings()), GreenFringeStep)


def test_green_fringe_step_applies_strength():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.color import remove_green_fringe
    from nocturne.steps.green_fringe import GreenFringeStep
    a = np.full((8, 8, 3), 0.3, np.float32)
    a[..., 1] = 0.9
    img = AstroImage(a, is_linear=False)
    assert np.allclose(GreenFringeStep().apply(img, 0.6).data,
                       remove_green_fringe(img, 0.6).data)
    assert np.allclose(GreenFringeStep().apply(img, "").data, img.data)   # empty -> no-op
```

Update `tests/ui/test_pipeline.py`.

Replace `test_path_stages_single_linear_flow`:

```python
def test_path_stages_single_linear_flow():
    ids = [s.id for s in path_stages()]
    assert ids == [
        "load", "crop", "background", "color", "deconvolution", "stretch",
        "recover_core", "levels", "curves", "saturation", "green_fringe",
        "noise_sharpen", "local_contrast", "star_reduction", "enhancements", "export",
    ]
```

Replace the `PROCESSING_ORDER` assertion inside `test_step_name_and_order`:

```python
    assert PROCESSING_ORDER == [
        "background", "color", "remove_green", "deconvolution", "stretch",
        "recover_core", "levels", "curves", "saturation", "green_fringe",
        "noise_sharpen", "local_contrast", "star_reduction",
    ]
```

Add `"green_fringe"` to the expected `frozenset({...})` in `test_post_stretch_ids_are_the_finishing_steps_minus_export` (keep every existing member).

Add:

```python
def test_green_fringe_placed_after_saturation():
    from nocturne.ui.pipeline import POST_STRETCH_IDS, STEP_NAME
    ids = [s.id for s in path_stages()]
    assert ids.index("green_fringe") == ids.index("saturation") + 1
    assert ids.index("green_fringe") < ids.index("noise_sharpen")
    assert STEP_NAME["green_fringe"] == "Remove Green Fringe"
    assert "green_fringe" in POST_STRETCH_IDS
```

Add to `tests/test_recipe.py`:

```python
def test_green_fringe_option_round_trip():
    from nocturne.recipe import serialize_option, deserialize_option
    assert serialize_option("green_fringe", 0.4) == 0.4
    assert deserialize_option("green_fringe", 0.4) == 0.4
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/steps/test_factory.py tests/ui/test_pipeline.py tests/test_recipe.py -q`
Expected: FAIL — `ModuleNotFoundError: nocturne.steps.green_fringe` and the updated frozen-list assertions fail.

- [ ] **Step 3a: Create the step wrapper**

Create `nocturne/steps/green_fringe.py`:

```python
from __future__ import annotations

from ..core.color import remove_green_fringe
from ..core.image import AstroImage
from ..history.step import Step


class GreenFringeStep(Step):
    name = "Remove Green Fringe"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        strength = float(option) if option not in (None, "") else 0.0
        return remove_green_fringe(img, strength)
```

- [ ] **Step 3b: Register in the factory**

In `nocturne/steps/factory.py`, add the import next to the other step imports:

```python
from .green_fringe import GreenFringeStep
```

and add this branch after the `saturation` branch:

```python
    if stage_id == "green_fringe":
        return GreenFringeStep()
```

- [ ] **Step 3c: Register the stage in the pipeline**

In `nocturne/ui/pipeline.py`:

Insert into `_IN_APP_TAIL` after the `saturation` Stage, before `noise_sharpen`:

```python
    Stage("saturation", "Saturation", "saturation"),
    Stage("green_fringe", "Remove Green Fringe", "green_fringe"),
    Stage("noise_sharpen", "Noise Reduction", "process"),
```

Add to `STEP_NAME` after the `"saturation"` entry:

```python
    "saturation": "Saturation",
    "green_fringe": "Remove Green Fringe",
    "noise_sharpen": "Noise Reduction",
```

Insert into `PROCESSING_ORDER` after `"saturation"`:

```python
PROCESSING_ORDER = [
    "background", "color", "remove_green", "deconvolution", "stretch",
    "recover_core", "levels", "curves", "saturation", "green_fringe",
    "noise_sharpen", "local_contrast", "star_reduction",
]
```

Add `"green_fringe"` to `POST_STRETCH_IDS` (the `frozenset({...})` a few lines below).

- [ ] **Step 3d: Recipe serialization**

In `nocturne/recipe.py`, add `green_fringe` to the float branch (the `if stage_id in ("local_contrast", "star_reduction", "recover_core"):` line):

```python
    if stage_id in ("local_contrast", "star_reduction", "recover_core", "green_fringe"):
```

(No change to `deserialize_option` — floats round-trip through its final `return value`.)

- [ ] **Step 3e: Help topic**

In `nocturne/ui/help_content.py`:

Add to `_STAGE_TO_TOPIC` after the `"saturation"` entry:

```python
    "saturation": "saturation",
    "green_fringe": "green_fringe",
    "noise_sharpen": "noise_sharpen",
```

Add a topic to `_TOPIC_LIST` (place it just before the `noise_sharpen` `_t(...)` entry so the guide reads in pipeline order):

```python
    _t("green_fringe", "Remove Green Fringe",
       "Remove the green colour fringe around stars.",
       "<h4>What it does</h4>"
       "<p>Stars are never truly green, so a green fringe or halo around them is "
       "always an artifact (from chromatic aberration or debayering). This reduces "
       "green only where it exceeds the red/blue level — hardest on bright star halos, "
       "with no effect on neutral, red, or blue tones.</p>"
       "<h4>How to use it</h4>"
       "<p>Raise <b>Strength</b> until the green fringe fades. 0 = off; at full strength "
       "it matches the quick Remove Green in the Color step, but here you dial it in late "
       "and watch the live preview. Apply.</p>"
       "<h4>Tips</h4>"
       "<p>A little usually does it. If a stubborn fringe survives, apply the step twice "
       "rather than pushing one pass too hard.</p>"),
```

Add `"green_fringe"` to the "The Steps" `HelpSection` tuple after `"saturation"`:

```python
    HelpSection("The Steps", ("crop", "background", "color", "deconvolution", "stretch",
                              "recover_core", "levels", "curves", "saturation",
                              "green_fringe", "noise_sharpen", "local_contrast",
                              "star_reduction", "enhancements", "export")),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/steps/test_factory.py tests/ui/test_pipeline.py tests/ui/test_help_content.py tests/test_recipe.py -q`
Expected: PASS (all green, including the help completeness test now that `green_fringe` has a topic).

- [ ] **Step 5: Commit**

```bash
git add nocturne/steps/green_fringe.py nocturne/steps/factory.py nocturne/ui/pipeline.py nocturne/recipe.py nocturne/ui/help_content.py tests/steps/test_factory.py tests/ui/test_pipeline.py tests/test_recipe.py
git commit -m "feat: register Remove Green Fringe stage (step, factory, pipeline, recipe, help)"
```

---

### Task 3: Remove Green Fringe panel

**Files:**
- Modify: `nocturne/ui/step_panels.py` (add `on_fringe_change` param + `green_fringe` branch)
- Test: `tests/ui/test_step_panels.py`

**Interfaces:**
- Consumes: stage `green_fringe` from `path_stages()` (Task 2); `ResetSlider`, `QLabel`, `QPushButton`, `QHBoxLayout` (already imported).
- Produces: `build_panel(..., on_fringe_change=None)`; panel with `w.fringe_slider` (a `ResetSlider(0)`), `w.fringe_val`, `w.apply_btn`, `w.panel_kind == "green_fringe"`; slider `valueChanged` updates the readout and calls `on_fringe_change(value/100.0)`; Apply calls `on_apply(value/100.0)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_step_panels.py`:

```python
def test_green_fringe_panel_has_slider_readout(qtbot):
    seen = {}
    w = build_panel(_stage("green_fringe"),
                    on_fringe_change=lambda s: seen.__setitem__("s", s))
    qtbot.addWidget(w)
    assert w.panel_kind == "green_fringe"
    assert hasattr(w, "fringe_slider") and hasattr(w, "fringe_val")
    assert w.fringe_slider.value() == 0            # default off
    w.fringe_slider.setValue(60)
    assert w.fringe_val.text().strip() == "0.60"   # readout tracks the slider
    assert seen.get("s") == 0.60                    # live-preview hook fires
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_step_panels.py::test_green_fringe_panel_has_slider_readout -q`
Expected: FAIL — `build_panel()` got an unexpected keyword `on_fringe_change` (or the `green_fringe` kind falls through to a bare panel).

- [ ] **Step 3: Implement the panel**

In `nocturne/ui/step_panels.py`, add the parameter to `build_panel`'s signature (next to `on_lc_change=None`):

```python
    on_lc_change=None,
    on_fringe_change=None,
```

Add the branch (place it after the `saturation` branch, matching pipeline order):

```python
    elif stage.kind == "green_fringe":
        lay.addWidget(_desc_label(
            "Remove the green colour fringe around stars. Green isn't real in astro "
            "images, so this only reduces green excess. 0 = off."))
        slider = ResetSlider(0)
        fringe_val = QLabel(f"{slider.value() / 100:.2f}")

        def _emit_fringe(*_):
            fringe_val.setText(f"{slider.value() / 100:.2f}")
            if on_fringe_change is not None:
                on_fringe_change(slider.value() / 100.0)

        slider.valueChanged.connect(_emit_fringe)
        apply_btn = QPushButton("Apply Remove Green Fringe")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(slider.value() / 100.0))
        fringe_row = QHBoxLayout()
        fringe_row.addWidget(QLabel("Strength (off → full)"))
        fringe_row.addWidget(fringe_val)
        lay.addLayout(fringe_row)
        lay.addWidget(slider)
        lay.addWidget(apply_btn)
        w.fringe_slider = slider
        w.fringe_val = fringe_val
        w.apply_btn = apply_btn
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ui/test_step_panels.py -q`
Expected: PASS (all step-panel tests green).

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/step_panels.py tests/ui/test_step_panels.py
git commit -m "feat: Remove Green Fringe panel (strength slider + numeric readout)"
```

---

### Task 4: main_window live preview + commit wiring

**Files:**
- Modify: `nocturne/ui/main_window.py` (import, `__init__` timer, preview methods, `_rebuild_panel`)
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `remove_green_fringe` (Task 1); `_preview_base`, `_show_preview`, `current_stage_id`, `apply_current`, `build_panel` (existing); `w.fringe_slider` (Task 3); stage `green_fringe` in `PROCESSING_ORDER`/factory (Task 2, so `apply_current` commits it).
- Produces: `_on_fringe_change(strength)`, `_render_fringe_preview()`; `_fringe_pending`/`_fringe_timer`; `on_fringe_change=self._on_fringe_change` wired into `build_panel(...)`; `_rebuild_panel` resets `_fringe_pending` on entry.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_main_window.py` (mirror the existing `_window`/`_make_fits`/`_go_to_id` helpers and the entries-count non-commit idiom):

```python
def test_green_fringe_live_preview_renders_without_commit(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("green_fringe")
    entries_before = [name for name, _ in win.project.entries()]
    win._on_fringe_change(0.6)
    win._render_fringe_preview()
    assert not win.image_view._item.pixmap().isNull()
    assert [name for name, _ in win.project.entries()] == entries_before  # no commit


def test_green_fringe_preview_updates_histogram(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("green_fringe")
    seen = []
    monkeypatch.setattr(win.histogram_view, "set_image", lambda img: seen.append(img))
    win._on_fringe_change(0.6)
    win._render_fringe_preview()
    assert seen
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py::test_green_fringe_live_preview_renders_without_commit -q`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_render_fringe_preview'`.

- [ ] **Step 3a: Import the core function**

In `nocturne/ui/main_window.py`, next to `from ..core.hdr import recover_core`:

```python
from ..core.color import remove_green_fringe
```

- [ ] **Step 3b: Add the debounce timer in `__init__`**

After the `curves` timer block (the one ending
`self._curve_timer.timeout.connect(self._render_curve_preview)`), add:

```python
        # Green-fringe live-preview: a debounced (90 ms) non-committing render.
        self._fringe_pending = None
        self._fringe_timer = QTimer(self)
        self._fringe_timer.setSingleShot(True)
        self._fringe_timer.timeout.connect(self._render_fringe_preview)
```

- [ ] **Step 3c: Add the preview methods**

After `_render_curve_preview` / `_on_curve_preset` (before the `# --- star reduction live preview ---` section), add:

```python
    # --- green fringe live preview ---
    def _on_fringe_change(self, strength: float) -> None:
        """The Remove Green Fringe slider moved: stash the value and (re)start debounce."""
        self._fringe_pending = strength
        self._fringe_timer.start(90)

    def _render_fringe_preview(self) -> None:
        """Non-committing live preview of the current green-fringe strength."""
        if self.project is None or self.current_stage_id() != "green_fringe":
            return
        img = self._preview_base("green_fringe")
        strength = (self._fringe_pending if self._fringe_pending is not None
                    else self._panel.fringe_slider.value() / 100.0)
        self._show_preview(remove_green_fringe(img, strength).data)
```

- [ ] **Step 3d: Reset pending + wire the callback in `_rebuild_panel`**

In `_rebuild_panel`, next to the other per-stage resets (e.g. after the
`if stage.id == "curves": self._curve_pending = None` block):

```python
        if stage.id == "green_fringe":
            self._fringe_pending = None
```

In the same method's `build_panel(...)` call, add the callback next to
`on_lc_change=self._on_lc_change,`:

```python
            on_lc_change=self._on_lc_change,
            on_fringe_change=self._on_fringe_change,
```

(Commit needs no new code: `apply_current` already routes any `PROCESSING_ORDER`
stage through `_step_for("green_fringe").apply(base, strength)`, which Task 2
registered. `_log_step` already formats a float option as `"{option:.2f}"`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -q`
Expected: PASS (all main-window tests green).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS (all tests green; count = previous total + the new green_fringe/panel/window/factory/pipeline/recipe tests).

- [ ] **Step 6: Commit**

```bash
git add nocturne/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat: Remove Green Fringe live preview + commit wiring in main window"
```

---

### Task 5: Real-data validation

**Files:**
- Update: `TODO.md`

**Interfaces:**
- Consumes: the shipped Remove Green Fringe step.
- Produces: validated behaviour; before/after evidence for sign-off.

- [ ] **Step 1: Drive the app on real data**

```bash
.venv/bin/python -m nocturne
```

Open a stretched target that shows green star fringe, run through to **Remove Green Fringe** (after Saturation). Drag **Strength**: confirm the green fringe/halo on stars fades as strength rises, the nebula colour and star cores stay correct (red/blue untouched), and the live preview equals the committed result after Apply.

- [ ] **Step 2: Capture before/after for sign-off**

Save a Strength-0 (off) and a tuned screenshot and present them for approval. Do not merge until the user confirms.

- [ ] **Step 3: Mark the backlog item done and commit**

Add a checked item to `TODO.md` recording that Remove Green Fringe shipped as a finishing step after Saturation (strength-controlled green-excess SCNR; `strength=1` == the Color-step Remove Green).

```bash
git add TODO.md
git commit -m "docs: mark Remove Green Fringe done (validated on real data)"
```

---

## Self-Review

**Spec coverage:**
- `core/color.py` `remove_green_fringe` (green-excess SCNR, strength-scaled, no-op at 0, mono no-op, `strength=1` == `remove_green`) → Task 1. ✅
- Stage after Saturation; `POST_STRETCH_IDS`; recipe float round-trip; help topic; step wrapper → Task 2. ✅
- Panel with strength slider + readout → Task 3. ✅
- Debounced live preview via `_preview_base`→`_show_preview` (image + histogram); commit via `apply_current` → Task 4. ✅
- Real-data validation → Task 5. ✅
- Tests: core, panel, window, factory, pipeline (frozen lists), recipe → Tasks 1–4. ✅

**Placeholder scan:** No TBD/"handle edge cases"/"similar to" — every code step contains full code. ✅

**Type consistency:** `remove_green_fringe(img, strength)` signature identical across core, step wrapper, and main_window preview; panel attribute names (`fringe_slider`, `fringe_val`) match between Task 3 (defined) and Task 4 (consumed); callback `on_fringe_change` consistent across `step_panels.py` and `main_window.py`; stage id `"green_fringe"` consistent across pipeline, factory, recipe, help, panel kind; recipe float branch verified by `test_green_fringe_option_round_trip`. ✅
