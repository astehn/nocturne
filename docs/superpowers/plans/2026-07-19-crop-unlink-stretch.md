# Crop-panel "Unlink stretch" toggle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a manual, display-only checkbox in the Crop panel that neutralizes a tinted linear preview by switching it from `linked_stretch` to `unlinked_stretch`.

**Architecture:** `to_qimage` gains an `unlinked` flag that only matters on the linear-preview path; `MainWindow` holds the session-scoped display flag and passes it both to `to_qimage` (render) and `build_panel` (checkbox initial state); the Crop panel exposes the checkbox and reports toggles via a callback.

**Tech Stack:** Python, NumPy, PySide6, pytest/pytest-qt.

## Global Constraints

- Display-only: never mutate `AstroImage.data`; the flag is not part of edit history or settings.
- Off by default (`False`): linked stretch remains the default.
- The `unlinked` param must be a no-op when `img.is_linear` is `False` (the `clip` path).
- Both stretch functions already exist in `nocturne/core/autostretch.py`: `autostretch(img)` (= linked) and `unlinked_stretch(data, target=_TARGET_BG)`. Do not modify them.
- Follow existing UI patterns: panels communicate with the window via `on_*` callbacks passed to `build_panel`; the window re-renders through `MainWindow._refresh()`.

---

### Task 1: `to_qimage` unlinked flag

**Files:**
- Modify: `nocturne/ui/preview.py`
- Test: `tests/ui/test_preview.py`

**Interfaces:**
- Produces: `to_qimage(img: AstroImage, unlinked: bool = False) -> QImage`

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_preview.py`:

```python
from nocturne.ui.preview import to_qimage  # already imported at top


def _channel_medians(qimg):
    w, h = qimg.width(), qimg.height()
    bpl = qimg.bytesPerLine()
    buf = np.frombuffer(qimg.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)
    arr = buf[:, : w * 3].reshape(h, w, 3)
    return np.array([np.median(arr[..., c]) for c in range(3)], dtype=float)


def _tinted_linear():
    rng = np.random.default_rng(0)
    data = np.zeros((8, 12, 3), np.float32)
    data[..., 0] = 0.02 + rng.random((8, 12)) * 0.01  # R low
    data[..., 1] = 0.05 + rng.random((8, 12)) * 0.01  # G mid
    data[..., 2] = 0.12 + rng.random((8, 12)) * 0.01  # B elevated -> blue cast
    return AstroImage(data, is_linear=True)


def test_unlinked_neutralizes_tint_on_linear(qapp):
    img = _tinted_linear()
    linked_spread = np.ptp(_channel_medians(to_qimage(img, unlinked=False)))
    unlinked_spread = np.ptp(_channel_medians(to_qimage(img, unlinked=True)))
    assert unlinked_spread < linked_spread


def test_unlinked_is_noop_when_not_linear(qapp):
    data = _tinted_linear().data
    img = AstroImage(data, is_linear=False)
    a = to_qimage(img, unlinked=False)
    b = to_qimage(img, unlinked=True)
    assert a == b  # QImage equality: identical pixels
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_preview.py -q`
Expected: FAIL — `to_qimage()` takes 1 positional arg / unexpected keyword `unlinked`.

- [ ] **Step 3: Implement the flag**

In `nocturne/ui/preview.py`, update the import and function:

```python
from ..core.autostretch import autostretch, unlinked_stretch


def to_qimage(img: AstroImage, unlinked: bool = False) -> QImage:
    if img.is_linear:
        data = unlinked_stretch(img.data) if unlinked else autostretch(img)
    else:
        data = np.clip(img.data, 0.0, 1.0)
    if data.ndim == 2:
        data = np.repeat(data[:, :, None], 3, axis=2)
    rgb = (data * 255 + 0.5).astype(np.uint8)
    rgb = np.ascontiguousarray(rgb)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_preview.py -q`
Expected: PASS (all, including the two pre-existing dimension tests).

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/preview.py tests/ui/test_preview.py
git commit -m "feat(preview): unlinked display-stretch flag for to_qimage"
```

---

### Task 2: Crop-panel checkbox + window wiring

**Files:**
- Modify: `nocturne/ui/step_panels.py` (crop branch of `build_panel`)
- Modify: `nocturne/ui/main_window.py` (`__init__` state, `_refresh`, `_rebuild_panel`, new `_on_unlink_toggle`)
- Test: `tests/ui/test_step_panels.py`, `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `to_qimage(img, unlinked)` from Task 1.
- Produces:
  - `build_panel(..., on_unlink_toggle=None, unlinked_checked: bool = False)`; crop panel exposes `w.unlink_check` (a `QCheckBox`).
  - `MainWindow._display_unlinked: bool` and `MainWindow._on_unlink_toggle(self, checked: bool) -> None`.

- [ ] **Step 1: Write the failing panel test**

Add to `tests/ui/test_step_panels.py`:

```python
def test_crop_panel_unlink_checkbox_reports_toggle(qapp):
    seen = []
    w = build_panel(
        _stage("crop"),
        on_unlink_toggle=lambda c: seen.append(c),
        unlinked_checked=False,
    )
    assert hasattr(w, "unlink_check")
    assert w.unlink_check.isChecked() is False
    w.unlink_check.setChecked(True)
    assert seen == [True]


