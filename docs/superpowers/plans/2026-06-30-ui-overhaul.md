# Seestar Processor v1.1 UI Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-panel window with a guided left-stepper + zoom/pan preview + Back/Next flow, styled with a dark theme — reusing the existing processing engine unchanged.

**Architecture:** New focused widgets under `seestar_processor/ui/` — `pipeline.py` (stage model), `theme.py` (dark QSS), `image_view.py` (QGraphicsView zoom/pan), `stepper.py` (left step list), `step_panels.py` (per-stage controls) — wired by a slimmed `main_window.py`. The `Project` history, `steps/`, `tools/`, `core/`, and `ui/preview.to_qimage` are reused as-is.

**Tech Stack:** Python 3.13 (`.venv`), PySide6 (Qt Widgets/GraphicsView), pytest + pytest-qt.

## Global Constraints

- Engine is reused unchanged: `Project` (history/project.py), `BackgroundStep`, `StretchStep`, `load_fits`, `to_qimage`, `save_tiff`/`save_jpeg`, `Settings`/`graxpert_valid`. Do NOT modify those modules in this plan.
- Pipeline order & enablement (verbatim): `Load`(enabled) · `Crop`(disabled) · `Background`(enabled) · `Color`(disabled) · `Deconvolution`(disabled) · `Noise`(disabled) · `Stretch`(enabled) · `Final Fixes`(disabled) · `Export`(enabled).
- Processing-stage → history-step-name map: `background`→`"Background"`, `stretch`→`"Stretch"`. History order is `["background", "stretch"]`.
- Strength options for processing stages: `["Small", "Medium", "Large"]`, default `"Medium"`.
- Run tests with `.venv/bin/pytest`; Python is `.venv/bin/python` (3.13). pytest-qt `qtbot`/`qapp` fixtures work headless here (no env var needed).
- Tests must need NO GraXpert binary (drive the engine directly / via fakes).

---

### Task 1: Pipeline stage model

**Files:**
- Create: `seestar_processor/ui/pipeline.py`
- Test: `tests/ui/test_pipeline.py`

**Interfaces:**
- Produces: `Stage` (frozen dataclass: `id: str`, `label: str`, `kind: str`, `enabled: bool`), `PIPELINE: list[Stage]`, `next_enabled(index: int) -> int`, `prev_enabled(index: int) -> int`, `STEP_NAME: dict[str, str]`, `PROCESSING_ORDER: list[str]`. `kind ∈ {"load","process","stretch","export","placeholder"}`.

- [ ] **Step 1: Write the failing test**

`tests/ui/test_pipeline.py`:
```python
from seestar_processor.ui.pipeline import (
    PIPELINE, next_enabled, prev_enabled, STEP_NAME, PROCESSING_ORDER,
)


def _index(stage_id):
    return next(i for i, s in enumerate(PIPELINE) if s.id == stage_id)


def test_pipeline_order_and_enablement():
    ids = [s.id for s in PIPELINE]
    assert ids == [
        "load", "crop", "background", "color", "deconvolution",
        "noise", "stretch", "final_fixes", "export",
    ]
    enabled = {s.id for s in PIPELINE if s.enabled}
    assert enabled == {"load", "background", "stretch", "export"}


def test_next_enabled_skips_disabled_and_clamps():
    assert next_enabled(_index("load")) == _index("background")
    assert next_enabled(_index("background")) == _index("stretch")
    assert next_enabled(_index("stretch")) == _index("export")
    last = _index("export")
    assert next_enabled(last) == last  # clamp at end


def test_prev_enabled_skips_disabled_and_clamps():
    assert prev_enabled(_index("stretch")) == _index("background")
    assert prev_enabled(_index("background")) == _index("load")
    assert prev_enabled(_index("load")) == _index("load")  # clamp at start


def test_step_name_and_order():
    assert STEP_NAME == {"background": "Background", "stretch": "Stretch"}
    assert PROCESSING_ORDER == ["background", "stretch"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/ui/test_pipeline.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/ui/pipeline.py`:
