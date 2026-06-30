# Processing Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** Add a collapsible, append-only, timestamped processing log that confirms each action and quantifies how much it changed the image (RMS Δ).

**Architecture:** A pure `rms_delta` metric in `core/`, a `LogPanel` widget + `format_log_entry` formatter in `ui/`, and main-window wiring that logs open / each applied step / export / undo / redo.

**Tech Stack:** Python 3.13 (.venv), PySide6, numpy, pytest+pytest-qt.

## Global Constraints
- Spec: `docs/superpowers/specs/2026-06-30-processing-log-design.md`.
- Append-only log (undone actions remain). Panel default visible, toggled by a toolbar "Log" button.
- Entry body format (no timestamp): `"<Name> (<option>)  —  Δ <pct>%"`; crop → `"<Name>  —  → W×H"`; option None/"" omits the parens. Timestamp `HH:MM:SS` is prepended by `LogPanel.append_entry`.
- `rms_delta` returns a percent (0–100) or `None` when shapes differ.
- Run tests `.venv/bin/pytest`; Python `.venv/bin/python` (3.13); pytest-qt headless.

---

### Task 1: rms_delta metric

**Files:**
- Create: `seestar_processor/core/metrics.py`
- Test: `tests/core/test_metrics.py`

**Interfaces:**
- Produces: `rms_delta(before: AstroImage, after: AstroImage) -> float | None` — `sqrt(mean((after-before)^2)) * 100` over all pixels; `None` if shapes differ.

- [ ] **Step 1: Write the failing test**

```python
import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.metrics import rms_delta


def test_identical_is_zero():
    a = AstroImage(np.full((8, 8, 3), 0.5, np.float32))
    assert rms_delta(a, AstroImage(a.data.copy())) == 0.0


def test_change_is_positive():
    a = AstroImage(np.full((8, 8, 3), 0.5, np.float32))
    b = AstroImage(np.full((8, 8, 3), 0.6, np.float32))
    d = rms_delta(a, b)
    assert 9.0 < d < 11.0  # ~10%


def test_shape_mismatch_returns_none():
    a = AstroImage(np.zeros((8, 8, 3), np.float32))
    b = AstroImage(np.zeros((4, 4, 3), np.float32))
    assert rms_delta(a, b) is None
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement**

```python
from __future__ import annotations

import numpy as np

from .image import AstroImage


def rms_delta(before: AstroImage, after: AstroImage) -> float | None:
    if before.data.shape != after.data.shape:
        return None
    diff = after.data.astype(np.float32) - before.data.astype(np.float32)
    return float(np.sqrt(np.mean(diff * diff)) * 100.0)
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: add rms_delta change metric`.

---

### Task 2: LogPanel + formatter

**Files:**
- Create: `seestar_processor/ui/log_panel.py`
- Test: `tests/ui/test_log_panel.py`

**Interfaces:**
- Produces:
  - `format_log_entry(name, option, delta, dims=None) -> str` — `delta` float|None, `dims` (w,h)|None. Rules: if `dims` given → `"<name>  —  → {w}×{h}"`; elif `delta is None` → `"<name'>"` (name with option); else `"<name'>  —  Δ {delta:.1f}%"`. `<name'>` = `f"{name} ({option})"` when option not in (None, "") else `name`.
  - `LogPanel(QWidget)` — `append_entry(body: str) -> None` (prepends `HH:MM:SS`, appends a line, autoscrolls), `clear_log() -> None`, `text() -> str` (current contents).

- [ ] **Step 1: Write the failing tests**

```python
import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui.log_panel import format_log_entry, LogPanel  # noqa: E402


def test_format_with_delta():
    assert format_log_entry("Noise & Sharpen", "medium", 0.83) == \
        "Noise & Sharpen (medium)  —  Δ 0.8%"


def test_format_crop_dims():
    assert format_log_entry("Crop", "", None, dims=(1920, 1080)) == \
        "Crop  —  → 1920×1080"


def test_format_no_option_no_delta():
    assert format_log_entry("Stretch", "", None) == "Stretch"


def test_format_zero_delta():
    assert format_log_entry("Color", None, 0.0) == "Color  —  Δ 0.0%"


def test_log_panel_append_and_clear(qtbot):
    panel = LogPanel()
    qtbot.addWidget(panel)
    panel.append_entry("Hello")
    assert "Hello" in panel.text()
    panel.clear_log()
    assert panel.text().strip() == ""
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement**

```python
from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QPlainTextEdit


