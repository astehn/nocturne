# Visual Polish (Tier 2 — Canvas & Panels) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Nocturne's canvas and panels screenshot-worthy — gradient canvas backdrop, image drop shadow, floating zoom pill, empty-state welcome screen, styled histogram, and card-style step panels.

**Architecture:** Add paint/backdrop to `ImageView` (drawBackground gradient + drop shadow), a `ZoomPill` child widget, a `WelcomeScreen` shown via a `QStackedWidget` in the centre, a rewritten filled histogram, and a card wrapper for step panels — all driven by Tier 1 theme tokens. Purely visual.

**Tech Stack:** PySide6 (QGraphicsView, QGraphicsDropShadowEffect, QStackedWidget, QPainter), Python 3.11+.

## Global Constraints

- Package `seestar_processor` (no rename). Venv `.venv`; UI tests headless (`QT_QPA_PLATFORM=offscreen`).
- **Visual only** — no processing/navigation/crop/before-after behaviour changes; existing tests stay green.
- Reuse Tier 1 theme tokens from `ui/theme.py` (`BG_0`, `BG_1`, `BG_2`, `BG_3`, `BORDER`, `ACCENT`, `TEXT`, `TEXT_DIM`, `TEXT_FAINT`).
- Empty-state uses a **text** wordmark ("Nocturne"), not a logo asset (that's Tier 3).
- Keep the pure/paint split: logic in small tested helpers; paint code gets smoke tests (renders without error).
- Commit after each task. Create the `visual-polish-t2` branch first (do not start on `main`).

---

## File Structure

- `seestar_processor/ui/image_view.py` — `drawBackground` gradient, image drop shadow, `zoom_in`/`zoom_out`, host the zoom pill.
- `seestar_processor/ui/zoom_pill.py` — NEW: floating `– / fit / +` control.
- `seestar_processor/ui/welcome.py` — NEW: empty-state welcome widget.
- `seestar_processor/ui/histogram_view.py` — filled translucent RGB curves + faint grid; `_polygon_points` helper.
- `seestar_processor/ui/step_panels.py` — `stepCard` objectName + `stepDesc` strip.
- `seestar_processor/ui/theme.py` — QSS for `#stepCard`, `#stepDesc`, `#welcomeTitle`, `#zoomPill`.
- `seestar_processor/ui/main_window.py` — `QStackedWidget` [welcome, image_view]; switch on open.
- Tests: `tests/ui/test_zoom_pill.py`, `tests/ui/test_welcome.py`, `tests/ui/test_histogram_view.py`, `tests/ui/test_image_view.py` (add), `tests/ui/test_main_window.py` (add), `tests/ui/test_step_panels.py` (add or extend).

---

## Task 0: Branch setup

- [ ] **Step 1: Create the feature branch**

```bash
cd /Volumes/Work/Code/Editor
git checkout -b visual-polish-t2
git status   # expect: On branch visual-polish-t2, clean
```

---

## Task 1: Histogram — filled RGB curves + grid

**Files:**
- Modify: `seestar_processor/ui/histogram_view.py`
- Test: `tests/ui/test_histogram_view.py`

**Interfaces:**
- Produces: `_polygon_points(counts, w, h, peak) -> list[tuple[float, float]]` (a closed area polygon spanning the width); `HistogramView.set_image`/`_hist`/`_COLORS` unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_histogram_view.py`:

```python
import numpy as np
import pytest

pytest.importorskip("PySide6")
from seestar_processor.core.image import AstroImage  # noqa: E402
from seestar_processor.ui.histogram_view import HistogramView, _polygon_points  # noqa: E402


def test_polygon_points_span_and_bounds():
    pts = _polygon_points([0, 5, 10, 5, 0], w=100, h=50, peak=10)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    assert min(xs) >= 0 and max(xs) <= 100
    assert min(ys) >= 0 and max(ys) <= 50
    # closes along the baseline (first and last points sit on the bottom edge)
    assert pts[0][1] == 50 and pts[-1][1] == 50


def test_set_image_populates_and_paints(qtbot):
    view = HistogramView()
    qtbot.addWidget(view)
    view.resize(200, 120)
    img = AstroImage((np.random.rand(20, 20, 3)).astype(np.float32), is_linear=False)
    view.set_image(img)
    assert view._hist is not None
    from PySide6.QtGui import QPixmap
    view.render(QPixmap(view.size()))   # paintEvent runs without error
```

- [ ] **Step 2: Run it, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_histogram_view.py -q`
Expected: FAIL (`_polygon_points` not defined).

- [ ] **Step 3: Implement**

Replace the entire contents of `seestar_processor/ui/histogram_view.py` with:

```python
from __future__ import annotations

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core.histogram import histogram
from .theme import BG_0, BORDER

_COLORS = {"r": "#ff5555", "g": "#55ff55", "b": "#5599ff", "l": "#cccccc"}


def _polygon_points(counts, w: int, h: int, peak: int):
    """Closed area-polygon points for a channel: a filled curve from the
    baseline up to each bin height and back, spanning the full width."""
    n = len(counts)
    if n == 0 or peak <= 0:
        return [(0.0, float(h)), (float(w), float(h))]
    pts = [(0.0, float(h))]
    for x in range(n):
        bx = x / (n - 1) * w if n > 1 else 0.0
        by = h - (counts[x] / peak) * (h - 2)
        pts.append((bx, by))
    pts.append((float(w), float(h)))
    return pts


class HistogramView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._hist = None

    def set_image(self, img) -> None:
        self._hist = histogram(img, bins=256)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(BG_0))
        w, h = self.width(), self.height()
        # faint horizontal grid
        grid = QColor(BORDER)
        grid.setAlpha(90)
        p.setPen(QPen(grid, 1))
        for i in range(1, 4):
            y = int(h * i / 4)
            p.drawLine(0, y, w, y)
        if not self._hist:
            return
        peak = max(int(c.max()) for c in self._hist.values()) or 1
        for key, counts in self._hist.items():
            col = QColor(_COLORS[key])
            fill = QColor(col)
            fill.setAlpha(70)
            poly = QPolygonF([QPointF(x, y) for x, y in
                              _polygon_points(counts, w, h, peak)])
            p.setPen(QPen(col, 1))
            p.setBrush(fill)
            p.drawPolygon(poly)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_histogram_view.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/histogram_view.py tests/ui/test_histogram_view.py
git commit -m "feat: filled translucent RGB histogram with grid"
```

---

## Task 2: ImageView — gradient backdrop, drop shadow, zoom methods

**Files:**
- Modify: `seestar_processor/ui/image_view.py`
- Test: `tests/ui/test_image_view.py`

**Interfaces:**
- Consumes: theme `BG_0`, `BG_1`.
- Produces: `ImageView.zoom_in()` (scale 1.25), `ImageView.zoom_out()` (scale 0.8); `drawBackground` paints a radial gradient; the image item has a drop shadow. `wheelEvent` refactored to call `zoom_in`/`zoom_out`.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_image_view.py`:

```python
import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QImage  # noqa: E402
from seestar_processor.ui.image_view import ImageView  # noqa: E402


def _qimage(w=40, h=30):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(0x202020)
    return img


def test_zoom_in_out_change_scale(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.resize(300, 200)
    view.set_image(_qimage())
    before = view.transform().m11()
    view.zoom_in()
    assert view.transform().m11() > before
    mid = view.transform().m11()
    view.zoom_out()
    assert view.transform().m11() < mid


def test_zoom_noop_without_image(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    # no image -> zoom does nothing, no crash
    view.zoom_in()
    view.zoom_out()
```

- [ ] **Step 2: Run it, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_image_view.py -q`
Expected: FAIL (`zoom_in` not defined).

- [ ] **Step 3: Implement**

In `seestar_processor/ui/image_view.py`:

(a) Extend the imports:

```python
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsScene, QGraphicsView,
)

from .theme import BG_0, BG_1
```

(b) In `ImageView.__init__`, after `self._scene.addItem(self._item)`, add a drop shadow on the image item:

```python
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 0)
        shadow.setColor(QColor(0, 0, 0, 130))
        self._item.setGraphicsEffect(shadow)
```

(c) Add `drawBackground` and the zoom methods to the class, and refactor `wheelEvent`:

```python
    def drawBackground(self, painter, rect) -> None:
        vp = self.viewport().rect()
        grad = QRadialGradient(vp.center(), max(vp.width(), vp.height()) * 0.7)
        grad.setColorAt(0.0, QColor(BG_1))
        grad.setColorAt(1.0, QColor(BG_0))
        painter.save()
        painter.resetTransform()
        painter.fillRect(vp, QBrush(grad))
        painter.restore()

    def zoom_in(self) -> None:
        if not self._item.pixmap().isNull():
            self.scale(1.25, 1.25)

    def zoom_out(self) -> None:
        if not self._item.pixmap().isNull():
            self.scale(0.8, 0.8)

    def wheelEvent(self, event) -> None:
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()
```

(Delete the old `wheelEvent` body that used `factor`. `QLinearGradient` is imported for
possible future use but the radial one is used here — if a linter flags it as unused, drop
`QLinearGradient` from the import.)

- [ ] **Step 4: Run tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_image_view.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/image_view.py tests/ui/test_image_view.py
git commit -m "feat: gradient canvas backdrop, image drop shadow, zoom methods"
```

---

## Task 3: Zoom pill (floating control)

**Files:**
- Create: `seestar_processor/ui/zoom_pill.py`
- Modify: `seestar_processor/ui/image_view.py` (host the pill, position on resize)
- Test: `tests/ui/test_zoom_pill.py`

**Interfaces:**
- Consumes: `ImageView.zoom_in`/`zoom_out`/`fit`.
- Produces: `ZoomPill(on_out, on_fit, on_in, parent=None)` with buttons `out_btn`, `fit_btn`, `in_btn`.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_zoom_pill.py`:

```python
import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui.zoom_pill import ZoomPill  # noqa: E402


def test_buttons_invoke_callbacks(qtbot):
    calls = []
    pill = ZoomPill(lambda: calls.append("out"),
                    lambda: calls.append("fit"),
                    lambda: calls.append("in"))
    qtbot.addWidget(pill)
    pill.out_btn.click()
    pill.fit_btn.click()
    pill.in_btn.click()
    assert calls == ["out", "fit", "in"]
```

- [ ] **Step 2: Run it, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_zoom_pill.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the pill**

Create `seestar_processor/ui/zoom_pill.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget


class ZoomPill(QWidget):
    """Floating zoom control: – / fit / + ."""

    def __init__(self, on_out, on_fit, on_in, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("zoomPill")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(2)
        self.out_btn = QPushButton("−")   # minus
        self.fit_btn = QPushButton("⤢")   # fit / expand glyph
        self.in_btn = QPushButton("+")
        for b, cb in ((self.out_btn, on_out), (self.fit_btn, on_fit),
                      (self.in_btn, on_in)):
            b.setFixedSize(28, 24)
            b.setFlat(True)
            b.clicked.connect(cb)
            lay.addWidget(b)
```

- [ ] **Step 4: Host the pill in ImageView**

In `seestar_processor/ui/image_view.py`, add the import at the top:

```python
from .zoom_pill import ZoomPill
```

In `ImageView.__init__` (at the end), create the pill:

```python
        self._zoom_pill = ZoomPill(self.zoom_out, self.fit, self.zoom_in, self)
        self._zoom_pill.raise_()
        self._position_zoom_pill()
```

Add these two methods:

```python
    def _position_zoom_pill(self) -> None:
        pill = self._zoom_pill
        pill.adjustSize()
        m = 12
        pill.move(self.width() - pill.width() - m, self.height() - pill.height() - m)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_zoom_pill()
```

- [ ] **Step 5: Run tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_zoom_pill.py tests/ui/test_image_view.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add seestar_processor/ui/zoom_pill.py seestar_processor/ui/image_view.py tests/ui/test_zoom_pill.py
git commit -m "feat: floating zoom pill on the image canvas"
```

---

## Task 4: Welcome screen + centre QStackedWidget

**Files:**
- Create: `seestar_processor/ui/welcome.py`
- Modify: `seestar_processor/ui/main_window.py` (wrap centre in a stack; switch on open)
- Test: `tests/ui/test_welcome.py`, `tests/ui/test_main_window.py` (add)

**Interfaces:**
- Consumes: `seestar_processor.APP_TAGLINE`; `ImageView`.
- Produces: `WelcomeScreen(on_open, on_stack, parent=None)` with `open_btn`, `stack_btn`; `MainWindow._center_stack` (QStackedWidget), page 0 = welcome, page 1 = image_view.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_welcome.py`:

```python
import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui.welcome import WelcomeScreen  # noqa: E402


def test_welcome_buttons_invoke_callbacks(qtbot):
    calls = []
    w = WelcomeScreen(lambda: calls.append("open"), lambda: calls.append("stack"))
    qtbot.addWidget(w)
    w.open_btn.click()
    w.stack_btn.click()
    assert calls == ["open", "stack"]
```

And add to `tests/ui/test_main_window.py`:

```python
def test_center_stack_switches_on_open(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    # welcome page shown before any image is loaded
    assert win._center_stack.currentIndex() == 0
    win.open_fits(_make_fits(tmp_path))
    # image page shown after loading
    assert win._center_stack.currentIndex() == 1
    assert win._center_stack.currentWidget() is win.image_view
```

- [ ] **Step 2: Run it, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_welcome.py "tests/ui/test_main_window.py::test_center_stack_switches_on_open" -q`
Expected: FAIL (module not found / `_center_stack` missing).

- [ ] **Step 3: Implement the welcome screen**

Create `seestar_processor/ui/welcome.py`:

```python
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .. import APP_NAME, APP_TAGLINE


class WelcomeScreen(QWidget):
    def __init__(self, on_open, on_stack, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("welcome")
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel(APP_NAME)
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline = QLabel(APP_TAGLINE)
        tagline.setObjectName("welcomeTag")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("Open a file or Stack a folder to begin")
        hint.setObjectName("welcomeHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.open_btn = QPushButton("Open FITS")
        self.open_btn.clicked.connect(lambda: on_open())
        self.stack_btn = QPushButton("Stack…")
        self.stack_btn.setObjectName("primary")
        self.stack_btn.clicked.connect(lambda: on_stack())
        buttons = QHBoxLayout()
        buttons.setAlignment(Qt.AlignmentFlag.AlignCenter)
        buttons.addWidget(self.open_btn)
        buttons.addWidget(self.stack_btn)

        root.addWidget(title)
        root.addWidget(tagline)
        root.addSpacing(8)
        root.addWidget(hint)
        root.addSpacing(20)
        root.addLayout(buttons)
```

- [ ] **Step 4: Wire the stack into MainWindow**

In `seestar_processor/ui/main_window.py`:

(a) Add imports near the other `.ui` imports:

```python
from PySide6.QtWidgets import QStackedWidget
from .welcome import WelcomeScreen
```

(If `QStackedWidget` is imported from a grouped `PySide6.QtWidgets` import already, add it to
that group instead of a new line.)

(b) Replace these two lines in the centre layout:

```python
        self.image_view = ImageView()
        root.addWidget(self.image_view, 1)
```

with:

```python
        self.image_view = ImageView()
        self._center_stack = QStackedWidget()
        self._welcome = WelcomeScreen(self._choose_fits, self._open_stack)
        self._center_stack.addWidget(self._welcome)   # page 0
        self._center_stack.addWidget(self.image_view)  # page 1
        root.addWidget(self._center_stack, 1)
```

(c) In `open_image`, after `self.project = Project(base, self._cache_dir)`, switch to the
image page:

```python
        self._center_stack.setCurrentWidget(self.image_view)
```

- [ ] **Step 5: Run tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_welcome.py tests/ui/test_main_window.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add seestar_processor/ui/welcome.py seestar_processor/ui/main_window.py tests/ui/test_welcome.py tests/ui/test_main_window.py
git commit -m "feat: empty-state welcome screen via centre QStackedWidget"
```

---

## Task 5: Card-style step panels + consolidated QSS + full suite

**Files:**
- Modify: `seestar_processor/ui/step_panels.py`
- Modify: `seestar_processor/ui/theme.py`
- Modify: `TODO.md`
- Test: `tests/ui/test_step_panels.py`

**Interfaces:**
- Consumes: theme tokens.
- Produces: built panel widget `objectName() == "stepCard"`; a `stepDesc`-named description label under the title.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_step_panels.py` (or add if it exists):

```python
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QLabel  # noqa: E402
from seestar_processor.ui.pipeline import path_stages  # noqa: E402
from seestar_processor.ui.step_panels import build_panel  # noqa: E402


def test_panel_is_a_card(qtbot):
    stage = next(s for s in path_stages("in_app") if s.id == "stretch")
    panel = build_panel(stage)
    qtbot.addWidget(panel)
    assert panel.objectName() == "stepCard"


def test_panel_has_description_strip(qtbot):
    stage = next(s for s in path_stages("in_app") if s.id == "stretch")
    panel = build_panel(stage)
    qtbot.addWidget(panel)
    descs = [c for c in panel.findChildren(QLabel) if c.objectName() == "stepDesc"]
    assert descs, "panel has a stepDesc label"
```

- [ ] **Step 2: Run it, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_step_panels.py -q`
Expected: FAIL (objectName not set / no stepDesc).

- [ ] **Step 3: Implement**

There is already a `_DESCRIPTIONS` dict (used by the `process` branch) and most branches
already add a `_desc_label`. Do NOT add a second dict or a duplicate description. Make exactly
these three edits in `seestar_processor/ui/step_panels.py`:

(a) In `_desc_label`, set the object name so every existing description strip becomes
styleable and test-visible. Replace the function body:

```python
def _desc_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("stepDesc")
    label.setWordWrap(True)
    return label
```

(b) Mark the panel widget as a card. Change the line `w = QWidget()` (right after the
`build_panel` signature) to also set the object name:

```python
    w = QWidget()
    w.setObjectName("stepCard")
```

(c) Three branches — `stretch`, `levels`, `saturation` — currently have no description strip.
Add one `_desc_label(...)` as the FIRST statement inside each of those three `elif` branches.

For `stretch` (`elif stage.kind == "stretch":`), the first statement becomes:
```python
        lay.addWidget(_desc_label("Brighten the faint detail so the target appears."))
        slider = QSlider(Qt.Orientation.Horizontal)
```

For `levels` (`elif stage.kind == "levels":`):
```python
        lay.addWidget(_desc_label("Fine-tune black point, midtones, and white point."))
        black = QSlider(Qt.Orientation.Horizontal)
```

For `saturation` (`elif stage.kind == "saturation":`):
```python
        lay.addWidget(_desc_label("Boost colour intensity."))
        slider = QSlider(Qt.Orientation.Horizontal)
```

(Leave every other branch untouched — they already have a `_desc_label`, which now carries the
`stepDesc` object name from edit (a).)

- [ ] **Step 4: Add the QSS (theme.py)**

In `seestar_processor/ui/theme.py`, inside the `build_stylesheet()` returned string, append
these rules before the closing `"""` (they use the existing token names):

```css
QWidget#stepCard {{ background: {BG_2}; border-radius: 10px; }}
QLabel#stepDesc {{ color: {TEXT_DIM}; font-size: 12px; padding-bottom: 6px; }}
QWidget#welcome {{ background: transparent; }}
QLabel#welcomeTitle {{ font-size: 40px; font-weight: 700; color: #ffffff; }}
QLabel#welcomeTag {{ font-size: 15px; color: {TEXT_DIM}; }}
QLabel#welcomeHint {{ font-size: 13px; color: {TEXT_FAINT}; }}
QWidget#zoomPill {{ background: {BG_2}; border: 1px solid {BORDER}; border-radius: 14px; }}
QWidget#zoomPill QPushButton {{ background: transparent; border: none; color: {TEXT};
    font-size: 15px; padding: 0; }}
QWidget#zoomPill QPushButton:hover {{ color: {ACCENT}; }}
```

- [ ] **Step 5: Run tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_step_panels.py -q`
Expected: PASS.

- [ ] **Step 6: Full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass. If `test_sharpen_changes_image_and_keeps_shape` fails, it's the known pre-existing flake — rerun it alone to confirm.

- [ ] **Step 7: Mark Tier 2 done in the backlog**

In `TODO.md`, change the Tier 2 line under "Visual polish — later tiers" from `- [ ] **Tier 2 …`
to `- [x] **Tier 2 …` and append: `Shipped: gradient canvas, image shadow, zoom pill, welcome
screen, filled histogram, card panels.`

- [ ] **Step 8: Commit**

```bash
git add seestar_processor/ui/step_panels.py seestar_processor/ui/theme.py tests/ui/test_step_panels.py TODO.md
git commit -m "feat: card-style step panels + welcome/zoom/histogram QSS; mark Tier 2 done"
```

---

## Definition of Done

- All tasks committed on `visual-polish-t2`; full suite green.
- Launching the app shows the welcome screen; loading an image reveals it on a gradient
  backdrop with a soft shadow, a floating zoom pill, a filled RGB histogram, and card-style
  step panels.
- No behavioural change; existing tests stay green (only additive UI tests + the panel/histogram
  changes).
- After merge: take fresh screenshots (welcome + a loaded nebula) for the testers/README.
- Finish with **superpowers:finishing-a-development-branch**.
```