```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    id: str
    label: str
    kind: str  # "load" | "process" | "stretch" | "export" | "placeholder"
    enabled: bool


PIPELINE: list[Stage] = [
    Stage("load", "Load", "load", True),
    Stage("crop", "Crop", "placeholder", False),
    Stage("background", "Background", "process", True),
    Stage("color", "Color", "placeholder", False),
    Stage("deconvolution", "Deconvolution", "placeholder", False),
    Stage("noise", "Noise", "placeholder", False),
    Stage("stretch", "Stretch", "stretch", True),
    Stage("final_fixes", "Final Fixes", "placeholder", False),
    Stage("export", "Export", "export", True),
]

STEP_NAME = {"background": "Background", "stretch": "Stretch"}
PROCESSING_ORDER = ["background", "stretch"]


def next_enabled(index: int) -> int:
    for i in range(index + 1, len(PIPELINE)):
        if PIPELINE[i].enabled:
            return i
    return index


def prev_enabled(index: int) -> int:
    for i in range(index - 1, -1, -1):
        if PIPELINE[i].enabled:
            return i
    return index
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/ui/test_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/pipeline.py tests/ui/test_pipeline.py
git commit -m "feat: add UI pipeline stage model"
```

---

### Task 2: Dark theme

**Files:**
- Create: `seestar_processor/ui/theme.py`
- Test: `tests/ui/test_theme.py`

**Interfaces:**
- Produces: `apply_dark_theme(app) -> None` — sets the Fusion style and a dark stylesheet on the QApplication. `ACCENT: str` (hex accent color).

- [ ] **Step 1: Write the failing test**

`tests/ui/test_theme.py`:
```python
import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui.theme import apply_dark_theme, ACCENT  # noqa: E402


def test_apply_dark_theme_sets_stylesheet(qapp):
    apply_dark_theme(qapp)
    qss = qapp.styleSheet()
    assert isinstance(qss, str) and len(qss) > 0
    assert ACCENT in qss
    assert qapp.style().objectName().lower() == "fusion"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/ui/test_theme.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/ui/theme.py`:
```python
from __future__ import annotations

ACCENT = "#2dd4bf"  # teal accent

_DARK_QSS = f"""
* {{ color: #e6e6e6; font-size: 13px; }}
QMainWindow, QWidget {{ background-color: #1e1f22; }}
QToolBar {{ background: #26282c; border: none; spacing: 6px; padding: 4px; }}
QToolBar QToolButton {{ padding: 6px 10px; border-radius: 6px; }}
QToolBar QToolButton:hover {{ background: #34373c; }}
QToolBar QToolButton:disabled {{ color: #6b6f76; }}
QLabel#stageTitle {{ font-size: 18px; font-weight: 600; color: #ffffff; padding-bottom: 6px; }}
QListWidget {{ background: #26282c; border: none; outline: 0; padding: 6px; }}
QListWidget::item {{ padding: 10px 12px; border-radius: 6px; margin: 2px 0; }}
QListWidget::item:selected {{ background: {ACCENT}; color: #06201c; font-weight: 600; }}
QListWidget::item:disabled {{ color: #5e636b; }}
QComboBox {{ background: #2f3237; border: 1px solid #3c4046; border-radius: 6px; padding: 6px 8px; }}
QPushButton {{ background: #34373c; border: 1px solid #3c4046; border-radius: 6px; padding: 8px 14px; }}
QPushButton:hover {{ background: #3e4248; }}
QPushButton:disabled {{ color: #6b6f76; background: #2a2c30; }}
QPushButton#primary {{ background: {ACCENT}; color: #06201c; font-weight: 600; border: none; }}
QPushButton#primary:hover {{ background: #34e3cd; }}
QPushButton#primary:disabled {{ background: #2a2c30; color: #6b6f76; }}
QGraphicsView {{ background: #131417; border: 1px solid #2c2f34; }}
"""


def apply_dark_theme(app) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(_DARK_QSS)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/ui/test_theme.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/theme.py tests/ui/test_theme.py
git commit -m "feat: add dark theme stylesheet"
```

---

### Task 3: Zoomable / pannable image view

**Files:**
- Create: `seestar_processor/ui/image_view.py`
- Test: `tests/ui/test_image_view.py`

**Interfaces:**
- Produces: `ImageView(QGraphicsView)` with `set_image(qimage: QImage) -> None`, `fit() -> None`, `actual_size() -> None`. Wheel zooms to cursor; drag pans (ScrollHandDrag). Auto-fits on the first image.

- [ ] **Step 1: Write the failing test**

