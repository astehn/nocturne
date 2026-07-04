# Reset Sliders on Double-Click Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Double-clicking any app slider resets it to its default (Lightroom/PixInsight convention), via a small reusable `ResetSlider` widget.

**Architecture:** New `ui/reset_slider.py` `ResetSlider(QSlider)` stores its construction default and resets on `mouseDoubleClickEvent`. Swap the ad-hoc `QSlider`s in `ui/step_panels.py` and `ui/palette_dialog.py` for it.

**Tech Stack:** Python 3.13 (`.venv`), PySide6 (Qt), pytest-qt (`QT_QPA_PLATFORM=offscreen`).

## Global Constraints

- Use `.venv/bin/python` / `.venv/bin/pytest`; system python is 3.9 and will fail. Qt tests: prefix `QT_QPA_PLATFORM=offscreen`.
- `ResetSlider` MUST set range BEFORE value in its constructor (gamma default 100 in a 10–300 range would otherwise clamp to 99).
- Reset restores the stored construction default and must emit `valueChanged` (so the palette live preview updates).
- Defaults (verified against current code): stretch 50, levels black 0 / gamma 100 (range 10–300) / white 100, saturation 50, palette black 0 / mid 50 / white 100.
- Preserve all existing behaviour: `w.*_slider` attribute names, signal wiring, the saturation tick marks, the Target-dropdown `setValue`, and the palette's existing global "Reset" button.
- Commit co-author trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Known flake: `test_sharpen_changes_image_and_keeps_shape` — rerun alone if it trips.

---

### Task 1: `ResetSlider` widget

**Files:**
- Create: `seestar_processor/ui/reset_slider.py`
- Test: `tests/ui/test_reset_slider.py`

**Interfaces:**
- Produces: `ResetSlider(default: int, *, minimum=0, maximum=100, orientation=Qt.Orientation.Horizontal, parent=None)` — a `QSlider` subclass; resets to `default` on double-click; exposes `_default`.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_reset_slider.py`:

```python
from PySide6.QtCore import Qt

from seestar_processor.ui.reset_slider import ResetSlider


def test_resets_to_default_on_double_click(qtbot):
    s = ResetSlider(50)
    qtbot.addWidget(s)
    assert s.value() == 50
    s.setValue(30)
    qtbot.mouseDClick(s, Qt.MouseButton.LeftButton)
    assert s.value() == 50


def test_range_set_before_value_avoids_clamp(qtbot):
    s = ResetSlider(100, minimum=10, maximum=300)
    qtbot.addWidget(s)
    assert s.value() == 100          # not clamped to a default 0-99 range
    assert s._default == 100
    s.setValue(250)
    qtbot.mouseDClick(s, Qt.MouseButton.LeftButton)
    assert s.value() == 100


def test_has_reset_tooltip(qtbot):
    s = ResetSlider(0)
    qtbot.addWidget(s)
    assert "reset" in s.toolTip().lower()


def test_reset_emits_value_changed(qtbot):
    s = ResetSlider(50)
    qtbot.addWidget(s)
    s.setValue(20)
    seen = []
    s.valueChanged.connect(seen.append)
    qtbot.mouseDClick(s, Qt.MouseButton.LeftButton)
    assert 50 in seen
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_reset_slider.py -q`
Expected: FAIL with `ModuleNotFoundError: seestar_processor.ui.reset_slider`.

- [ ] **Step 3: Implement the widget**

Create `seestar_processor/ui/reset_slider.py`:

```python
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSlider


