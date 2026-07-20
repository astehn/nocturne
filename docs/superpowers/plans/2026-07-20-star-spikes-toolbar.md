# Star Spikes → Toolbar Tool (re-home) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Star Spikes out of the linear processing pipeline into a toolbar dialog tool (like Ha/OIII), since it is a purely artistic choice — keeping the reusable `detect_stars`/`add_spikes` core unchanged.

**Architecture:** Remove the `star_spikes` pipeline stage (stage list, panel, main_window step wiring, factory, recipe, step wrapper) and instead add a `StarSpikesDialog` (QDialog + `FramePreview` live preview + three sliders + Apply/Close) opened from a toolbar "Star Spikes…" action. Detection runs once on dialog open; sliders live-preview `add_spikes`; Apply records a `_PrecomputedStep("Star Spikes", result)` at the current position. The `nocturne/core/star_spikes.py` module (Task-1 of the prior plan) is unchanged.

**Tech Stack:** Python, NumPy, `sep`, PySide6, pytest. No new third-party dependency.

## Global Constraints

- Do NOT modify `nocturne/core/star_spikes.py` — the render is already validated; this plan only changes where the tool lives.
- After this plan, `star_spikes` is NOT a member of `path_stages()`, `STEP_NAME`, `PROCESSING_ORDER`, or `POST_STRETCH_IDS`; there is no `star_spikes` panel `kind`; and `make_step("star_spikes", ...)` no longer exists.
- The tool operates on the current committed image (`project.current()`), which must be display-space (not linear); guard with a status message if the image is still linear.
- Apply records `_PrecomputedStep("Star Spikes", result)` via `project.run_step(...)`, logged like the other recorded steps; it is intentionally NOT recipe-serialized (consistent with the Enhancements taps / toolbar tools).
- Dialog mirrors the existing toolbar-dialog pattern (`nocturne/ui/haoiii_dialog.py`): `QDialog`, an `on_apply` callback, `Close`/primary `Apply` buttons.
- Sliders: Length `ResetSlider(0)` (0 = off), Number-of-stars `ResetSlider(6, 0–50)`, Rotation `ResetSlider(0, 0–90)` — same ranges/defaults as before.

---

### Task 1: Remove Star Spikes from the linear pipeline

**Files:**
- Modify: `nocturne/ui/pipeline.py`
- Modify: `nocturne/ui/step_panels.py`
- Modify: `nocturne/ui/main_window.py`
- Modify: `nocturne/steps/factory.py`
- Delete: `nocturne/steps/star_spikes.py`
- Modify: `nocturne/recipe.py`
- Modify: `nocturne/ui/help_content.py`
- Test: revert `tests/ui/test_pipeline.py`, `tests/ui/test_main_window.py`, `tests/ui/test_step_panels.py`, `tests/steps/test_factory.py`, `tests/test_recipe.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: a pipeline with no `star_spikes` stage; `nocturne/core/star_spikes.py` remains importable (used by Task 2).

- [ ] **Step 1: Update the frozen-list + stage tests to the post-removal state (write the failing tests first)**

In `tests/ui/test_pipeline.py`, set `test_path_stages_single_linear_flow` back to (no `star_spikes`):

```python
def test_path_stages_single_linear_flow():
    ids = [s.id for s in path_stages()]
    assert ids == [
        "load", "crop", "background", "color", "deconvolution", "stretch",
        "recover_core", "levels", "curves", "saturation", "noise_sharpen",
        "local_contrast", "star_reduction", "enhancements", "export",
    ]
```

Set the `PROCESSING_ORDER` assertion in `test_step_name_and_order` back to (no `star_spikes`):

```python
    assert PROCESSING_ORDER == [
        "background", "color", "remove_green", "deconvolution", "stretch",
        "recover_core", "levels", "curves", "saturation", "noise_sharpen",
        "local_contrast", "star_reduction",
    ]