`tests/ui/test_image_view.py`:
```python
import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QImage  # noqa: E402
from seestar_processor.ui.image_view import ImageView  # noqa: E402


def _qimage(w=20, h=10):
    arr = (np.random.rand(h, w, 3) * 255).astype(np.uint8)
    arr = np.ascontiguousarray(arr)
    return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def test_set_image_populates_pixmap(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    assert view._item.pixmap().isNull()
    view.set_image(_qimage())
    assert not view._item.pixmap().isNull()
    assert view._item.pixmap().width() == 20


def test_fit_and_actual_size_do_not_raise(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage())
    view.fit()
    view.actual_size()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/ui/test_image_view.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/ui/image_view.py`:
```python
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView


class ImageView(QGraphicsView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = QGraphicsPixmapItem()
        self._scene.addItem(self._item)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._has_image = False

    def set_image(self, qimage) -> None:
        self._item.setPixmap(QPixmap.fromImage(qimage))
        self._scene.setSceneRect(self._item.boundingRect())
        if not self._has_image:
            self._has_image = True
            self.fit()

    def fit(self) -> None:
        if not self._item.pixmap().isNull():
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def actual_size(self) -> None:
        self.resetTransform()

    def wheelEvent(self, event) -> None:
        if self._item.pixmap().isNull():
            return
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/ui/test_image_view.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/image_view.py tests/ui/test_image_view.py
git commit -m "feat: add zoomable/pannable ImageView"
```

---

### Task 4: Stepper widget

**Files:**
- Create: `seestar_processor/ui/stepper.py`
- Test: `tests/ui/test_stepper.py`

**Interfaces:**
- Consumes: `PIPELINE` (Task 1).
- Produces: `Stepper(QListWidget)` with signal `stageSelected(int)`, methods `set_current(index: int) -> None` and `mark_done(done_ids: set[str]) -> None`. Renders all stages; disabled stages are non-selectable and labelled "… (soon)"; clicking an enabled stage emits `stageSelected` with its PIPELINE index.

- [ ] **Step 1: Write the failing test**

`tests/ui/test_stepper.py`:
```python
import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui.pipeline import PIPELINE  # noqa: E402
from seestar_processor.ui.stepper import Stepper  # noqa: E402


def _index(stage_id):
    return next(i for i, s in enumerate(PIPELINE) if s.id == stage_id)


def test_clicking_enabled_stage_emits_index(qtbot):
    step = Stepper()
    qtbot.addWidget(step)
    received = []
    step.stageSelected.connect(received.append)
    step._on_click(step.item(_index("stretch")))
    assert received == [_index("stretch")]


def test_clicking_disabled_stage_emits_nothing(qtbot):
    step = Stepper()
    qtbot.addWidget(step)
    received = []
    step.stageSelected.connect(received.append)
    step._on_click(step.item(_index("crop")))
    assert received == []


def test_disabled_items_are_not_selectable(qtbot):
    step = Stepper()
    qtbot.addWidget(step)
    from PySide6.QtCore import Qt
    item = step.item(_index("noise"))
    assert not (item.flags() & Qt.ItemFlag.ItemIsEnabled)


def test_mark_done_prefixes_check(qtbot):
    step = Stepper()
    qtbot.addWidget(step)
    step.mark_done({"background"})
    assert step.item(_index("background")).text().startswith("✓")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/ui/test_stepper.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/ui/stepper.py`:
```python
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from .pipeline import PIPELINE


class Stepper(QListWidget):
    stageSelected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        for stage in PIPELINE:
            item = QListWidgetItem(self._label(stage.id, stage.label, stage.enabled))
            if not stage.enabled:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.addItem(item)
        self.itemClicked.connect(self._on_click)

    @staticmethod
    def _label(stage_id: str, label: str, enabled: bool, done: bool = False) -> str:
        text = label if enabled else f"{label}  (soon)"
        return f"✓ {text}" if done else text

    def _on_click(self, item) -> None:
        index = self.row(item)
        if PIPELINE[index].enabled:
            self.stageSelected.emit(index)

    def set_current(self, index: int) -> None:
        self.setCurrentRow(index)

    def mark_done(self, done_ids: set) -> None:
        for i, stage in enumerate(PIPELINE):
            self.item(i).setText(
                self._label(stage.id, stage.label, stage.enabled, stage.id in done_ids)
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/ui/test_stepper.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/stepper.py tests/ui/test_stepper.py
git commit -m "feat: add Stepper widget"
```

