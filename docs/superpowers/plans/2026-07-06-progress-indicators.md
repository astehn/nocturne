# Progress Indicators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ambient, non-intrusive progress indication (thin top bar + busy-cursor + grey label) to the main window, threshold-gated so fast ops never flash, and fold in two real fixes: move export off the UI thread and make busy-clearing `finally`-safe.

**Architecture:** A new `BusyBar` overlay widget replaces the image-dimming `BusyOverlay`. A `_run_busy` helper on `MainWindow` centralises the set-busy → run_async → done/err dance and clears busy in a `finally`. `_set_busy` flips the re-entry gate immediately but delays the *visuals* by ~400 ms via a single-shot timer. `apply_current`, `_colourise`, and `export_final` all route through `_run_busy`.

**Tech Stack:** Python 3.13 (`.venv`), PySide6 (Qt), pytest-qt (headless via `QT_QPA_PLATFORM=offscreen`).

## Global Constraints

- Python interpreter: `.venv/bin/python`; tests: `.venv/bin/pytest` (system python3 is 3.9 — do NOT use it).
- Run the suite with: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`.
- Preserve test seams: the `_async_enabled=False` synchronous path (tests set it via the `_window` helper), and the injectable `_bg_runner` / `_rc_runner`.
- Bar height: `BUSY_BAR_HEIGHT = 3` px. Visual delay: `BUSY_DELAY_MS = 400` ms. Highlight colour: `ACCENT` from `seestar_processor/ui/theme.py` (`"#2dd4bf"`).
- Busy label colour: `#9aa0a6` (neutral grey), kept separate from the red error `_status` label (`#ff6b6b`).
- Indeterminate only on the main window — no determinate/`set_fraction`. The stacking / batch / Ha-OIII dialogs already have real progress bars and MUST NOT be touched.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: `BusyBar` widget

**Files:**
- Create: `seestar_processor/ui/busy_bar.py`
- Test: `tests/ui/test_busy_bar.py`

**Interfaces:**
- Consumes: nothing (standalone widget). `ACCENT` from `seestar_processor/ui/theme.py`.
- Produces: `class BusyBar(QWidget)` with `show_over(widget)`, `hide_bar()`, a private `_timer` (QTimer), and module constant `BUSY_BAR_HEIGHT = 3`. Mouse-transparent (`WA_TransparentForMouseEvents`). Animation timer runs only while shown.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_busy_bar.py`:

```python
import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QWidget  # noqa: E402
from seestar_processor.ui.busy_bar import BusyBar, BUSY_BAR_HEIGHT  # noqa: E402


def test_busy_bar_show_over_and_hide(qtbot):
    parent = QWidget()
    parent.resize(200, 100)
    qtbot.addWidget(parent)
    bar = BusyBar()
    bar.show_over(parent)
    assert bar.parent() is parent
    assert bar.isHidden() is False
    assert bar._timer.isActive() is True
    assert bar.height() == BUSY_BAR_HEIGHT
    assert bar.width() == parent.width()
    bar.hide_bar()
    assert bar._timer.isActive() is False
    assert bar.isHidden() is True


def test_busy_bar_follows_target_resize(qtbot):
    parent = QWidget()
    parent.resize(200, 100)
    qtbot.addWidget(parent)
    bar = BusyBar()
    bar.show_over(parent)
    parent.resize(400, 120)
    assert bar.width() == 400


def test_busy_bar_is_mouse_transparent(qtbot):
    bar = BusyBar()
    qtbot.addWidget(bar)
    assert bar.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_busy_bar.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'seestar_processor.ui.busy_bar'`.

- [ ] **Step 3: Write minimal implementation**

Create `seestar_processor/ui/busy_bar.py`:

```python
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from .theme import ACCENT

BUSY_BAR_HEIGHT = 3            # px
_ANIM_INTERVAL_MS = 33         # ~30 fps repaint while shown
_SWEEP_FRACTION = 0.30         # moving highlight width as a fraction of the track


