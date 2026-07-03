# Visual Polish (Tier 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Nocturne screenshot-worthy — a semantic colour system, coloured step states in the stepper, toolbar icons with grouping, and styled sliders/dialogs — with zero behavioural change.

**Architecture:** Restructure `ui/theme.py` around named colour tokens and build the full QSS (including slider/dialog polish) from them. Add a pure `step_state()` + a `StepDelegate` to `ui/stepper.py`. Add hand-authored SVG icons under `seestar_processor/assets/icons/` and a tinting `ui/icons.py` loader. Wire icons + separators into the toolbar.

**Tech Stack:** PySide6 (QSS, QStyledItemDelegate, QtSvg), Python 3.11+.

## Global Constraints

- Package `seestar_processor` (no rename). Use the venv (`.venv/bin/python`, `.venv/bin/pytest`); system python is 3.9 and fails.
- UI tests run headless: `QT_QPA_PLATFORM=offscreen`.
- **Visual only** — no processing/pipeline/behaviour changes. Existing behaviour tests stay green; only the stepper's text-assertion test is updated to the new rendering.
- Icons are original hand-authored SVGs (no third-party licensing).
- Assets live in `seestar_processor/assets/icons/` so they travel with the package.
- Commit after each task. Create the `visual-polish` branch first (do not start on `main`).

---

## File Structure

- `seestar_processor/ui/theme.py` — colour tokens + `build_stylesheet()` + `apply_dark_theme()`.
- `seestar_processor/ui/stepper.py` — `step_state()` pure fn + `StepDelegate` + `Stepper.state_at()`.
- `seestar_processor/ui/icons.py` — NEW: `load_icon(name, color)` tinting loader.
- `seestar_processor/assets/icons/*.svg` — NEW: 13 monochrome line icons.
- `seestar_processor/ui/main_window.py` — toolbar icons + group separators.
- `TODO.md` — Tier 2/3 roadmap.
- Tests: `tests/ui/test_theme.py`, `tests/ui/test_stepper.py` (update), `tests/ui/test_icons.py`.

---

## Task 0: Branch setup

- [ ] **Step 1: Create the feature branch**

```bash
cd /Volumes/Work/Code/Editor
git checkout -b visual-polish
git status   # expect: On branch visual-polish, clean
```

---

## Task 1: `theme.py` — colour tokens + full themed QSS

**Files:**
- Modify: `seestar_processor/ui/theme.py`
- Test: `tests/ui/test_theme.py`

**Interfaces:**
- Produces: token constants `BG_0, BG_1, BG_2, BG_3, BORDER, ACCENT, ACCENT_HI, SUCCESS, WARNING, DANGER, TEXT, TEXT_DIM, TEXT_FAINT`; `build_stylesheet() -> str`; `apply_dark_theme(app) -> None`.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_theme.py`:

```python
from seestar_processor.ui import theme


def test_tokens_defined():
    for name in ("BG_0", "BG_1", "BG_2", "BG_3", "ACCENT", "SUCCESS",
                 "WARNING", "DANGER", "TEXT", "TEXT_DIM", "TEXT_FAINT"):
        val = getattr(theme, name)
        assert isinstance(val, str) and val.startswith("#")


def test_build_stylesheet_uses_tokens():
    qss = theme.build_stylesheet()
    assert isinstance(qss, str) and len(qss) > 500
    # semantic colours flow into the stylesheet
    assert theme.ACCENT in qss
    assert theme.BG_1 in qss
    # slider + progressbar polish present
    assert "QSlider" in qss and "QProgressBar" in qss
    assert "::sub-page" in qss  # accent-filled slider track
```

- [ ] **Step 2: Run it, expect failure**

Run: `.venv/bin/pytest tests/ui/test_theme.py -q`
Expected: FAIL (`build_stylesheet` / tokens not defined).

- [ ] **Step 3: Implement**

Replace the entire contents of `seestar_processor/ui/theme.py` with:

```python
from __future__ import annotations

# --- semantic colour tokens ---
BG_0 = "#16171a"     # deepest (canvas)
BG_1 = "#1e1f22"     # window
BG_2 = "#26282c"     # panels / toolbar
BG_3 = "#2f3237"     # inputs / raised
BORDER = "#3c4046"
ACCENT = "#2dd4bf"   # teal
ACCENT_HI = "#34e3cd"
SUCCESS = "#3fb950"  # green
WARNING = "#e3b341"  # amber
DANGER = "#f85149"   # red
TEXT = "#e6e6e6"
TEXT_DIM = "#8a9099"
TEXT_FAINT = "#5e636b"