---

### Task 5: Per-stage control panels

**Files:**
- Create: `seestar_processor/ui/step_panels.py`
- Test: `tests/ui/test_step_panels.py`

**Interfaces:**
- Consumes: `Stage` (Task 1).
- Produces: `build_panel(stage, *, on_open=None, on_apply=None, on_export=None, apply_enabled=True, option_default="Medium") -> QWidget`. The returned widget exposes (for testing) `panel_kind` (== stage.kind) and, for process/stretch stages, attributes `option_box` (QComboBox) and `apply_btn` (QPushButton). `on_apply`/`on_export` are called with the current option/format string.

- [ ] **Step 1: Write the failing test**

`tests/ui/test_step_panels.py`:
```python
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QPushButton  # noqa: E402
from seestar_processor.ui.pipeline import PIPELINE  # noqa: E402
from seestar_processor.ui.step_panels import build_panel  # noqa: E402


def _stage(stage_id):
    return next(s for s in PIPELINE if s.id == stage_id)


def test_load_panel_has_open_button(qtbot):
    clicked = []
    w = build_panel(_stage("load"), on_open=lambda: clicked.append(True))
    qtbot.addWidget(w)
    assert w.panel_kind == "load"
    btn = w.findChild(QPushButton)
    btn.click()
    assert clicked == [True]


def test_process_panel_apply_passes_option(qtbot):
    got = []
    w = build_panel(_stage("background"), on_apply=got.append, option_default="Large")
    qtbot.addWidget(w)
    assert w.panel_kind == "process"
    assert w.option_box.currentText() == "Large"
    w.apply_btn.click()
    assert got == ["Large"]


def test_apply_disabled_when_requested(qtbot):
    w = build_panel(_stage("background"), on_apply=lambda o: None, apply_enabled=False)
    qtbot.addWidget(w)
    assert w.apply_btn.isEnabled() is False


def test_placeholder_panel(qtbot):
    w = build_panel(_stage("crop"))
    qtbot.addWidget(w)
    assert w.panel_kind == "placeholder"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/ui/test_step_panels.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

`seestar_processor/ui/step_panels.py`:
```python
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QVBoxLayout, QWidget

OPTIONS = ["Small", "Medium", "Large"]


def build_panel(
    stage,
    *,
    on_open=None,
    on_apply=None,
    on_export=None,
    apply_enabled: bool = True,
    option_default: str = "Medium",
) -> QWidget:
    w = QWidget()
    w.panel_kind = stage.kind
    lay = QVBoxLayout(w)

    title = QLabel(stage.label)
    title.setObjectName("stageTitle")
    lay.addWidget(title)

    if stage.kind == "load":
        btn = QPushButton("Open FITS…")
        if on_open is not None:
            btn.clicked.connect(lambda: on_open())
        lay.addWidget(btn)
        lay.addWidget(QLabel("Open a stacked Seestar FITS to begin."))

    elif stage.kind in ("process", "stretch"):
        box = QComboBox()
        box.addItems(OPTIONS)
        box.setCurrentText(option_default)
        apply_btn = QPushButton(f"Apply {stage.label}")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(box.currentText()))
        lay.addWidget(QLabel("Strength"))
        lay.addWidget(box)
        lay.addWidget(apply_btn)
        w.option_box = box
        w.apply_btn = apply_btn

    elif stage.kind == "export":
        fmt = QComboBox()
        fmt.addItems(["TIFF (16-bit)", "JPEG"])
        btn = QPushButton("Export…")
        btn.setObjectName("primary")
        if on_export is not None:
            btn.clicked.connect(lambda: on_export(fmt.currentText()))
        lay.addWidget(QLabel("Format"))
        lay.addWidget(fmt)
        lay.addWidget(btn)
        w.format_box = fmt

    else:  # placeholder
        lay.addWidget(QLabel("Coming soon — not available in this version."))

    lay.addStretch(1)
    return w
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/ui/test_step_panels.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/step_panels.py tests/ui/test_step_panels.py
git commit -m "feat: add per-stage control panels"
```

---

### Task 6: Rewire MainWindow + theme on launch

**Files:**
- Rewrite: `seestar_processor/ui/main_window.py`
- Modify: `seestar_processor/__main__.py` (apply theme before showing window)
- Rewrite: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: everything above + `Project`, `load_fits`, `BackgroundStep`, `StretchStep`, `GraXpert`, `to_qimage`, `save_tiff`/`save_jpeg`, `Settings`/`load_settings`/`save_settings`/`graxpert_valid`, `SettingsDialog`.
- Produces: `MainWindow(settings_path)` with public methods used by tests: `open_fits(path)`, `apply_current(option)`, `go_next()`, `go_back()`, `current_stage_id() -> str`. Internal: `_stage` (PIPELINE index), `_go_to(index)`, `_refresh()`. Navigation moves across enabled stages only; applying a processing stage truncates history to that stage's prefix (`jump_back(min(PROCESSING_ORDER.index(id), len(entries)))`) then runs the step and advances.

- [ ] **Step 1: Write the failing tests**

`tests/ui/test_main_window.py` (replace entire file):
```python
import numpy as np
import pytest
from astropy.io import fits