class BusyBar(QWidget):
    """Thin animated indeterminate progress bar overlaid on a target's top edge.

    Never dims or covers the image body; mouse-transparent so it never blocks
    clicks on the canvas underneath. The animation timer runs only while shown.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._target: QWidget | None = None
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(_ANIM_INTERVAL_MS)
        self._timer.timeout.connect(self._advance)
        self.hide()

    def _advance(self) -> None:
        self._phase = (self._phase + 0.03) % 1.0
        self.update()

    def _reposition(self) -> None:
        if self._target is not None:
            self.setGeometry(0, 0, self._target.width(), BUSY_BAR_HEIGHT)

    def show_over(self, widget: QWidget) -> None:
        if self._target is not None and self._target is not widget:
            self._target.removeEventFilter(self)
        self._target = widget
        self.setParent(widget)
        widget.installEventFilter(self)
        self._reposition()
        self._phase = 0.0
        self._timer.start()
        self.raise_()
        self.show()

    def hide_bar(self) -> None:
        self._timer.stop()
        if self._target is not None:
            self._target.removeEventFilter(self)
            self._target = None
        self.hide()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._target and event.type() == QEvent.Type.Resize:
            self._reposition()
        return False

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        w = self.width()
        h = self.height()
        painter.fillRect(self.rect(), QColor(255, 255, 255, 30))   # faint track
        sweep_w = max(1, int(w * _SWEEP_FRACTION))
        x = int(self._phase * (w + sweep_w)) - sweep_w
        painter.fillRect(x, 0, sweep_w, h, QColor(ACCENT))         # moving highlight
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_busy_bar.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/busy_bar.py tests/ui/test_busy_bar.py
git commit -m "feat: BusyBar — thin animated indeterminate top-edge progress bar

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `_run_busy` helper (finally-safe) + migrate apply_current & _colourise

**Files:**
- Modify: `seestar_processor/ui/main_window.py` (`apply_current` at ~412-457; `_colourise` at ~218-253; `_set_busy` at ~469-478)
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: existing `run_async(self._pool, work, on_done, on_error)`, `self._set_busy(bool)`, `self._async_enabled`.
- Produces: `_run_busy(self, work, on_result, label: str, err_prefix: str) -> None` — sets busy with `label`, runs `work` (async when `_async_enabled` else inline), calls `on_result(result)` on success, sets `f"{err_prefix}: {exc}"` in `self._status` on failure, and **always** clears busy in a `finally`. `_set_busy` gains a `label: str = "Working…"` parameter (unused by the overlay in this task; consumed in Task 3).

**Note:** This task keeps the existing `BusyOverlay` visuals. It only introduces `_run_busy`, adds the `label` param to `_set_busy`, and migrates the two async call sites. The visual overhaul is Task 3.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_main_window.py` (the `_window` helper already sets `_async_enabled = False`):

```python
def test_run_busy_clears_busy_when_on_result_raises(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)  # _async_enabled = False -> inline
    win.open_fits(_make_fits(tmp_path))

    def boom(_result):
        raise RuntimeError("kaboom")

    with pytest.raises(RuntimeError):
        win._run_busy(lambda: 1, boom, "Working…", "Failed")
    assert win._busy is False  # finally cleared it despite the throw


def test_run_busy_reports_error_prefix(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))

    def work():
        raise ValueError("disk full")

    win._run_busy(work, lambda r: None, "Working…", "Export failed")
    assert win._busy is False
    assert "Export failed: disk full" in win._status.text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py::test_run_busy_clears_busy_when_on_result_raises tests/ui/test_main_window.py::test_run_busy_reports_error_prefix -q`
Expected: FAIL with `AttributeError: 'MainWindow' object has no attribute '_run_busy'`.

- [ ] **Step 3a: Add the `label` param to `_set_busy`**

In `seestar_processor/ui/main_window.py`, change the `_set_busy` signature (keep the body as-is for now):

```python
    def _set_busy(self, busy: bool, label: str = "Working…") -> None:
        self._busy = busy
        if busy:
            self._busy_overlay.show_over(self.image_view)
        else:
            self._busy_overlay.hide()
        self._back_btn.setDisabled(busy)
        self._next_btn.setDisabled(busy)
        if hasattr(self._panel, "apply_btn"):
            self._panel.apply_btn.setDisabled(busy)
```

- [ ] **Step 3b: Add the `_run_busy` helper**

Add this method to `MainWindow` (place it directly above `_set_busy`):

```python
    def _run_busy(self, work, on_result, label: str, err_prefix: str) -> None:
        """Run `work` off the UI thread with busy indication; `on_result(result)`
        on success, `f"{err_prefix}: {exc}"` in the status label on failure.
        Busy is always cleared in a finally (even if `on_result` raises)."""
        self._set_busy(True, label)

        def done(result):
            try:
                on_result(result)
            finally:
                self._set_busy(False)

        def err(exc):
            try:
                self._status.setText(f"{err_prefix}: {exc}")
            finally:
                self._set_busy(False)

        if self._async_enabled:
            run_async(self._pool, work, done, err)
        else:
            try:
                result = work()
            except Exception as exc:  # mirror the async error path
                err(exc)
            else:
                done(result)          # an on_result throw propagates after the finally
```

- [ ] **Step 3c: Migrate `apply_current` to `_run_busy`**

Replace the tail of `apply_current` (from `step = self._step_for(stage_id)` through the `if self._async_enabled: ... else: ...` block) with:

```python
        step = self._step_for(stage_id)
        base = self.project.current()
        self._status.setText("")

        def on_result(result):
            self.project.run_step(_PrecomputedStep(STEP_NAME[stage_id], result), option)
            self._log_step(stage_id, option, base, result)
            self._refresh()  # stay on this step; user clicks Next to advance

        self._run_busy(lambda: step.apply(base, option), on_result,
                       f"Applying {STEP_NAME[stage_id]}…", "Failed")
```

- [ ] **Step 3d: Migrate `_colourise` to `_run_busy`**

Replace the tail of `_colourise` (from `self._status.setText("")` / `self._set_busy(True)` through the `if self._async_enabled: ... else: ...` block) with:

```python
        self._status.setText("")

        def work():
            starless, stars = self._colourise_starx(base)
            if stars is None:
                return render_nebula(starless, PaletteParams())
            return compose(starless, stars, PaletteParams())

        def on_result(result):
            self.project.jump_back(idx)             # truncate only on success
            self.project.run_step(_PrecomputedStep("Colourise", result), "")
            self.log_panel.append_entry(
                format_log_entry("Colourise", "", rms_delta(base, result)))
            self._refresh()

        self._run_busy(work, on_result, "Colourising…", "Colourise failed")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q`
Expected: PASS — the two new tests plus all existing main-window tests (apply, colourise, busy-gating) stay green.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/main_window.py tests/ui/test_main_window.py
git commit -m "refactor: _run_busy helper (finally-safe) + migrate apply/colourise

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Threshold-gated visuals — BusyBar + grey label + busy-cursor

**Files:**
- Modify: `seestar_processor/ui/main_window.py` (imports; `__init__` busy state ~86-90 & right-panel ~128-131; `_set_busy` from Task 2)
- Modify: `seestar_processor/ui/worker.py` (remove `BusyOverlay`)
- Test: `tests/ui/test_main_window.py`; `tests/ui/test_worker.py`

**Interfaces:**
- Consumes: `BusyBar` and `BUSY_BAR_HEIGHT` from `seestar_processor/ui/busy_bar.py` (Task 1); `_run_busy` / `_set_busy(busy, label)` (Task 2).
- Produces: threshold-gated `_set_busy`; `_show_busy_visuals()` / `_hide_busy_visuals()` / `_tick_ellipsis()`; new state `self._busy_bar`, `self._busy_label`, `self._busy_shown`, `self._cursor_active`, `self._busy_timer`, `self._ellipsis_timer`, `self._busy_label_text`, `self._ellipsis_n`; module constant `BUSY_DELAY_MS = 400`. `BusyOverlay` no longer exists in `worker.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_main_window.py`:

```python
def test_set_busy_gates_immediately_but_delays_visuals(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._set_busy(True, "Applying Stretch…")
    assert win._busy is True
    assert win._back_btn.isEnabled() is False          # gate is immediate
    assert win._busy_shown is False                    # visuals delayed by the timer
    assert win._busy_timer.isActive() is True
    win._set_busy(False)
    assert win._busy is False
    assert win._busy_timer.isActive() is False
    assert win._back_btn.isEnabled() is True


def test_show_and_hide_busy_visuals_balance_cursor(qtbot, tmp_path):
    from PySide6.QtWidgets import QApplication
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._busy_label_text = "Colourising…"
    win._show_busy_visuals()
    assert win._busy_shown is True
    assert win._busy_bar.isHidden() is False
    assert "Colourising…" in win._busy_label.text()
    assert win._cursor_active is True
    win._hide_busy_visuals()
    assert win._busy_shown is False
    assert win._busy_bar.isHidden() is True
    assert win._busy_label.text() == ""
    assert win._cursor_active is False
    assert QApplication.overrideCursor() is None       # balanced, no leftover override
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py::test_set_busy_gates_immediately_but_delays_visuals tests/ui/test_main_window.py::test_show_and_hide_busy_visuals_balance_cursor -q`
Expected: FAIL with `AttributeError` (`_busy_shown` / `_show_busy_visuals` / `_busy_timer` do not exist).

- [ ] **Step 3a: Update imports in `main_window.py`**

Change the QtCore and QtWidgets imports and the worker import:

```python
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)
```

```python
from .busy_bar import BusyBar
from .worker import run_async
```

Add the module constant near the top of `main_window.py` (next to `_ASPECT_RATIO`):

```python
BUSY_DELAY_MS = 400   # ms before busy visuals appear; sub-threshold ops show nothing
```

- [ ] **Step 3b: Replace the busy state in `__init__`**

Replace `self._busy_overlay = BusyOverlay()` (line ~90) with:

```python
        self._busy_bar = BusyBar()
        self._busy_shown = False        # whether the delayed visuals are currently up
        self._cursor_active = False     # whether an override cursor is currently set
        self._busy_label_text = ""      # base label text (ellipsis animation appends)
        self._ellipsis_n = 0
        self._busy_timer = QTimer(self)
        self._busy_timer.setSingleShot(True)
        self._busy_timer.timeout.connect(self._show_busy_visuals)
        self._ellipsis_timer = QTimer(self)
        self._ellipsis_timer.setInterval(BUSY_DELAY_MS)
        self._ellipsis_timer.timeout.connect(self._tick_ellipsis)
```

- [ ] **Step 3c: Add the grey busy label to the right panel**

Directly after the `self._status` label block (lines ~128-131), add a dedicated grey busy label:

```python
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #ff6b6b;")
        self._right_layout.addWidget(self._status)
        self._busy_label = QLabel("")
        self._busy_label.setStyleSheet("color: #9aa0a6;")   # neutral grey, not error-red
        self._right_layout.addWidget(self._busy_label)
```

- [ ] **Step 3d: Rewrite `_set_busy` and add the visual helpers**

Replace the whole `_set_busy` body (from Task 2) with the threshold-gated version and add three helpers:

```python
    def _set_busy(self, busy: bool, label: str = "Working…") -> None:
        self._busy = busy
        if busy:
            self._busy_label_text = label
            self._busy_timer.start(BUSY_DELAY_MS)   # visuals only if op outlasts it
        else:
            self._busy_timer.stop()
            self._hide_busy_visuals()               # no-op if visuals never showed
        self._back_btn.setDisabled(busy)            # gating stays immediate
        self._next_btn.setDisabled(busy)
        if hasattr(self._panel, "apply_btn"):
            self._panel.apply_btn.setDisabled(busy)

    def _show_busy_visuals(self) -> None:
        self._busy_bar.show_over(self.image_view)
        self._ellipsis_n = 0
        self._busy_label.setText(self._busy_label_text)
        self._ellipsis_timer.start()
        if not self._cursor_active:
            QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
            self._cursor_active = True
        self._busy_shown = True

    def _hide_busy_visuals(self) -> None:
        self._ellipsis_timer.stop()
        if self._busy_shown:
            self._busy_bar.hide_bar()
            self._busy_label.setText("")
        if self._cursor_active:
            QApplication.restoreOverrideCursor()
            self._cursor_active = False
        self._busy_shown = False

    def _tick_ellipsis(self) -> None:
        self._ellipsis_n = (self._ellipsis_n + 1) % 4
        self._busy_label.setText(self._busy_label_text + "." * self._ellipsis_n)
```

- [ ] **Step 3e: Remove `BusyOverlay` from `worker.py`**

Delete the `BusyOverlay` class (lines ~49-69) and its now-unused imports from `seestar_processor/ui/worker.py`. After removal the import line should be:

```python
from PySide6.QtCore import QObject, QRunnable, Slot
```

(Remove `Qt`, `QColor`, `QPainter`, `QLabel`, `QVBoxLayout`, `QWidget` — verify none are referenced elsewhere in `worker.py`; only `BusyOverlay` used them.)

- [ ] **Step 3f: Update `test_worker.py`**

Replace `test_busy_overlay_constructs` and the `BusyOverlay` import in `tests/ui/test_worker.py`. The import line becomes:

```python
from seestar_processor.ui.worker import run_async  # noqa: E402
```

Delete `test_busy_overlay_constructs` entirely (the `BusyBar` behaviour is covered by `tests/ui/test_busy_bar.py`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py tests/ui/test_worker.py tests/ui/test_busy_bar.py -q`
Expected: PASS — the two new visual tests plus all existing tests green; no reference to `BusyOverlay` remains.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/main_window.py seestar_processor/ui/worker.py tests/ui/test_main_window.py tests/ui/test_worker.py
git commit -m "feat: threshold-gated busy visuals (BusyBar + grey label + busy-cursor)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Move export off the UI thread + retire `_guarded`

**Files:**
- Modify: `seestar_processor/ui/main_window.py` (`export_final` at ~602-638; remove `_guarded` at ~590-600)
- Test: `tests/ui/test_main_window.py` (rewrite `test_export_failure_is_surfaced` at ~231-236; the two export file tests at ~416-454 stay, verified)

**Interfaces:**
- Consumes: `_run_busy(work, on_result, label, err_prefix)` (Task 2). `save_tiff` / `save_png` / `save_fits` from `..core.export`; `RCAstro`, `resolve_binary`, `rcastro_valid`.
- Produces: `export_final` runs its file-writing through `_run_busy` (off the UI thread when `_async_enabled`). `_guarded` is removed.

- [ ] **Step 1: Write the failing test + rewrite the `_guarded` test**

First, add a spy test that genuinely fails before the migration — the old `export_final` never calls `_run_busy`:

```python
def test_export_single_routes_through_run_busy(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    out = tmp_path / "pic.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    calls = []
    monkeypatch.setattr(win, "_run_busy",
                        lambda work, on_result, label, err_prefix: calls.append(label))
    win.export_final("PNG")
    assert calls == ["Exporting…"]     # export now goes through the busy helper
```

Then replace `test_export_failure_is_surfaced` (it currently calls the soon-removed `_guarded`) with an export-path error test:

```python
def test_export_failure_is_surfaced(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    import seestar_processor.ui.main_window as mw
    win = _window(qtbot, tmp_path)  # _async_enabled = False -> inline
    win.open_fits(_make_fits(tmp_path))
    out = tmp_path / "pic.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(mw, "save_png",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    win.export_final("PNG")
    assert "Export failed: disk full" in win._status.text()
    assert win._busy is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py::test_export_single_routes_through_run_busy -q`
Expected: FAIL with `assert [] == ['Exporting…']` — the current `export_final` writes directly and never calls `_run_busy`. (`test_export_failure_is_surfaced` also no longer references `_guarded`; it pins the post-migration error path.)

- [ ] **Step 3: Rewrite `export_final` and remove `_guarded`**

Delete the `_guarded` method (lines ~590-600). Replace `export_final` with:

```python
    def export_final(self, fmt: str) -> None:
        if self.project is None:
            return
        img = self.project.current()
        if fmt == "Starless + Stars (two TIFFs)":
            if not rcastro_valid(self.settings):
                self._status.setText("Starless + stars split needs RC-Astro (see Settings).")
                return
            folder = QFileDialog.getExistingDirectory(self, "Export starless + stars to…")
            if not folder:
                return

            def _split():
                rc = RCAstro(resolve_binary(self.settings.rcastro_path))
                starless, stars = rc.remove_stars(img, runner=self._rc_runner)
                save_tiff(starless, os.path.join(folder, "starless.tif"))
                save_tiff(stars, os.path.join(folder, "stars.tif"))

            self._run_busy(_split,
                           lambda _: self.log_panel.append_entry("Exported starless.tif + stars.tif"),
                           "Exporting…", "Export failed")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", "", "TIFF (*.tiff);;PNG (*.png);;FITS (*.fits)"
        )
        if not path:
            return
        if fmt == "PNG":
            if not path.lower().endswith(".png"):
                path += ".png"
            save, name = save_png, os.path.basename(path)
        elif fmt == "FITS":
            if not path.lower().endswith((".fits", ".fit")):
                path += ".fits"
            save, name = save_fits, os.path.basename(path)
        else:
            if not path.lower().endswith((".tiff", ".tif")):
                path += ".tiff"
            save, name = save_tiff, os.path.basename(path)
        self._run_busy(lambda: save(img, path),
                       lambda _: self.log_panel.append_entry(f"Exported {name}"),
                       "Exporting…", "Export failed")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q`
Expected: PASS — `test_export_single_routes_through_run_busy`, `test_export_failure_is_surfaced`, `test_export_final_split_writes_two_tiffs`, and `test_export_final_single_file` all green (the file tests run inline because `_window` sets `_async_enabled = False`).

- [ ] **Step 5: Full suite + commit**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: PASS (all tests green).

```bash
git add seestar_processor/ui/main_window.py tests/ui/test_main_window.py
git commit -m "fix: run export off the UI thread via _run_busy; retire _guarded

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Thin animated top-edge indeterminate bar replacing the dimming overlay → Task 1 (`BusyBar`) + Task 3 (wired in, `BusyOverlay` removed). ✅
- Dedicated grey busy label separate from red error label, with animated ellipsis → Task 3 (`_busy_label`, `_tick_ellipsis`). ✅
- App busy-cursor, balanced set/restore → Task 3 (`_cursor_active`, `_show/_hide_busy_visuals`, balance test). ✅
- ~400 ms threshold; gate immediate, visuals delayed → Task 3 (`BUSY_DELAY_MS`, `_busy_timer`, gating test). ✅
- `_run_busy` finally-safe consolidation; migrate apply_current & _colourise → Task 2 (+ regression test). ✅
- Export off the UI thread; retire `_guarded` → Task 4. ✅
- Dialogs untouched; indeterminate only → no task touches them; no `set_fraction`. ✅
- Test seams preserved (`_async_enabled`, injectable runners) → used throughout. ✅

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows complete code. ✅

**Type consistency:** `_run_busy(work, on_result, label, err_prefix)` signature identical in Tasks 2 & 4. `_set_busy(busy, label="Working…")` introduced in Task 2, rewritten (same signature) in Task 3. `BusyBar` / `BUSY_BAR_HEIGHT` names match between Task 1 and Task 3 import. `_busy_shown` / `_cursor_active` / `_busy_timer` used consistently. ✅