def build_stylesheet() -> str:
    return f"""
* {{ color: {TEXT}; font-size: 14px; }}
QMainWindow, QWidget {{ background-color: {BG_1}; }}
QToolBar {{ background: {BG_2}; border: none; spacing: 4px; padding: 6px; }}
QToolBar::separator {{ background: {BORDER}; width: 1px; margin: 4px 6px; }}
QToolBar QToolButton {{ padding: 6px 10px; border-radius: 8px; color: {TEXT_DIM}; }}
QToolBar QToolButton:hover {{ background: {BG_3}; color: {TEXT}; }}
QToolBar QToolButton:pressed {{ background: {BORDER}; }}
QToolBar QToolButton:checked {{ background: {BG_3}; color: {ACCENT}; }}
QToolBar QToolButton:disabled {{ color: {TEXT_FAINT}; }}

QLabel#stageTitle {{ font-size: 20px; font-weight: 600; color: #ffffff; padding-bottom: 8px; }}

QListWidget {{ background: {BG_2}; border: none; outline: 0; padding: 8px; }}
QListWidget::item {{ padding: 2px; border-radius: 8px; margin: 1px 0; }}
QListWidget::item:selected {{ background: transparent; }}

QComboBox, QLineEdit {{ background: {BG_3}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 6px 10px; }}
QComboBox:focus, QLineEdit:focus {{ border: 1px solid {ACCENT}; }}

QPushButton {{ background: {BG_3}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 8px 14px; }}
QPushButton:hover {{ background: #3e4248; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; background: #2a2c30; }}
QPushButton#primary {{ background: {ACCENT}; color: #06201c; font-weight: 600; border: none; }}
QPushButton#primary:hover {{ background: {ACCENT_HI}; }}
QPushButton#primary:disabled {{ background: #2a2c30; color: {TEXT_FAINT}; }}

QGraphicsView {{ background: {BG_0}; border: 1px solid #2c2f34; }}

QSlider::groove:horizontal {{ height: 6px; background: {BG_3}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::add-page:horizontal {{ background: {BG_3}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 16px; height: 16px;
    margin: -6px 0; border-radius: 8px; }}
QSlider::handle:horizontal:hover {{ background: {ACCENT_HI}; }}

QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px;
    border: 1px solid {BORDER}; background: {BG_3}; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {ACCENT}; border: 1px solid {ACCENT}; }}

QProgressBar {{ background: {BG_3}; border: none; border-radius: 6px; height: 10px;
    text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 6px; }}

QHeaderView::section {{ background: {BG_3}; color: {TEXT_DIM}; border: none;
    padding: 6px 8px; }}
QTableWidget {{ background: {BG_2}; gridline-color: {BORDER};
    border: 1px solid {BORDER}; border-radius: 8px; }}
QTableWidget::item:hover {{ background: {BG_3}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #4a4f56; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


def apply_dark_theme(app) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(build_stylesheet())
```

- [ ] **Step 4: Run tests, expect pass**

Run: `.venv/bin/pytest tests/ui/test_theme.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/theme.py tests/ui/test_theme.py
git commit -m "feat: colour-token theme + styled sliders/dialogs QSS"
```

---

## Task 2: `stepper.py` — coloured step states

**Files:**
- Modify: `seestar_processor/ui/stepper.py`
- Modify: `tests/ui/test_stepper.py`

**Interfaces:**
- Consumes: theme tokens.
- Produces: `step_state(index, current_index, done_indexes, enabled) -> str` ("current"|"done"|"upcoming"|"locked"); `Stepper.state_at(index) -> str`; a `StepDelegate` painting badges. `Stepper` keeps `set_stages`/`set_current`/`mark_done`/`stageSelected`/`_on_click`.

- [ ] **Step 1: Update the tests**

In `tests/ui/test_stepper.py`, REPLACE `test_mark_done_prefixes_check` with:

```python
def test_step_state_pure():
    from seestar_processor.ui.stepper import step_state
    # locked wins regardless
    assert step_state(2, 2, {2}, enabled=False) == "locked"
    # current wins over done
    assert step_state(1, 1, {1}, enabled=True) == "current"
    assert step_state(0, 3, {0, 1}, enabled=True) == "done"
    assert step_state(4, 3, {0, 1}, enabled=True) == "upcoming"


def test_mark_done_sets_done_state(qtbot):
    step = Stepper()
    qtbot.addWidget(step)
    step.set_stages(path_stages("in_app"))
    step.set_current(0)                     # "load" is current
    step.mark_done({"crop"})
    crop_row = next(i for i, s in enumerate(path_stages("in_app")) if s.id == "crop")
    assert step.state_at(crop_row) == "done"


def test_current_state(qtbot):
    step = Stepper()
    qtbot.addWidget(step)
    step.set_stages(path_stages("in_app"))
    step.set_current(2)
    assert step.state_at(2) == "current"
```

(The other three tests — `test_set_stages_populates_rows`, `test_clicking_enabled_stage_emits_index`, `test_disabled_stage_does_not_emit` — stay as they are.)

- [ ] **Step 2: Run it, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_stepper.py -q`
Expected: FAIL (`step_state` / `state_at` not defined).

- [ ] **Step 3: Implement**

Replace the entire contents of `seestar_processor/ui/stepper.py` with:

```python
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStyledItemDelegate

from .theme import ACCENT, BG_3, SUCCESS, TEXT, TEXT_DIM, TEXT_FAINT


def step_state(index: int, current_index: int, done_indexes, enabled: bool) -> str:
    """Pure state decision for a stepper row."""
    if not enabled:
        return "locked"
    if index == current_index:
        return "current"
    if index in done_indexes:
        return "done"
    return "upcoming"


class StepDelegate(QStyledItemDelegate):
    """Paints a status badge + label per row (state from the parent Stepper)."""

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        s.setHeight(max(s.height(), 40))
        return s

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        stepper = self.parent()
        state = stepper.state_at(index.row())
        r = option.rect
        cx, cy = r.left() + 18, r.center().y()

        # current: subtle background + accent left bar
        if state == "current":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(BG_3))
            painter.drawRoundedRect(QRectF(r.left() + 4, r.top() + 2,
                                           r.width() - 8, r.height() - 4), 8, 8)
            painter.setBrush(QColor(ACCENT))
            painter.drawRoundedRect(QRectF(r.left() + 4, r.top() + 6, 3,
                                           r.height() - 12), 1.5, 1.5)

        # badge
        badge = {"done": SUCCESS, "current": ACCENT,
                 "upcoming": TEXT_FAINT, "locked": TEXT_FAINT}[state]
        painter.setPen(QPen(QColor(badge), 2))
        if state == "done":
            painter.setBrush(QColor(SUCCESS))
            painter.drawEllipse(QRectF(cx - 8, cy - 8, 16, 16))
            painter.setPen(QPen(QColor("#06201c"), 2))
            painter.drawLine(int(cx - 3), int(cy), int(cx - 1), int(cy + 3))
            painter.drawLine(int(cx - 1), int(cy + 3), int(cx + 4), int(cy - 3))
        elif state == "current":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(cx - 8, cy - 8, 16, 16))
            painter.setBrush(QColor(ACCENT))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(cx - 3, cy - 3, 6, 6))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(cx - 6, cy - 6, 12, 12))

        # label
        label = index.data(Qt.ItemDataRole.DisplayRole) or ""
        color = {"done": TEXT, "current": TEXT,
                 "upcoming": TEXT_DIM, "locked": TEXT_FAINT}[state]
        font = QFont(painter.font())
        font.setBold(state == "current")
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(QRectF(r.left() + 36, r.top(), r.width() - 80, r.height()),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                         str(label))

        # "soon" pill for locked rows
        if state == "locked":
            pill = QRectF(r.right() - 48, cy - 9, 40, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(BG_3))
            painter.drawRoundedRect(pill, 9, 9)
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), "soon")

        painter.restore()


class Stepper(QListWidget):
    stageSelected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stages = []
        self._current = -1
        self._done: set = set()
        self.setItemDelegate(StepDelegate(self))
        self.itemClicked.connect(self._on_click)

    def set_stages(self, stages) -> None:
        self._stages = list(stages)
        self.clear()
        for stage in self._stages:
            item = QListWidgetItem(stage.label)
            if not stage.enabled:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.addItem(item)

    def _on_click(self, item) -> None:
        index = self.row(item)
        if 0 <= index < len(self._stages) and self._stages[index].enabled:
            self.stageSelected.emit(index)

    def set_current(self, index: int) -> None:
        self._current = index
        self.setCurrentRow(index)
        self.viewport().update()

    def mark_done(self, done_ids: set) -> None:
        self._done = {i for i, s in enumerate(self._stages) if s.id in done_ids}
        self.viewport().update()

    def state_at(self, index: int) -> str:
        stage = self._stages[index]
        return step_state(index, self._current, self._done, stage.enabled)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_stepper.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/stepper.py tests/ui/test_stepper.py
git commit -m "feat: coloured step states (done/current/upcoming/locked) in the stepper"
```

---

## Task 3: SVG icons + tinting loader

**Files:**
- Create: `seestar_processor/assets/icons/*.svg` (13 files)
- Create: `seestar_processor/ui/icons.py`
- Test: `tests/ui/test_icons.py`

**Interfaces:**
- Consumes: theme `TEXT`; `PySide6.QtSvg.QSvgRenderer`.
- Produces: `ICON_NAMES` (tuple), `load_icon(name: str, color: str = TEXT) -> QIcon` (cached; `FileNotFoundError` on unknown name).

- [ ] **Step 1: Create the SVG assets**

Create each file under `seestar_processor/assets/icons/`. Every file's content is one line:

`open.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
```

`settings.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/><circle cx="9" cy="7" r="2.2" fill="#fff"/><circle cx="15" cy="12" r="2.2" fill="#fff"/><circle cx="8" cy="17" r="2.2" fill="#fff"/></svg>
```

`save-recipe.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h12v18l-6-4-6 4z"/></svg>
```

`batch.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/></svg>
```

`stack.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 3 8l9 5 9-5z"/><path d="M3 13l9 5 9-5"/></svg>
```

`haoiii.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="12" r="6"/><circle cx="15" cy="12" r="6"/></svg>
```

`palette.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3s6 6 6 10a6 6 0 0 1-12 0c0-4 6-10 6-10z"/></svg>
```

`undo.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 8 5 12l4 4"/><path d="M5 12h9a5 5 0 1 1 0 10"/></svg>
```

`redo.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 8l4 4-4 4"/><path d="M19 12h-9a5 5 0 1 0 0 10"/></svg>
```

`before-after.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="5" width="16" height="14" rx="1"/><line x1="12" y1="5" x2="12" y2="19"/></svg>
```

`log.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="7" x2="19" y2="7"/><line x1="5" y1="12" x2="19" y2="12"/><line x1="5" y1="17" x2="14" y2="17"/></svg>
```

`fit.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9V4h5"/><path d="M20 9V4h-5"/><path d="M4 15v5h5"/><path d="M20 15v5h-5"/></svg>
```

`actual-size.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="1"/><rect x="9" y="9" width="6" height="6" rx="1"/></svg>
```

- [ ] **Step 2: Write the failing test**

Create `tests/ui/test_icons.py`:

```python
import xml.etree.ElementTree as ET

import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui.icons import ICON_NAMES, load_icon, _ICON_DIR  # noqa: E402


def test_all_named_svgs_exist_and_are_valid_xml():
    for name in ICON_NAMES:
        path = _ICON_DIR / f"{name}.svg"
        assert path.exists(), f"missing icon: {name}"
        ET.parse(str(path))  # raises if malformed


def test_load_icon_returns_icon(qtbot):
    icon = load_icon("stack")
    assert not icon.isNull()


def test_load_icon_cached(qtbot):
    assert load_icon("palette") is load_icon("palette")


def test_load_icon_unknown_raises(qtbot):
    with pytest.raises(FileNotFoundError):
        load_icon("does-not-exist")
```

- [ ] **Step 3: Run it, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_icons.py -q`
Expected: FAIL (module `seestar_processor.ui.icons` not found).

- [ ] **Step 4: Implement**

Create `seestar_processor/ui/icons.py`:

```python
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme import TEXT

_ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"

ICON_NAMES = (
    "open", "settings", "save-recipe", "batch", "stack", "haoiii", "palette",
    "undo", "redo", "before-after", "log", "fit", "actual-size",
)


@lru_cache(maxsize=None)
def load_icon(name: str, color: str = TEXT) -> QIcon:
    """Render an SVG icon tinted to `color` (source-in composite). Cached."""
    path = _ICON_DIR / f"{name}.svg"
    if not path.exists():
        raise FileNotFoundError(f"icon not found: {name}")
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return QIcon()
    size = QSize(48, 48)
    pm = QPixmap(size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    renderer.render(painter, QRectF(0, 0, size.width(), size.height()))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pm.rect(), QColor(color))
    painter.end()
    return QIcon(pm)
```

- [ ] **Step 5: Run tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_icons.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add seestar_processor/assets/icons seestar_processor/ui/icons.py tests/ui/test_icons.py
git commit -m "feat: hand-authored SVG icons + tinting loader"
```

---

## Task 4: Toolbar icons + grouping, roadmap, full suite

**Files:**
- Modify: `seestar_processor/ui/main_window.py` (`_build_toolbar`)
- Modify: `TODO.md`
- Test: `tests/ui/test_main_window.py` (add one)

**Interfaces:**
- Consumes: `icons.load_icon`; theme `ACCENT`.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_main_window.py`:

```python
def test_toolbar_actions_have_icons(qtbot, tmp_path):
    from PySide6.QtWidgets import QToolBar
    win = _window(qtbot, tmp_path)
    main = next(b for b in win.findChildren(QToolBar) if b.windowTitle() == "Main")
    labelled = [a for a in main.actions() if a.text()]
    assert labelled, "toolbar has labelled actions"
    assert all(not a.icon().isNull() for a in labelled), "every labelled action has an icon"
```

- [ ] **Step 2: Run it, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py::test_toolbar_actions_have_icons -q`
Expected: FAIL (actions have null icons).

- [ ] **Step 3: Implement**

In `seestar_processor/ui/main_window.py`, add the import near the other `.ui` imports:

```python
from .icons import load_icon
from .theme import ACCENT
```

Then in `_build_toolbar`, REPLACE the block of `tb.addAction(...)` calls (from `tb.addAction("Open FITS", ...)` through `tb.addAction("100%", ...)`) with this — everything after the "100%" action (the spacer / tools label) stays unchanged:

```python
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        # File
        tb.addAction(load_icon("open"), "Open FITS", self._choose_fits)
        tb.addAction(load_icon("settings"), "Settings", self._open_settings)
        tb.addSeparator()
        # Tools (primary features tinted with the accent)
        self._save_recipe_act = tb.addAction(load_icon("save-recipe"), "Save Recipe", self._save_recipe)
        tb.addAction(load_icon("batch"), "Batch…", self._open_batch)
        tb.addAction(load_icon("stack", ACCENT), "Stack…", self._open_stack)
        tb.addAction(load_icon("haoiii", ACCENT), "Ha/OIII…", self._open_haoiii)
        tb.addAction(load_icon("palette", ACCENT), "Palette…", self._open_palette)
        tb.addSeparator()
        # Edit / compare
        self._undo_act = tb.addAction(load_icon("undo"), "Undo", self._undo)
        self._redo_act = tb.addAction(load_icon("redo"), "Redo", self._redo)
        self._ba_act = tb.addAction(load_icon("before-after"), "Before/After", self._toggle_before_after)
        self._ba_act.setCheckable(True)
        self._log_act = tb.addAction(load_icon("log"), "Log", self._toggle_log)
        self._log_act.setCheckable(True)
        self._log_act.setChecked(True)
        tb.addSeparator()
        # View
        tb.addAction(load_icon("fit"), "Fit", self.image_view.fit)
        tb.addAction(load_icon("actual-size"), "100%", self.image_view.actual_size)
```

(Ensure `Qt` is imported in this module — it is used elsewhere; if not, add `from PySide6.QtCore import Qt`.)

- [ ] **Step 4: Run tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q`
Expected: PASS.

- [ ] **Step 5: Full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass. If `test_sharpen_changes_image_and_keeps_shape` fails, it's the known pre-existing flake — rerun it alone to confirm.

- [ ] **Step 6: Add the Tier 2/3 roadmap to the backlog**

In `TODO.md`, add a new section:

```markdown
## Visual polish — later tiers (Tier 1 shipped)
- [ ] **Tier 2 — canvas & panels (hero shot):** radial-gradient canvas backdrop; framed image
      with soft shadow; floating zoom pill (– 100% +); empty-state screen (logo + "Open or Stack
      to begin"); card-style right panel with per-step description strips; histogram styling
      (filled RGB + faint grid).
- [ ] **Tier 3 — branding & finish:** app icon + "Nocturne" wordmark; splash screen (with
      packaging); labelled before/after divider handle; spinner busy-overlay.
```

- [ ] **Step 7: Commit**

```bash
git add seestar_processor/ui/main_window.py tests/ui/test_main_window.py TODO.md
git commit -m "feat: toolbar icons + grouping; document Tier 2/3 visual roadmap"
```

---

## Definition of Done

- All tasks committed on `visual-polish`; full suite green.
- Launching the app shows: grouped toolbar with icons, coloured step states (green check =
  done, teal ring + left bar = current, dim = upcoming, faint "soon" = locked), accent-filled
  sliders, themed dialogs.
- No behavioural change; only the stepper text-assertion test was updated.
- After merge: take fresh screenshots for the testers/README.
- Finish with **superpowers:finishing-a-development-branch**.
```