pytest.importorskip("PySide6")
from seestar_processor.ui.main_window import MainWindow  # noqa: E402


def _make_fits(tmp_path):
    arr = (np.random.rand(3, 24, 24) * 1000).astype(np.uint16)
    p = tmp_path / "stack.fits"
    fits.PrimaryHDU(arr).writeto(str(p))
    return str(p)


def _window(qtbot, tmp_path):
    win = MainWindow(settings_path=str(tmp_path / "settings.json"))
    qtbot.addWidget(win)
    return win


def test_open_fits_loads_and_advances_to_background(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win.project is not None
    assert win.project.current().is_linear is True
    # after opening, the flow advances from Load to the first processing stage
    assert win.current_stage_id() == "background"


def test_next_skips_disabled_stages(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))           # at "background"
    win.go_next()                                  # skips color/decon/noise
    assert win.current_stage_id() == "stretch"
    win.go_next()
    assert win.current_stage_id() == "export"
    win.go_next()                                  # clamp at end
    assert win.current_stage_id() == "export"


def test_back_skips_disabled_stages(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.go_next()                                  # stretch
    win.go_back()                                  # background
    assert win.current_stage_id() == "background"
    win.go_back()                                  # load
    assert win.current_stage_id() == "load"


def test_apply_stretch_marks_nonlinear_and_advances(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.go_next()                                  # stretch stage
    win.apply_current("Medium")
    assert win.project.current().is_linear is False
    # applying advances to the next enabled stage (export)
    assert win.current_stage_id() == "export"


def test_reapply_stretch_does_not_duplicate_history(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.go_next()                                  # stretch
    win.apply_current("Small")
    win._go_to_id("stretch")                       # navigate back to stretch
    win.apply_current("Large")
    names = [n for n, _ in win.project.entries()]
    assert names.count("Stretch") == 1            # replaced, not duplicated


def test_panel_matches_current_stage(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win._panel.panel_kind == "process"     # background
    win.go_next()
    assert win._panel.panel_kind == "stretch"


def test_navigation_never_crashes_after_undo(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.apply_current("Small")                     # background -> stretch
    win.apply_current("Medium")                    # stretch -> export
    win._undo()
    # navigating to any enabled stage must not raise
    for sid in ("load", "background", "stretch", "export"):
        win._go_to_id(sid)
    assert win.project is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/ui/test_main_window.py -v`
Expected: FAIL (current MainWindow lacks `current_stage_id`/`go_next`/etc.).

- [ ] **Step 3: Write the implementation**

`seestar_processor/ui/main_window.py` (replace entire file):
```python
from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QMainWindow, QPushButton, QVBoxLayout, QWidget,
)

from ..core.export import save_jpeg, save_tiff
from ..history.project import Project
from ..settings import graxpert_valid, load_settings, save_settings
from ..steps.background import BackgroundStep
from ..steps.load import load_fits
from ..steps.stretch_step import StretchStep
from ..tools.graxpert import GraXpert
from .image_view import ImageView
from .pipeline import PIPELINE, PROCESSING_ORDER, STEP_NAME, next_enabled, prev_enabled
from .preview import to_qimage
from .settings_dialog import SettingsDialog
from .step_panels import build_panel
from .stepper import Stepper


def _stage_index(stage_id: str) -> int:
    return next(i for i, s in enumerate(PIPELINE) if s.id == stage_id)


class MainWindow(QMainWindow):
    def __init__(self, settings_path: str) -> None:
        super().__init__()
        self.setWindowTitle("Seestar Processor")
        self._settings_path = settings_path
        self.settings = load_settings(settings_path)
        self.project: Project | None = None
        self._cache_dir = os.path.join(os.path.dirname(settings_path), "cache")
        self._stage = 0
        self._before_after = False

        central = QWidget()
        root = QHBoxLayout(central)

        self.stepper = Stepper()
        self.stepper.setMaximumWidth(200)
        self.stepper.stageSelected.connect(self._go_to)
        root.addWidget(self.stepper)

        self.image_view = ImageView()
        root.addWidget(self.image_view, 1)

        right = QWidget()
        right.setMinimumWidth(240)
        self._right_layout = QVBoxLayout(right)
        self._panel = QWidget()
        self._right_layout.addWidget(self._panel)
        self._right_layout.addStretch(1)
        nav = QHBoxLayout()
        self._back_btn = QPushButton("← Back")
        self._next_btn = QPushButton("Next →")
        self._next_btn.setObjectName("primary")
        self._back_btn.clicked.connect(self.go_back)
        self._next_btn.clicked.connect(self.go_next)
        nav.addWidget(self._back_btn)
        nav.addWidget(self._next_btn)
        self._right_layout.addLayout(nav)
        root.addWidget(right)

        self.setCentralWidget(central)
        self._build_toolbar()
        self._rebuild_panel()
        self._refresh()

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Main")
        tb.addAction("Open FITS", self._choose_fits)
        tb.addAction("Settings", self._open_settings)
        self._undo_act = tb.addAction("Undo", self._undo)
        self._redo_act = tb.addAction("Redo", self._redo)
        self._ba_act = tb.addAction("Before/After", self._toggle_before_after)
        self._ba_act.setCheckable(True)
        tb.addAction("Fit", self.image_view.fit)
        tb.addAction("100%", self.image_view.actual_size)

    # --- navigation ---
    def current_stage_id(self) -> str:
        return PIPELINE[self._stage].id

    def go_next(self) -> None:
        self._go_to(next_enabled(self._stage))

    def go_back(self) -> None:
        self._go_to(prev_enabled(self._stage))

    def _go_to(self, index: int) -> None:
        if not PIPELINE[index].enabled:
            return
        self._stage = index
        self._rebuild_panel()
        self._refresh()

    def _go_to_id(self, stage_id: str) -> None:
        self._go_to(_stage_index(stage_id))

    # --- file / project ---
    def _choose_fits(self) -> None:
        path = QFileDialog.getOpenFileName(self, "Open FITS", "", "FITS (*.fit *.fits)")[0]
        if path:
            self.open_fits(path)

    def open_fits(self, path: str) -> None:
        base = load_fits(path)
        os.makedirs(self._cache_dir, exist_ok=True)
        self.project = Project(base, self._cache_dir)
        self._go_to(next_enabled(_stage_index("load")))  # advance Load -> Background

    # --- apply a processing stage ---
    def _step_for(self, stage_id: str):
        if stage_id == "background":
            step = BackgroundStep(GraXpert(self.settings.graxpert_path))
            return step
        if stage_id == "stretch":
            return StretchStep()
        raise ValueError(stage_id)

    def apply_current(self, option: str) -> None:
        if self.project is None:
            return
        stage_id = PIPELINE[self._stage].id
        if stage_id not in PROCESSING_ORDER:
            return
        # Truncate history to the prefix that should precede this stage, so a
        # re-apply replaces (not duplicates) this stage and anything after it.
        target = min(PROCESSING_ORDER.index(stage_id), len(self.project.entries()))
        self.project.jump_back(target)
        self.project.run_step(self._step_for(stage_id), option)
        self._go_to(next_enabled(self._stage))

    # --- history ---
    def _undo(self) -> None:
        if self.project:
            self.project.undo()
            self._refresh()

    def _redo(self) -> None:
        if self.project:
            self.project.redo()
            self._refresh()

    def _toggle_before_after(self) -> None:
        self._before_after = self._ba_act.isChecked()
        self._refresh()

    # --- export ---
    def _export_current(self, fmt: str) -> None:
        if not self.project:
            return
        path, selected = QFileDialog.getSaveFileName(
            self, "Export", "", "TIFF (*.tiff);;JPEG (*.jpg)"
        )
        if not path:
            return
        img = self.project.current()
        wants_jpeg = "JPEG" in fmt or path.lower().endswith((".jpg", ".jpeg"))
        if wants_jpeg:
            if not path.lower().endswith((".jpg", ".jpeg")):
                path += ".jpg"
            save_jpeg(img, path)
        else:
            if not path.lower().endswith((".tiff", ".tif")):
                path += ".tiff"
            save_tiff(img, path)

    # --- settings ---
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.result_settings()
            save_settings(self.settings, self._settings_path)
            self._rebuild_panel()
            self._refresh()

    # --- rendering ---
    def _rebuild_panel(self) -> None:
        stage = PIPELINE[self._stage]
        apply_enabled = self.project is not None
        if stage.id == "background":
            apply_enabled = apply_enabled and graxpert_valid(self.settings)
        new_panel = build_panel(
            stage,
            on_open=self._choose_fits,
            on_apply=self.apply_current,
            on_export=self._export_current,
            apply_enabled=apply_enabled,
        )
        self._right_layout.replaceWidget(self._panel, new_panel)
        self._panel.deleteLater()
        self._panel = new_panel

    def _refresh(self) -> None:
        self.stepper.set_current(self._stage)
        self.stepper.mark_done(self._done_ids())
        if self.project is not None:
            img = self.project.current()
            if self._before_after:
                before, _ = self.project.before_after()
                img = before
            self.image_view.set_image(to_qimage(img))
        self._back_btn.setEnabled(prev_enabled(self._stage) != self._stage)
        self._next_btn.setEnabled(next_enabled(self._stage) != self._stage)
        self._undo_act.setEnabled(bool(self.project and self.project.can_undo()))
        self._redo_act.setEnabled(bool(self.project and self.project.can_redo()))

    def _done_ids(self) -> set:
        done = set()
        if self.project is None:
            return done
        done.add("load")
        applied = {n for n, _ in self.project.entries()}
        for sid, name in STEP_NAME.items():
            if name in applied:
                done.add(sid)
        return done
```

`seestar_processor/__main__.py` (replace entire file):
```python
import os
import sys

from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow
from .ui.theme import apply_dark_theme


def main() -> None:
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    settings_path = os.path.join(
        os.path.expanduser("~"), ".seestar_processor", "settings.json"
    )
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    win = MainWindow(settings_path=settings_path)
    win.resize(1280, 760)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/ui/test_main_window.py -v`
Expected: PASS (all 7).

- [ ] **Step 5: Full suite + manual check**

Run: `.venv/bin/pytest -q`
Expected: all PASS, pristine.

Manual: `.venv/bin/python -m seestar_processor` → dark window; left stepper with disabled stages greyed; Open a FITS → advances to Background; wheel-zoom and drag-pan the image; Back/Next move between enabled stages; Apply Stretch updates the preview and advances; Export from the Export stage.

- [ ] **Step 6: Commit**

```bash
git add seestar_processor/ui/main_window.py seestar_processor/__main__.py tests/ui/test_main_window.py
git commit -m "feat: stepper-based guided UI with zoom/pan and dark theme"
```

---

## Self-Review notes

- **Spec coverage:** left stepper (T4), zoom/pan preview (T3), Back/Next + guided one-stage-at-a-time (T6), dark theme (T2), full pipeline with disabled stages (T1+T4), per-stage controls (T5), engine reuse (T6 imports only). Re-apply-without-duplication handled by the `jump_back(min(...))` rule (T6) and tested.
- **Crash regression:** the v1 stale-step-list crash can't recur — navigation only ever targets valid enabled PIPELINE indices via `next_enabled`/`prev_enabled`/`_go_to`, and `apply_current` caps `jump_back` at `len(entries)`. Covered by `test_navigation_never_crashes_after_undo`.
- **Type consistency:** `current_stage_id`, `go_next`, `go_back`, `_go_to`, `_go_to_id`, `apply_current`, `_panel.panel_kind`, `option_box`, `apply_btn` are used identically in tests and implementation.
- **Out of scope:** disabled stages remain placeholders (no processing logic added).
```