```

Remove `"star_spikes"` from the expected `frozenset({...})` in `test_post_stretch_ids_are_the_finishing_steps_minus_export`, and DELETE the `test_star_spikes_placed_after_star_reduction` test.

In `tests/ui/test_main_window.py`, remove `"star_spikes"` from the `seq` list in `test_default_in_app_path_navigation`, and DELETE the three star-spikes step tests (`test_star_spikes_caches_stars_and_enables_controls`, `test_star_spikes_preview_renders_without_commit`, `test_star_spikes_preview_updates_histogram`).

In `tests/ui/test_step_panels.py`, DELETE `test_star_spikes_panel_controls`.

In `tests/steps/test_factory.py`, DELETE `test_make_step_star_spikes` and `test_star_spikes_step_is_self_contained_noop_on_empty`.

In `tests/test_recipe.py`, DELETE `test_star_spikes_option_round_trip`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_pipeline.py -q`
Expected: FAIL — `path_stages()` still contains `star_spikes` (production code not yet reverted).

- [ ] **Step 3a: Remove the stage from the pipeline**

In `nocturne/ui/pipeline.py`:
- Delete the `Stage("star_spikes", "Star Spikes", "star_spikes"),` line from `_IN_APP_TAIL`.
- Delete the `"star_spikes": "Star Spikes",` entry from `STEP_NAME`.
- Delete `"star_spikes"` from `PROCESSING_ORDER`.
- Delete `"star_spikes"` from `POST_STRETCH_IDS`.

- [ ] **Step 3b: Remove the panel branch**

In `nocturne/ui/step_panels.py`:
- Delete the `on_spikes_change=None,` parameter from `build_panel`'s signature.
- Delete the entire `elif stage.kind == "star_spikes":` branch (from that `elif` line down to and including its `w.apply_btn = apply_btn` assignment, i.e. the whole block ending just before the next `elif`/`else`).

- [ ] **Step 3c: Remove the main_window step wiring**

In `nocturne/ui/main_window.py`:
- Delete the import `from ..core.star_spikes import add_spikes, detect_stars`.
- Delete the `__init__` block: `self._spikes_pending`, `self._spikes_stars`, `self._spikes_ready`, and the `self._spikes_timer` QTimer setup.
- Delete the five methods `_enable_spikes_panel`, `_setup_star_spikes`, `_on_spikes_detected`, `_on_spikes_change`, `_render_spikes_preview`.
- In `_rebuild_panel`: delete the `if stage.id == "star_spikes": self._spikes_pending = None` reset, the `on_spikes_change=self._on_spikes_change,` line in the `build_panel(...)` call, and the `if stage.id == "star_spikes": self._setup_star_spikes()` call.
- In `_log_step`: delete the `elif stage_id == "star_spikes":` branch.

- [ ] **Step 3d: Remove the factory registration and step wrapper**

In `nocturne/steps/factory.py`: delete `from .star_spikes import StarSpikesStep` and the `if stage_id == "star_spikes": return StarSpikesStep()` branch.

Delete the file `nocturne/steps/star_spikes.py`:

```bash
git rm nocturne/steps/star_spikes.py
```

- [ ] **Step 3e: Remove the recipe branch**

In `nocturne/recipe.py`: delete the `if stage_id == "star_spikes": ...` branch from both `serialize_option` and `deserialize_option`.

- [ ] **Step 3f: Relocate the help topic out of the pipeline steps**

In `nocturne/ui/help_content.py`:
- Delete the `"star_spikes": "star_spikes",` entry from `_STAGE_TO_TOPIC`.
- Remove `"star_spikes"` from the "The Steps" `HelpSection` tuple.
- Keep the `_t("star_spikes", "Star Spikes", ...)` topic in `_TOPIC_LIST`, but update its "How to use it" paragraph to describe the toolbar button rather than a pipeline step:

```python
    _t("star_spikes", "Star Spikes",
       "Add diffraction spikes to the brightest stars.",
       "<h4>What it does</h4>"
       "<p>Refractor scopes like the Seestar produce no diffraction spikes — the "
       "four-point flares many people associate with an astrophoto. This tool draws "
       "tasteful, colour-matched spikes on the brightest stars. It is a purely artistic "
       "choice, so it lives in the toolbar rather than the processing steps.</p>"
       "<h4>How to use it</h4>"
       "<p>Finish your normal processing first, then click <b>Star Spikes…</b> in the "
       "toolbar. <b>Length</b> sets how long the spikes are (0 = off), <b>Number of stars</b> "
       "how many of the brightest stars get spikes, and <b>Rotation</b> tilts the cross. "
       "Watch the live preview, then Apply.</p>"
       "<h4>Tips</h4>"
       "<p>Less is more — a few long spikes on the brightest stars looks intentional; "
       "spikes on everything looks fake. Keep the count low.</p>"),
```

- Add `"star_spikes"` to the "Tools" `HelpSection` tuple (so the topic is still referenced by a real section):

```python
    HelpSection("Tools", ("tools", "star_spikes")),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_pipeline.py tests/ui/test_main_window.py tests/ui/test_step_panels.py tests/steps/test_factory.py tests/test_recipe.py tests/ui/test_help_content.py tests/core/test_star_spikes.py -q`
Expected: PASS (all green; `star_spikes` no longer a stage, core still tested).

Then the full suite:

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: remove Star Spikes from the linear pipeline (moving to a toolbar tool)"
```

---

### Task 2: Star Spikes toolbar dialog

**Files:**
- Create: `nocturne/ui/star_spikes_dialog.py`
- Modify: `nocturne/ui/main_window.py` (toolbar action + `_open_star_spikes` + `_apply_star_spikes`)
- Test: `tests/ui/test_star_spikes_dialog.py`, `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `detect_stars`, `add_spikes`, `Star` from `nocturne.core.star_spikes`; `nocturne.core.image.AstroImage`; `FramePreview`; `ResetSlider`; `rgb_to_qimage` from `nocturne.ui.preview`; `_PrecomputedStep` (existing, in main_window).
- Produces: `StarSpikesDialog(base: AstroImage, parent=None, on_apply=None)` with `length_slider`, `stars_slider`, `angle_slider`, `apply_btn`, a `_render_preview()` method, and `result()` (the last-rendered `AstroImage`); `MainWindow._open_star_spikes` + `_apply_star_spikes`.

- [ ] **Step 1: Write the failing tests**

Create `tests/ui/test_star_spikes_dialog.py`:

```python
import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.core.image import AstroImage  # noqa: E402
from nocturne.ui.star_spikes_dialog import StarSpikesDialog  # noqa: E402


def _img():
    # a bright dot on a dark field so detection finds a star
    a = np.zeros((64, 64, 3), np.float32)
    a[20, 40] = 1.0
    a[19:22, 39:42] = 0.9
    return AstroImage(a, is_linear=False)


def test_dialog_builds_and_detects(qtbot):
    d = StarSpikesDialog(_img())
    qtbot.addWidget(d)
    assert d.length_slider.value() == 0
    assert d.stars_slider.value() == 6
    assert len(d._stars) >= 1                 # detected on construction


def test_slider_change_renders_preview(qtbot):
    d = StarSpikesDialog(_img())
    qtbot.addWidget(d)
    d.length_slider.setValue(60)
    d._render_preview()
    assert d.preview.has_image()
    # length 0 -> result is the untouched base; length > 0 -> changed
    changed = d.result().data
    assert not np.allclose(changed, d._base.data)


def test_apply_calls_back_with_result(qtbot):
    got = []
    d = StarSpikesDialog(_img(), on_apply=got.append)
    qtbot.addWidget(d)
    d.length_slider.setValue(50)
    d._render_preview()
    d.apply_btn.click()
    assert got and isinstance(got[0], AstroImage)
    assert got[0].data.shape == (64, 64, 3)
```

Add to `tests/ui/test_main_window.py`:

```python
def test_star_spikes_tool_records_step_on_apply(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")                  # ensure a display-space image
    win.apply_current("")                     # commit a stretch so current() is non-linear
    from nocturne.core.image import AstroImage
    import numpy as np
    before = len(win.project.entries())
    result = AstroImage(np.clip(win.project.current().data, 0, 1), is_linear=False)
    win._apply_star_spikes(result)
    names = [name for name, _ in win.project.entries()]
    assert names[-1] == "Star Spikes"
    assert len(win.project.entries()) == before + 1


def test_star_spikes_tool_guarded_when_linear(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))       # freshly loaded image is linear
    opened = []
    monkeypatch.setattr("nocturne.ui.star_spikes_dialog.StarSpikesDialog",
                        lambda *a, **k: opened.append(True))
    win._open_star_spikes()
    assert not opened                         # refused on a linear image
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_star_spikes_dialog.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nocturne.ui.star_spikes_dialog'`.

- [ ] **Step 3a: Create the dialog**

Create `nocturne/ui/star_spikes_dialog.py`:

```python
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from ..core.image import AstroImage
from ..core.star_spikes import add_spikes, detect_stars
from .frame_preview import FramePreview
from .preview import rgb_to_qimage
from .reset_slider import ResetSlider


class StarSpikesDialog(QDialog):
    """Artistic tool: draw diffraction spikes on the brightest stars of the
    current (display-space) image, with a live preview. Detection runs once on
    open; the three sliders then re-render instantly. Apply hands the rendered
    AstroImage back via `on_apply`."""

    def __init__(self, base: AstroImage, parent=None, on_apply=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Star Spikes")
        self.setMinimumSize(720, 560)
        self._base = base
        self._on_apply = on_apply
        self._result = base
        self._stars = detect_stars(base.data)          # one-time detection

        self.preview = FramePreview()
        self.length_slider = ResetSlider(0)
        self.stars_slider = ResetSlider(6, minimum=0, maximum=50)
        self.angle_slider = ResetSlider(0, minimum=0, maximum=90)
        self.length_val = QLabel("0.00")
        self.stars_val = QLabel("6")
        self.angle_val = QLabel("0°")

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_preview)
        for s in (self.length_slider, self.stars_slider, self.angle_slider):
            s.valueChanged.connect(self._on_change)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self._apply)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)

        def _row(label, widget, val):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(val)
            outer = QVBoxLayout()
            outer.addLayout(row)
            outer.addWidget(widget)
            return outer

        root = QVBoxLayout(self)
        root.addWidget(self.preview, 1)
        note = QLabel("Add diffraction spikes to the brightest stars. Length 0 = off. "
                      "Keep the star count low so it looks intentional.")
        note.setWordWrap(True)
        root.addWidget(note)
        root.addLayout(_row("Length (off → long)", self.length_slider, self.length_val))
        root.addLayout(_row("Number of stars", self.stars_slider, self.stars_val))
        root.addLayout(_row("Rotation", self.angle_slider, self.angle_val))
        buttons = QHBoxLayout()
        buttons.addWidget(self.apply_btn)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

        self._render_preview()

    def _params(self):
        return (self.length_slider.value() / 100.0,
                self.stars_slider.value(),
                float(self.angle_slider.value()))

    def _on_change(self, *_):
        self.length_val.setText(f"{self.length_slider.value() / 100:.2f}")
        self.stars_val.setText(str(self.stars_slider.value()))
        self.angle_val.setText(f"{self.angle_slider.value()}°")
        self._timer.start(90)

    def _render_preview(self) -> None:
        length, count, angle = self._params()
        self._result = add_spikes(self._base, self._stars, length, count, angle)
        data = np.clip(self._result.data, 0.0, 1.0)
        if data.ndim == 2:
            rgb = np.repeat((data * 255 + 0.5).astype(np.uint8)[:, :, None], 3, axis=2)
        else:
            rgb = (data * 255 + 0.5).astype(np.uint8)
        self.preview.show_image(rgb_to_qimage(np.ascontiguousarray(rgb)))

    def result(self) -> AstroImage:
        return self._result

    def _apply(self) -> None:
        self._render_preview()                 # ensure result matches the sliders
        if self._on_apply is not None:
            self._on_apply(self._result)
        self.accept()
```