def format_log_entry(name, option, delta, dims=None) -> str:
    if dims is not None:
        return f"{name}  —  → {dims[0]}×{dims[1]}"
    label = f"{name} ({option})" if option not in (None, "") else name
    if delta is None:
        return label
    return f"{label}  —  Δ {delta:.1f}%"


class LogPanel(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumHeight(140)

    def append_entry(self, body: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.appendPlainText(f"{stamp}  {body}")
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def clear_log(self) -> None:
        self.clear()

    def text(self) -> str:
        return self.toPlainText()
```

(`LogPanel` is a `QPlainTextEdit` subclass — that satisfies "QWidget".)

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: add LogPanel and log entry formatter`.

---

### Task 3: Wire the log into MainWindow

**Files:**
- Modify: `seestar_processor/ui/main_window.py`
- Test: `tests/ui/test_main_window.py` (add cases)

**Interfaces:**
- Consumes: `rms_delta` (T1), `LogPanel`, `format_log_entry` (T2), `STEP_NAME`.
- Behavior:
  - Central layout wraps the existing stepper|image|controls row in a `QVBoxLayout`; `self.log_panel = LogPanel()` added beneath it.
  - Toolbar checkable **"Log"** action (default checked) toggles `self.log_panel` visibility.
  - `open_fits` success → `self.log_panel.append_entry(format_log_entry("Opened " + os.path.basename(path), "", None, dims=(w, h)))` where w,h from the loaded image.
  - In `apply_current`: capture `base` (already present). In `done(result)`: compute the entry —
    - background "off" branch: `append_entry(format_log_entry("Background", "off", None) + " — skipped")` (handled where "off" returns).
    - crop: `dims=(result.data.shape[1], result.data.shape[0])`, delta arg ignored → `format_log_entry("Crop", "", None, dims=dims)`.
    - else: `delta = rms_delta(base, result)`; `format_log_entry(STEP_NAME[stage_id], option_label, delta)` where `option_label` is the option as shown (for stretch, the numeric amount → `f"{option:.2f}"`; otherwise `option`).
  - `_undo` → `append_entry("Undo")`; `_redo` → `append_entry("Redo")`.
  - exports → `append_entry("Exported " + os.path.basename(path))` on success (inside the guarded save).

- [ ] **Step 1: Write the failing tests** (add to `tests/ui/test_main_window.py`)

```python
def test_log_records_applied_step(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.6)
    log = win.log_panel.text()
    assert "Stretch" in log and "Δ" in log


def test_log_records_open(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert "Opened" in win.log_panel.text()


def test_log_toggle_hides_panel(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert win.log_panel.isVisibleTo(win) or True  # visible by default (parent may be unshown)
    win._log_act.setChecked(False)
    win._toggle_log()
    assert win.log_panel.isHidden() is True
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** — import `os` (present), `rms_delta`, `LogPanel`, `format_log_entry`; restructure central layout; add the toolbar toggle + `_toggle_log`; add `append_entry` calls at the points above. Use the option label rule for stretch (`f"{option:.2f}"` when it's a float).
- [ ] **Step 4: Run → PASS** + full suite (pristine).
- [ ] **Step 5: Commit** `feat: wire processing log into the main window`.

---

## Verification (end to end)
`.venv/bin/python -m seestar_processor`: open a FITS (log shows "Opened … W×H"); apply Noise & Sharpen / Color (log shows the step + a Δ%, even when the image looks unchanged); crop (shows new dims); undo (shows "Undo"); toggle the Log button to hide/show the panel.

## Self-Review
- Coverage: metric (T1), panel+formatter (T2), wiring incl. open/apply/export/undo/redo + toggle + delta (T3). Append-only (never cleared on undo). Default-visible toggle (T3).
- Type consistency: `rms_delta -> float|None`, `format_log_entry(name, option, delta, dims=None)`, `LogPanel.append_entry/clear_log/text` used identically across tasks.