class ResetSlider(QSlider):
    """Slider that resets to its construction default on double-click."""

    def __init__(self, default: int, *, minimum: int = 0, maximum: int = 100,
                 orientation: Qt.Orientation = Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setRange(minimum, maximum)   # range BEFORE value so default isn't clamped
        self.setValue(default)
        self._default = default
        self.setToolTip("Double-click to reset")

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.setValue(self._default)
        event.accept()
```

- [ ] **Step 4: Run to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_reset_slider.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/reset_slider.py tests/ui/test_reset_slider.py
git commit -m "feat: ResetSlider widget (double-click resets to default)"
```

---

### Task 2: Swap sliders in step_panels and palette_dialog

**Files:**
- Modify: `seestar_processor/ui/step_panels.py` (stretch ~162, levels ~186-194, saturation ~217-219)
- Modify: `seestar_processor/ui/palette_dialog.py` (`_slider` factory ~132; slider creation ~61-68)
- Test: `tests/ui/test_step_panels.py`, `tests/ui/test_palette_dialog.py`

**Interfaces:**
- Consumes: `ResetSlider` from Task 1.

- [ ] **Step 1: Write the failing panel tests**

Add to `tests/ui/test_step_panels.py`:

```python
def test_sliders_are_reset_sliders_with_defaults(qtbot):
    from seestar_processor.ui.reset_slider import ResetSlider
    st = build_panel(_stage("stretch")); qtbot.addWidget(st)
    assert isinstance(st.stretch_slider, ResetSlider) and st.stretch_slider._default == 50
    lv = build_panel(_stage("levels")); qtbot.addWidget(lv)
    assert isinstance(lv.black_slider, ResetSlider) and lv.black_slider._default == 0
    assert isinstance(lv.gamma_slider, ResetSlider) and lv.gamma_slider._default == 100
    assert lv.gamma_slider.value() == 100           # 10-300 range, not clamped
    assert isinstance(lv.white_slider, ResetSlider) and lv.white_slider._default == 100
    sa = build_panel(_stage("saturation")); qtbot.addWidget(sa)
    assert isinstance(sa.sat_slider, ResetSlider) and sa.sat_slider._default == 50


def test_stretch_slider_double_click_resets(qtbot):
    from PySide6.QtCore import Qt
    st = build_panel(_stage("stretch")); qtbot.addWidget(st)
    st.stretch_slider.setValue(20)
    qtbot.mouseDClick(st.stretch_slider, Qt.MouseButton.LeftButton)
    assert st.stretch_slider.value() == 50
```

(If `_stage` isn't the helper name used in this file, read the top of the file and match it.)

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_step_panels.py -q -k "reset or reset_slider or double_click"`
Expected: FAIL (sliders are plain `QSlider`, not `ResetSlider`).

- [ ] **Step 3: Swap the step_panels sliders**

In `seestar_processor/ui/step_panels.py`, add the import near the other UI imports:
```python
from .reset_slider import ResetSlider
```

Stretch (replace lines ~162-164):
```python
        slider = ResetSlider(50)
```

Levels (replace lines ~186-194):
```python
        black = ResetSlider(0)
        gamma = ResetSlider(100, minimum=10, maximum=300)  # 1.00
        white = ResetSlider(100)
```

Saturation (replace lines ~217-219 — keep the tick lines that follow):
```python
        slider = ResetSlider(50)
        slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        slider.setTickInterval(50)
```

Leave the `QSlider` import in place — `QSlider.TickPosition` is still referenced.

- [ ] **Step 4: Write the failing palette test**

Add to `tests/ui/test_palette_dialog.py` (read the file's existing setup — it constructs a `PaletteDialog` with a `Settings` + base image; mirror that):

```python
def test_palette_sliders_are_reset_sliders(qtbot):
    from seestar_processor.ui.reset_slider import ResetSlider
    dlg = _make_dialog(qtbot)          # use this file's existing dialog-construction helper
    assert isinstance(dlg.black_slider, ResetSlider) and dlg.black_slider._default == 0
    assert isinstance(dlg.mid_slider, ResetSlider) and dlg.mid_slider._default == 50
    assert isinstance(dlg.white_slider, ResetSlider) and dlg.white_slider._default == 100
    assert dlg.black_slider.value() == 0 and dlg.white_slider.value() == 100


def test_palette_slider_double_click_resets(qtbot):
    from PySide6.QtCore import Qt
    dlg = _make_dialog(qtbot)
    dlg.white_slider.setValue(40)
    qtbot.mouseDClick(dlg.white_slider, Qt.MouseButton.LeftButton)
    assert dlg.white_slider.value() == 100
```

If `tests/ui/test_palette_dialog.py` has no reusable dialog helper, construct the dialog inline the same way an existing test in that file does (same `Settings()` + base `AstroImage`), and `qtbot.addWidget(dlg)`.

- [ ] **Step 5: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_palette_dialog.py -q -k reset`
Expected: FAIL (sliders are plain `QSlider`).

- [ ] **Step 6: Swap the palette_dialog sliders**

In `seestar_processor/ui/palette_dialog.py`, add the import:
```python
from .reset_slider import ResetSlider
```

Change the slider creation (lines ~61-68) to:
```python
        self.black_slider = self._slider(0)
        self.mid_slider = self._slider(50)
        self.white_slider = self._slider(100)
```
(Delete the now-redundant `self.black_slider.setValue(0)` / `self.white_slider.setValue(100)` and their comment.)

Change the `_slider` factory (lines ~132-137) to:
```python
    def _slider(self, default: int) -> ResetSlider:
        return ResetSlider(default)
```

Signals are still connected after construction (lines ~82-83), so no premature `_on_slider` fire. The existing global "Reset" button is untouched.

- [ ] **Step 7: Run the panel + palette tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_step_panels.py tests/ui/test_palette_dialog.py -q`
Expected: PASS.

- [ ] **Step 8: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass (rerun the known sharpen flake alone if it trips).

- [ ] **Step 9: Commit**

```bash
git add seestar_processor/ui/step_panels.py seestar_processor/ui/palette_dialog.py \
        tests/ui/test_step_panels.py tests/ui/test_palette_dialog.py
git commit -m "feat: use ResetSlider for all stretch/levels/saturation/palette sliders"
```

---

## Self-Review

- **Spec coverage:** widget (T1), all 5 step_panels sliders + 3 palette sliders swapped with correct defaults (T2), range-before-value verified for gamma (T1 + T2 tests), reset emits valueChanged (T1) — covered.
- **Placeholders:** none — full code in every step.
- **Type consistency:** `ResetSlider(default, *, minimum, maximum, ...)` and `_default` used identically in the widget, panels, palette, and all tests. `_slider(default)` factory signature matches its two call sites.
- **Drift caught:** saturation default is 50 (not the TODO's 40); gamma range-before-value avoids the 100→99 clamp.