def test_crop_panel_unlink_reflects_initial_state(qapp):
    w = build_panel(_stage("crop"), unlinked_checked=True)
    assert w.unlink_check.isChecked() is True
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ui/test_step_panels.py -q`
Expected: FAIL — `build_panel()` got an unexpected keyword `on_unlink_toggle` / no `unlink_check`.

- [ ] **Step 3: Add the checkbox to `build_panel`**

In `nocturne/ui/step_panels.py`, add `QCheckBox` to the imports from `PySide6.QtWidgets` if not present. Add the two parameters to the signature:

```python
def build_panel(
    stage,
    *,
    on_open=None,
    on_apply=None,
    on_crop_apply=None,
    on_crop_change=None,
    on_rotate=None,
    on_flip_h=None,
    on_flip_v=None,
    on_export=None,
    on_remove_green=None,
    on_colourise=None,
    on_palette_advanced=None,
    on_enhance=None,
    on_unlink_toggle=None,
    unlinked_checked: bool = False,
    apply_enabled: bool = True,
    split_enabled: bool = False,
) -> QWidget:
```

At the end of the `elif stage.kind == "crop":` block, after `lay.addWidget(apply_btn)` and before the `w.aspect_box = aspect` assignments, add:

```python
        unlink = QCheckBox("Unlink stretch (neutralize tint)")
        unlink.setChecked(unlinked_checked)
        if on_unlink_toggle is not None:
            unlink.toggled.connect(lambda c: on_unlink_toggle(c))
        lay.addWidget(unlink)
        lay.addWidget(_desc_label(
            "Preview only — evens out a colour cast so you can frame. "
            "Doesn't change your image."))
```

Then register it with the other `w.*` assignments:

```python
        w.unlink_check = unlink
```

- [ ] **Step 4: Run to verify panel tests pass**

Run: `.venv/bin/python -m pytest tests/ui/test_step_panels.py -q`
Expected: PASS.

- [ ] **Step 5: Write the failing window test**

Add to `tests/ui/test_main_window.py` (uses the existing `win`/`qtbot`/`tmp_path` + `_load` helper pattern already in that file — construct the window the same way the other tests do, load the sample, then navigate to crop):

```python
def test_unlink_toggle_sets_flag_and_survives_rebuild(qtbot, tmp_path):
    win = MainWindow(settings_path=str(tmp_path / "settings.json"))
    qtbot.addWidget(win)
    assert win._display_unlinked is False
    win._on_unlink_toggle(True)
    assert win._display_unlinked is True
    win._go_to_id("crop")
    win._rebuild_panel()
    assert win._panel.unlink_check.isChecked() is True
```

- [ ] **Step 6: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py::test_unlink_toggle_sets_flag_and_survives_rebuild -q`
Expected: FAIL — `MainWindow` has no `_display_unlinked` / `_on_unlink_toggle`.

- [ ] **Step 7: Wire the window**

In `nocturne/ui/main_window.py`:

1. In `__init__`, alongside the other simple state initializers (before the first `_rebuild_panel`/`_refresh` call), add:

```python
        self._display_unlinked = False
```

2. Add the handler method (near `_refresh`):

```python
    def _on_unlink_toggle(self, checked: bool) -> None:
        """Display-only: neutralize a tinted linear preview (Crop stage)."""
        self._display_unlinked = bool(checked)
        self._refresh()
```

3. In `_refresh`, change the render line:

```python
            self.image_view.set_image(to_qimage(img, self._display_unlinked))
```

4. In `_rebuild_panel`, add the two kwargs to the `build_panel(...)` call:

```python
            on_unlink_toggle=self._on_unlink_toggle,
            unlinked_checked=self._display_unlinked,
```

- [ ] **Step 8: Run the window test + full UI suite**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py tests/ui/test_step_panels.py tests/ui/test_preview.py -q`
Expected: PASS (all).

- [ ] **Step 9: Commit**

```bash
git add nocturne/ui/step_panels.py nocturne/ui/main_window.py tests/ui/test_step_panels.py tests/ui/test_main_window.py
git commit -m "feat(ui): Crop-panel unlink-stretch toggle for tinted previews"
```