- [ ] **Step 3b: Wire the toolbar action + handlers in main_window**

In `nocturne/ui/main_window.py`, add the toolbar action in `_build_toolbar` right after the Ha/OIII action (`tb.addAction(load_icon("haoiii", ACCENT), "Ha/OIII…", self._open_haoiii)`):

```python
        tb.addAction(load_icon("haoiii", ACCENT), "Star Spikes…", self._open_star_spikes)
```

(Reuse the `haoiii` icon — there is no dedicated spikes icon; a later task can add one.)

Add the two handlers (place them next to `_open_haoiii`):

```python
    def _open_star_spikes(self) -> None:
        if self.project is None:
            return
        if self.project.current().is_linear:
            self._status.setText("Stretch the image first — Star Spikes works on the "
                                 "stretched image.")
            return
        from .star_spikes_dialog import StarSpikesDialog
        StarSpikesDialog(self.project.current(), parent=self,
                         on_apply=self._apply_star_spikes).exec()

    def _apply_star_spikes(self, result) -> None:
        self.project.run_step(_PrecomputedStep("Star Spikes", result), "")
        self.log_panel.append_entry(format_log_entry("Star Spikes", "", None))
        self._status.setText("")
        self._refresh()
```

(`format_log_entry` is already imported in `main_window.py`; confirm and use the existing import.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_star_spikes_dialog.py tests/ui/test_main_window.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nocturne/ui/star_spikes_dialog.py nocturne/ui/main_window.py tests/ui/test_star_spikes_dialog.py tests/ui/test_main_window.py
git commit -m "feat: Star Spikes toolbar dialog (artistic tool with live preview)"
```

---

### Task 3: Real-data validation and merge prep

**Files:**
- Update: `TODO.md`

**Interfaces:**
- Consumes: the shipped toolbar tool.

- [ ] **Step 1: Drive the app on real data**

```bash
.venv/bin/python -m nocturne
```

Open a stretched target, finish normal processing, then click **Star Spikes…** in the toolbar. Confirm: the dialog opens with a live preview of the current image; the three sliders update the spikes live; Apply records a "Star Spikes" entry in the log and the main image shows the spikes; Close discards without applying; the tool refuses (status message) on a still-linear image.

- [ ] **Step 2: Capture before/after for sign-off**

Save a before (no spikes) and after (applied) screenshot and present for approval. Do not merge until the user confirms.

- [ ] **Step 3: Mark the backlog item done and commit**

In `TODO.md`, mark the "Diffraction / star spikes" item `- [x]` with a note that it shipped as a toolbar artistic tool (not a pipeline step). Note the deferred core minors (unify the two no-op paths; the length-0 no-op is moot now since Apply always renders at the chosen params).

```bash
git add TODO.md
git commit -m "docs: mark star spikes done (shipped as a toolbar artistic tool)"
```

---

## Self-Review

**Spec coverage:**
- Remove `star_spikes` from pipeline/panel/main_window/factory/recipe/help + revert tests → Task 1. ✅
- Toolbar dialog with live preview + Apply recording a precomputed step; guarded on linear; help relocated → Task 2. ✅
- Validation + TODO → Task 3. ✅
- Core `star_spikes.py` untouched (global constraint) — no task modifies it. ✅

**Placeholder scan:** No TBD/"handle edge cases"/"similar to" — every code step shows full code or an exact deletion target. ✅

**Type consistency:** `StarSpikesDialog(base, parent, on_apply)` and its `result()`/`_render_preview()`/`length_slider`/`stars_slider`/`angle_slider`/`apply_btn` are consistent between Task 2's definition and its tests; `on_apply` receives an `AstroImage`, which `_apply_star_spikes` records via `_PrecomputedStep("Star Spikes", result)`; `add_spikes(base, stars, length, count, angle)` signature matches the unchanged core; the removed identifiers (`_spikes_*`, `on_spikes_change`, `StarSpikesStep`, `make_step("star_spikes")`) are consistently deleted across production and tests in Task 1. ✅
