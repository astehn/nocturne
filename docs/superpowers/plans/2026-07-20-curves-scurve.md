# Curves / S-Curve Tone Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an interactive Curves step — a draggable monotone-cubic tone curve on luminance with a histogram backdrop, a background-aware "Add contrast" preset, and live preview.

**Architecture:** A pure-numpy core (`nocturne/core/curves.py`: `build_lut`, `apply_curve`, `gentle_s_points`) drives a custom `CurveEditor(QWidget)` (draggable interior points, pinned corners, histogram backdrop). A `curves` pipeline stage after Levels wraps `apply_curve` via the generic commit path; the panel embeds the editor with Reset/Add-contrast presets; main_window wires debounced live preview + histogram like the other tail steps.

**Tech Stack:** Python, NumPy, PySide6, pytest. No new third-party dependency (monotone-cubic interpolation implemented in numpy).

## Global Constraints

- No new third-party dependency. Monotone-cubic (Fritsch–Carlson) interpolation is implemented in numpy — do NOT add scipy.
- `apply_curve(img, points)` operates on luminance only; hue preserved by `out = RGB * (new_L / max(L, 1e-6))`; identity points `[(0,0),(1,1)]` are an exact no-op.
- Curve control points are `list[tuple[float, float]]` in `[0,1]`, sorted by x, with endpoints pinned at the corners `(0.0, 0.0)` and `(1.0, 1.0)` (not movable, not removable). Interior points keep a minimum x-gap of `0.02`.
- LUT is 1024 entries over `[0,1]`, monotonic non-decreasing.
- Preserve `is_linear` and `metadata`; output clipped to `[0,1]`, dtype `float32`. Greyscale (2-D) takes the single-channel path.
- Stage id `curves`, display name `"Curves"`, panel `kind == "curves"`, placed AFTER `levels` and BEFORE `saturation` in every ordering (pipeline `_IN_APP_TAIL`, `STEP_NAME`, `PROCESSING_ORDER`, `POST_STRETCH_IDS`).
- Recipe option is a list of `[x, y]` pairs (its own serialize/deserialize branch).
- Follow existing patterns: step wrapper mirrors `steps/levels.py`; panel/preview wiring mirrors the Levels / Recover Core live-preview pattern; the editor's paint idiom mirrors `nocturne/ui/histogram_view.py`.

---

### Task 1: Core curve engine (`core/curves.py`)

**Files:**
- Create: `nocturne/core/curves.py`
- Test: `tests/core/test_curves.py`

**Interfaces:**
- Consumes: `nocturne.core.image.AstroImage`.
- Produces:
  - `build_lut(points: list[tuple[float, float]], n: int = 1024) -> np.ndarray` — monotone-cubic LUT over `[0,1]`, float32, clipped to `[0,1]`.
  - `apply_curve(img: AstroImage, points: list[tuple[float, float]]) -> AstroImage`.
  - `gentle_s_points(data: np.ndarray) -> list[tuple[float, float]]` — background-aware "Add contrast" points.

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_curves.py`:

```python
import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.curves import build_lut, apply_curve, gentle_s_points

IDENTITY = [(0.0, 0.0), (1.0, 1.0)]


def test_identity_lut_is_ramp():
    lut = build_lut(IDENTITY, n=1024)
    assert lut.shape == (1024,)
    assert np.allclose(lut, np.linspace(0.0, 1.0, 1024), atol=1e-4)


def test_lut_is_monotonic_for_reasonable_points():
    lut = build_lut([(0.0, 0.0), (0.3, 0.15), (0.6, 0.8), (1.0, 1.0)])
    assert np.all(np.diff(lut) >= -1e-6)          # never decreases
    assert lut.min() >= 0.0 and lut.max() <= 1.0


def test_apply_identity_is_noop():
    rng = np.random.default_rng(0)
    img = AstroImage(rng.random((32, 32, 3)).astype(np.float32), is_linear=False)
    out = apply_curve(img, IDENTITY).data
    assert np.allclose(out, img.data, atol=1e-4)


def test_lifted_midtone_raises_mids_keeps_endpoints():
    # a flat mid-grey field lifts; pure black / pure white pixels stay put
    data = np.full((16, 16, 3), 0.5, np.float32)
    data[0, 0] = 0.0
    data[0, 1] = 1.0
    out = apply_curve(AstroImage(data), [(0.0, 0.0), (0.5, 0.68), (1.0, 1.0)]).data
    assert out[8, 8].mean() > 0.6            # midtone lifted
    assert np.allclose(out[0, 0], 0.0, atol=1e-4)   # black endpoint pinned
    assert np.allclose(out[0, 1], 1.0, atol=1e-4)   # white endpoint pinned


def test_output_range_and_dtype():
    rng = np.random.default_rng(1)
    img = AstroImage(rng.random((24, 24, 3)).astype(np.float32))
    out = apply_curve(img, [(0.0, 0.0), (0.4, 0.1), (0.7, 0.9), (1.0, 1.0)])
    assert out.data.dtype == np.float32
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0


def test_preserves_is_linear_and_metadata():
    img = AstroImage(np.full((8, 8, 3), 0.5, np.float32),
                     is_linear=False, metadata={"k": 1})
    out = apply_curve(img, [(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)])
    assert out.is_linear is False and out.metadata == {"k": 1}


def test_greyscale_path():
    data = np.linspace(0, 1, 64, dtype=np.float32).reshape(8, 8)
    out = apply_curve(AstroImage(data), [(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)])
    assert out.data.ndim == 2
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0


def _bg_image():
    # 80% background at 0.15, rest brighter -> 10th percentile ~ 0.15
    lum = np.full((100, 100), 0.15, np.float32)
    lum[:, 80:] = 0.6
    return np.repeat(lum[:, :, None], 3, axis=2)


def test_gentle_s_points_shape_and_pin():
    pts = gentle_s_points(_bg_image())
    xs = [p[0] for p in pts]
    assert pts[0] == (0.0, 0.0) and pts[-1] == (1.0, 1.0)   # corners present
    assert xs == sorted(xs) and len(set(xs)) == len(xs)     # strictly increasing x
    assert all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in pts)
    # background (~0.15) is pinned: the curve does not lift it
    lut = build_lut(pts)
    bg_out = lut[int(0.15 * (len(lut) - 1))]
    assert abs(bg_out - 0.15) < 0.03


def test_gentle_s_adds_midtone_contrast():
    lut = build_lut(gentle_s_points(_bg_image()))
    lo, hi = lut[int(0.45 * 1023)], lut[int(0.75 * 1023)]
    slope = (hi - lo) / (0.75 - 0.45)
    assert slope > 1.0        # steeper than linear through the midtones
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/core/test_curves.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nocturne.core.curves'`.

- [ ] **Step 3: Write the implementation**

Create `nocturne/core/curves.py`:

```python
from __future__ import annotations

import numpy as np

from .image import AstroImage

_MIN_GAP = 0.02


def _pchip_tangents(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Fritsch–Carlson monotone tangents for cubic Hermite interpolation."""
    n = len(xs)
    h = np.diff(xs)
    delta = np.diff(ys) / h
    m = np.zeros(n)
    for i in range(1, n - 1):
        if delta[i - 1] * delta[i] <= 0:
            m[i] = 0.0
        else:
            w1 = 2 * h[i] + h[i - 1]
            w2 = h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / delta[i - 1] + w2 / delta[i])
    m[0] = delta[0]
    m[-1] = delta[-1]
    return m


def build_lut(points: list[tuple[float, float]], n: int = 1024) -> np.ndarray:
    """A 1-D lookup table over [0,1] from control points, using monotone-cubic
    (Fritsch–Carlson) interpolation so the curve never overshoots or inverts."""
    pts = sorted((float(x), float(y)) for x, y in points)
    xs = np.array([p[0] for p in pts], dtype=np.float64)
    ys = np.array([p[1] for p in pts], dtype=np.float64)
    grid = np.linspace(0.0, 1.0, n)
    if len(xs) < 2:
        return np.clip(np.full(n, ys[0] if len(ys) else 0.0), 0, 1).astype(np.float32)
    m = _pchip_tangents(xs, ys)
    h = np.diff(xs)
    out = np.empty(n)
    seg = np.clip(np.searchsorted(xs, grid) - 1, 0, len(xs) - 2)
    for s in range(len(xs) - 1):
        mask = seg == s
        if not np.any(mask):
            continue
        t = (grid[mask] - xs[s]) / h[s]
        t2, t3 = t * t, t * t * t
        h00 = 2 * t3 - 3 * t2 + 1
        h10 = t3 - 2 * t2 + t
        h01 = -2 * t3 + 3 * t2
        h11 = t3 - t2
        out[mask] = (h00 * ys[s] + h10 * h[s] * m[s]
                     + h01 * ys[s + 1] + h11 * h[s] * m[s + 1])
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def apply_curve(img: AstroImage, points: list[tuple[float, float]]) -> AstroImage:
    """Apply a tone curve (from control `points`) to luminance, preserving hue by
    rescaling RGB with the luminance ratio. Identity points are a no-op."""
    data = np.clip(img.data, 0.0, 1.0).astype(np.float32)
    lut = build_lut(points)
    mono = data.ndim == 2
    lum = data if mono else data.mean(axis=2)
    idx = lum * (len(lut) - 1)
    lo = np.clip(np.floor(idx).astype(np.int64), 0, len(lut) - 2)
    frac = (idx - lo).astype(np.float32)
    new_lum = lut[lo] * (1.0 - frac) + lut[lo + 1] * frac
    if mono:
        out = new_lum
    else:
        ratio = new_lum / np.maximum(lum, 1e-6)
        out = data * ratio[..., None]
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def gentle_s_points(data: np.ndarray) -> list[tuple[float, float]]:
    """Background-aware 'Add contrast' preset: pin an anchor at the sky level,
    then dip a lower-mid point and lift an upper-mid point for a gentle S that
    raises midtone contrast without lifting the sky."""
    lum = data.mean(axis=2) if data.ndim == 3 else data
    bg = float(np.clip(np.percentile(lum, 10.0), 0.0, 0.5))
    span = 1.0 - bg
    lo_x = bg + span * 0.35
    hi_x = bg + span * 0.75
    d = span * 0.06
    raw = [(0.0, 0.0), (bg, bg),
           (lo_x, lo_x - d), (hi_x, hi_x + d), (1.0, 1.0)]
    # sort, clamp, drop interior points too close together (keeps strictly-increasing x)
    interior = sorted((float(np.clip(x, 0, 1)), float(np.clip(y, 0, 1)))
                      for x, y in raw if 0.0 < x < 1.0)
    out = [(0.0, 0.0)]
    for x, y in interior:
        if x - out[-1][0] >= _MIN_GAP:
            out.append((x, y))
    if len(out) > 1 and (1.0 - out[-1][0]) < _MIN_GAP:
        out.pop()
    out.append((1.0, 1.0))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/core/test_curves.py -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add nocturne/core/curves.py tests/core/test_curves.py
git commit -m "feat: curves core — monotone-cubic LUT, apply_curve, gentle_s_points"
```

---

### Task 2: CurveEditor widget (`ui/curve_editor.py`)

**Files:**
- Create: `nocturne/ui/curve_editor.py`
- Test: `tests/ui/test_curve_editor.py`

**Interfaces:**
- Consumes: `build_lut` from `nocturne.core.curves` (Task 1); `nocturne.ui.theme` colors.
- Produces: `CurveEditor(QWidget)` with:
  - signal `curveChanged` (emits `list[tuple[float, float]]`) on every edit.
  - `points() -> list[tuple[float, float]]`
  - `set_points(pts)` — replace model (sanitized: sorted, clamped, corners enforced, min x-gap `0.02`); emits `curveChanged`.
  - `add_point(x, y)`, `remove_point(index)` (refuses corners), `reset()`.
  - `set_histogram(data)` — stash normalized luminance histogram for the backdrop.

- [ ] **Step 1: Write the failing tests**

Create `tests/ui/test_curve_editor.py`:

```python
import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.ui.curve_editor import CurveEditor  # noqa: E402


def test_starts_at_identity(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    assert w.points() == [(0.0, 0.0), (1.0, 1.0)]


def test_set_points_round_trip_and_corner_enforcement(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    w.set_points([(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)])
    assert w.points() == [(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)]


def test_add_point_sorts_and_clamps(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    w.add_point(0.6, 0.4)
    w.add_point(0.3, 0.2)
    xs = [p[0] for p in w.points()]
    assert xs == sorted(xs)
    assert w.points()[0] == (0.0, 0.0) and w.points()[-1] == (1.0, 1.0)


def test_min_gap_drops_too_close_interior(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    w.set_points([(0.0, 0.0), (0.5, 0.5), (0.505, 0.6), (1.0, 1.0)])
    xs = [p[0] for p in w.points()]
    assert len(xs) == 3            # the 0.505 point was too close to 0.5 -> dropped


def test_remove_interior_but_not_corner(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    w.set_points([(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)])
    w.remove_point(0)              # corner -> refused
    assert len(w.points()) == 3
    w.remove_point(1)              # interior -> removed
    assert w.points() == [(0.0, 0.0), (1.0, 1.0)]


def test_reset_restores_identity(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    w.set_points([(0.0, 0.0), (0.4, 0.6), (1.0, 1.0)])
    w.reset()
    assert w.points() == [(0.0, 0.0), (1.0, 1.0)]


def test_curve_changed_emits(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.curveChanged, timeout=500):
        w.add_point(0.5, 0.6)


def test_set_histogram_accepts_mono_and_rgb(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    w.set_histogram(np.random.default_rng(0).random((16, 16)).astype(np.float32))
    w.set_histogram(np.random.default_rng(1).random((16, 16, 3)).astype(np.float32))
    w.grab()   # force a paint with histogram present -> must not raise


def test_paint_without_histogram(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    w.resize(240, 240)
    w.grab()   # paint with no histogram set -> must not raise
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_curve_editor.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nocturne.ui.curve_editor'`.

- [ ] **Step 3: Write the implementation**

Create `nocturne/ui/curve_editor.py`:

```python
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core.curves import build_lut
from .theme import BG_0, BORDER

_MIN_GAP = 0.02
_HIT = 0.035          # handle hit radius in normalized coords
_MARGIN = 8           # px inset so handles at the edges stay visible


class CurveEditor(QWidget):
    """A draggable tone-curve editor. Interior points can be added (click empty
    space), moved (drag), and removed (double-click); the two corner endpoints
    (0,0) and (1,1) are pinned. Emits `curveChanged` with the point list."""

    curveChanged = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(240, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._points: list[tuple[float, float]] = [(0.0, 0.0), (1.0, 1.0)]
        self._hist = None          # normalized [0,1] bin heights, or None
        self._drag: int | None = None

    # --- model ---
    def points(self) -> list[tuple[float, float]]:
        return list(self._points)

    @staticmethod
    def _sanitize(pts) -> list[tuple[float, float]]:
        interior = sorted((float(np.clip(x, 0, 1)), float(np.clip(y, 0, 1)))
                          for x, y in pts if 0.0 < x < 1.0)
        out = [(0.0, 0.0)]
        for x, y in interior:
            if x - out[-1][0] >= _MIN_GAP:
                out.append((x, y))
        if len(out) > 1 and (1.0 - out[-1][0]) < _MIN_GAP:
            out.pop()
        out.append((1.0, 1.0))
        return out

    def set_points(self, pts) -> None:
        self._points = self._sanitize(pts)
        self.update()
        self.curveChanged.emit(self.points())

    def add_point(self, x: float, y: float) -> None:
        self.set_points(self._points + [(x, y)])

    def remove_point(self, index: int) -> None:
        if 0 < index < len(self._points) - 1:   # never a corner
            self.set_points(self._points[:index] + self._points[index + 1:])

    def reset(self) -> None:
        self.set_points([(0.0, 0.0), (1.0, 1.0)])

    def set_histogram(self, data) -> None:
        lum = data.mean(axis=2) if data.ndim == 3 else data
        counts, _ = np.histogram(np.clip(lum, 0, 1), bins=128, range=(0.0, 1.0))
        peak = counts.max() or 1
        self._hist = (counts / peak).astype(float)
        self.update()

    # --- coordinate mapping (normalized [0,1] <-> widget px; y is inverted) ---
    def _plot_rect(self):
        return (_MARGIN, _MARGIN,
                max(1, self.width() - 2 * _MARGIN),
                max(1, self.height() - 2 * _MARGIN))

    def _to_px(self, x: float, y: float):
        ox, oy, w, h = self._plot_rect()
        return QPointF(ox + x * w, oy + (1.0 - y) * h)

    def _to_norm(self, px: float, py: float):
        ox, oy, w, h = self._plot_rect()
        return (float(np.clip((px - ox) / w, 0, 1)),
                float(np.clip(1.0 - (py - oy) / h, 0, 1)))

    def _nearest(self, x: float, y: float):
        best, best_d = None, _HIT
        for i, (px, py) in enumerate(self._points):
            d = ((px - x) ** 2 + (py - y) ** 2) ** 0.5
            if d < best_d:
                best, best_d = i, d
        return best

    # --- mouse ---
    def mousePressEvent(self, e) -> None:
        x, y = self._to_norm(e.position().x(), e.position().y())
        i = self._nearest(x, y)
        if i is None:
            self.add_point(x, y)
            self._drag = self._nearest(x, y)     # grab the just-added point
        else:
            self._drag = i
        e.accept()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is None:
            return
        i = self._drag
        if i == 0 or i == len(self._points) - 1:  # corners are pinned
            return
        x, y = self._to_norm(e.position().x(), e.position().y())
        lo = self._points[i - 1][0] + _MIN_GAP
        hi = self._points[i + 1][0] - _MIN_GAP
        if hi <= lo:                              # no room -> keep current x
            x = self._points[i][0]
        else:
            x = float(np.clip(x, lo, hi))
        pts = list(self._points)
        pts[i] = (x, y)
        self._points = pts
        self.update()
        self.curveChanged.emit(self.points())

    def mouseReleaseEvent(self, e) -> None:
        self._drag = None
        e.accept()

    def mouseDoubleClickEvent(self, e) -> None:   # noqa: N802 (Qt override)
        x, y = self._to_norm(e.position().x(), e.position().y())
        i = self._nearest(x, y)
        if i is not None:
            self.remove_point(i)
        e.accept()

    # --- paint ---
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(BG_0))
        ox, oy, w, h = self._plot_rect()

        if self._hist is not None:
            fill = QColor(BORDER)
            fill.setAlpha(70)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            n = len(self._hist)
            for i, v in enumerate(self._hist):
                bx = ox + i / n * w
                bh = v * h
                p.drawRect(int(bx), int(oy + h - bh), max(1, int(w / n) + 1), int(bh))

        grid = QColor(BORDER)
        grid.setAlpha(110)
        p.setPen(QPen(grid, 1))
        for i in range(1, 4):
            p.drawLine(int(ox + w * i / 4), oy, int(ox + w * i / 4), oy + h)
            p.drawLine(ox, int(oy + h * i / 4), ox + w, int(oy + h * i / 4))
        diag = QColor(BORDER)
        diag.setAlpha(140)
        p.setPen(QPen(diag, 1, Qt.PenStyle.DashLine))
        p.drawLine(self._to_px(0, 0), self._to_px(1, 1))

        lut = build_lut(self._points, n=max(2, w))
        curve = QPolygonF([self._to_px(i / (len(lut) - 1), float(v))
                           for i, v in enumerate(lut)])
        p.setPen(QPen(QColor("#cccccc"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(curve)

        for i, (px, py) in enumerate(self._points):
            corner = i == 0 or i == len(self._points) - 1
            p.setBrush(QColor("#888888") if corner else QColor("#ffffff"))
            p.setPen(QPen(QColor("#333333"), 1))
            c = self._to_px(px, py)
            p.drawEllipse(c, 5, 5)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_curve_editor.py -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/curve_editor.py tests/ui/test_curve_editor.py
git commit -m "feat: CurveEditor widget — draggable points, pinned corners, histogram backdrop"
```

---

### Task 3: Register the Curves stage (step, factory, pipeline, recipe, help)

**Files:**
- Create: `nocturne/steps/curves.py`
- Modify: `nocturne/steps/factory.py`
- Modify: `nocturne/ui/pipeline.py`
- Modify: `nocturne/recipe.py`
- Modify: `nocturne/ui/help_content.py`
- Test: `tests/steps/test_factory.py`, `tests/ui/test_pipeline.py`, `tests/test_recipe.py`

**Interfaces:**
- Consumes: `apply_curve` from `nocturne.core.curves` (Task 1); `nocturne.history.step.Step`.
- Produces: `CurvesStep` (`name = "Curves"`, `apply(img, option)` → `apply_curve`); stage id `"curves"` present in `path_stages()`, `STEP_NAME`, `PROCESSING_ORDER` (after `levels`, before `saturation`), and `POST_STRETCH_IDS`; `make_step("curves", ...)` → `CurvesStep`; recipe round-trips a points list.

- [ ] **Step 1: Write / update the failing tests**

Add to `tests/steps/test_factory.py`:

```python
def test_make_step_curves():
    from nocturne.steps.factory import make_step
    from nocturne.steps.curves import CurvesStep
    from nocturne.settings import Settings
    assert isinstance(make_step("curves", Settings()), CurvesStep)


def test_curves_step_applies_points():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.curves import apply_curve
    from nocturne.steps.curves import CurvesStep
    img = AstroImage(np.full((16, 16, 3), 0.5, np.float32), is_linear=False)
    pts = [(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)]
    assert np.allclose(CurvesStep().apply(img, pts).data, apply_curve(img, pts).data)
    # empty option -> identity no-op
    assert np.allclose(CurvesStep().apply(img, "").data, img.data, atol=1e-4)
```

Add to `tests/ui/test_pipeline.py` — update the two frozen lists and add a placement test.

Replace `test_path_stages_single_linear_flow`:

```python
def test_path_stages_single_linear_flow():
    ids = [s.id for s in path_stages()]
    assert ids == [
        "load", "crop", "background", "color", "deconvolution", "stretch",
        "recover_core", "levels", "curves", "saturation", "noise_sharpen",
        "local_contrast", "star_reduction", "enhancements", "export",
    ]
```

Replace the `PROCESSING_ORDER` assertion inside `test_step_name_and_order`:

```python
    assert PROCESSING_ORDER == [
        "background", "color", "remove_green", "deconvolution", "stretch",
        "recover_core", "levels", "curves", "saturation", "noise_sharpen",
        "local_contrast", "star_reduction",
    ]
```

Update the exact-set assertion in `test_post_stretch_ids_are_the_finishing_steps_minus_export` to include `"curves"` (add it to the expected `frozenset({...})` literal, keeping every existing member).

Add:

```python
def test_curves_placed_after_levels():
    from nocturne.ui.pipeline import POST_STRETCH_IDS, STEP_NAME
    ids = [s.id for s in path_stages()]
    assert ids.index("curves") == ids.index("levels") + 1
    assert ids.index("curves") < ids.index("saturation")
    assert STEP_NAME["curves"] == "Curves"
    assert "curves" in POST_STRETCH_IDS
```

Add to `tests/test_recipe.py`:

```python
def test_curves_option_round_trip():
    from nocturne.recipe import serialize_option, deserialize_option
    pts = [(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)]
    ser = serialize_option("curves", pts)
    assert ser == [[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]]   # JSON-friendly
    assert deserialize_option("curves", ser) == pts
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/steps/test_factory.py tests/ui/test_pipeline.py tests/test_recipe.py -q`
Expected: FAIL — `ModuleNotFoundError: nocturne.steps.curves` and the updated frozen-list assertions fail.

- [ ] **Step 3a: Create the step wrapper**

Create `nocturne/steps/curves.py`:

```python
from __future__ import annotations

from ..core.curves import apply_curve
from ..core.image import AstroImage
from ..history.step import Step

_IDENTITY = [(0.0, 0.0), (1.0, 1.0)]


class CurvesStep(Step):
    name = "Curves"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        points = option if option else _IDENTITY
        return apply_curve(img, points)
```

- [ ] **Step 3b: Register in the factory**

In `nocturne/steps/factory.py`, add the import next to the other step imports:

```python
from .curves import CurvesStep
```

and add this branch after the `levels` branch, before `saturation`:

```python
    if stage_id == "curves":
        return CurvesStep()
```

- [ ] **Step 3c: Register the stage in the pipeline**

In `nocturne/ui/pipeline.py`:

Insert into `_IN_APP_TAIL` after the `levels` Stage:

```python
    Stage("levels", "Levels", "levels"),
    Stage("curves", "Curves", "curves"),
    Stage("saturation", "Saturation", "saturation"),
```

Add to `STEP_NAME` after the `"levels"` entry:

```python
    "levels": "Levels",
    "curves": "Curves",
    "saturation": "Saturation",
```

Insert into `PROCESSING_ORDER` after `"levels"`:

```python
PROCESSING_ORDER = [
    "background", "color", "remove_green", "deconvolution", "stretch",
    "recover_core", "levels", "curves", "saturation", "noise_sharpen",
    "local_contrast", "star_reduction",
]
```

Add `"curves"` to `POST_STRETCH_IDS`:

```python
POST_STRETCH_IDS = frozenset({
    "recover_core", "levels", "curves", "saturation", "noise_sharpen",
    "local_contrast", "star_reduction", "enhancements",
})
```

- [ ] **Step 3d: Recipe serialization**

In `nocturne/recipe.py`, add a `curves` branch to both functions.

In `serialize_option`, before the final `return option`:

```python
    if stage_id == "curves":
        pts = option if option else [(0.0, 0.0), (1.0, 1.0)]
        return [[float(x), float(y)] for x, y in pts]
```

In `deserialize_option`, before the final `return value`:

```python
    if stage_id == "curves":
        return [tuple(p) for p in value]
```

- [ ] **Step 3e: Help topic**

In `nocturne/ui/help_content.py`:

Add to `_STAGE_TO_TOPIC` after the `"levels"` entry:

```python
    "levels": "levels",
    "curves": "curves",
    "saturation": "saturation",
```

Add a topic to `_TOPIC_LIST` (place it just before the `saturation` `_t(...)` entry so the guide reads in pipeline order):

```python
    _t("curves", "Curves",
       "Shape a tone curve to add midtone contrast.",
       "<h4>What it does</h4>"
       "<p>Bends the tones with a smooth curve. Where Levels sets the black point, "
       "midtone brightness and white point, Curves lets you add <b>contrast</b> in "
       "the middle — steepening the slope so the nebula gains punch — while leaving "
       "the darkest and brightest tones anchored.</p>"
       "<h4>How to use it</h4>"
       "<p>Click the curve to add a point, drag to move it, double-click to remove it. "
       "The faint histogram behind the grid shows where the sky and nebula sit — drop a "
       "point on the sky peak and leave it to pin the background, then lift the midtones. "
       "Or press <b>Add contrast</b> for a gentle S. Watch the live preview. Apply.</p>"
       "<h4>Tips</h4>"
       "<p>Small moves go a long way. A steep curve can crush the faint outer nebulosity "
       "into the background — keep an eye on the dim detail as you pull.</p>"),
```

Add `"curves"` to the "The Steps" `HelpSection` tuple after `"levels"`:

```python
    HelpSection("The Steps", ("crop", "background", "color", "deconvolution", "stretch",
                              "recover_core", "levels", "curves", "saturation",
                              "noise_sharpen", "local_contrast", "star_reduction",
                              "enhancements", "export")),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/steps/test_factory.py tests/ui/test_pipeline.py tests/ui/test_help_content.py tests/test_recipe.py -q`
Expected: PASS (all green, including the help completeness test now that `curves` has a topic).

- [ ] **Step 5: Commit**

```bash
git add nocturne/steps/curves.py nocturne/steps/factory.py nocturne/ui/pipeline.py nocturne/recipe.py nocturne/ui/help_content.py tests/steps/test_factory.py tests/ui/test_pipeline.py tests/test_recipe.py
git commit -m "feat: register Curves stage (step, factory, pipeline, recipe, help)"
```

---

### Task 4: Curves panel

**Files:**
- Modify: `nocturne/ui/step_panels.py` (import `CurveEditor`, add `on_curve_change`/`on_curve_preset` params + `curves` branch)
- Test: `tests/ui/test_step_panels.py`

**Interfaces:**
- Consumes: `CurveEditor` (Task 2); stage `curves` from `path_stages()` (Task 3).
- Produces: `build_panel(..., on_curve_change=None, on_curve_preset=None)`; panel with `w.curve_editor`, `w.reset_btn`, `w.add_contrast_btn`, `w.apply_btn`, `w.panel_kind == "curves"`; the editor's `curveChanged` → `on_curve_change(points)`; Reset/Add-contrast buttons → `on_curve_preset("reset"|"add_contrast")`; Apply → `on_apply(editor.points())`.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_step_panels.py`:

```python
def test_curves_panel_has_editor_and_presets(qtbot):
    changed, presets = [], []
    w = build_panel(_stage("curves"),
                    on_curve_change=changed.append,
                    on_curve_preset=presets.append)
    qtbot.addWidget(w)
    assert w.panel_kind == "curves"
    assert hasattr(w, "curve_editor")
    assert hasattr(w, "reset_btn") and hasattr(w, "add_contrast_btn")
    # editor edits route to on_curve_change
    w.curve_editor.add_point(0.5, 0.7)
    assert changed and changed[-1][-1] == (1.0, 1.0)   # emitted a point list
    # preset buttons route to on_curve_preset with the right kind
    w.reset_btn.click()
    w.add_contrast_btn.click()
    assert presets == ["reset", "add_contrast"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_step_panels.py::test_curves_panel_has_editor_and_presets -q`
Expected: FAIL — `build_panel()` got an unexpected keyword `on_curve_change` (or the `curves` kind falls through to a bare panel).

- [ ] **Step 3: Implement the panel**

In `nocturne/ui/step_panels.py`, add the import near the top (next to the other local widget imports):

```python
from .curve_editor import CurveEditor
```

Add the parameters to `build_panel`'s signature (next to `on_lc_change=None`):

```python
    on_lc_change=None,
    on_curve_change=None,
    on_curve_preset=None,
```

Add the branch (place it after the `levels` branch, matching pipeline order):

```python
    elif stage.kind == "curves":
        lay.addWidget(_desc_label(
            "Drag the curve to add midtone contrast. Drop a point on the "
            "background peak to pin the sky. Double-click a point to remove it."))
        editor = CurveEditor()
        if on_curve_change is not None:
            editor.curveChanged.connect(lambda pts: on_curve_change(pts))
        lay.addWidget(editor)

        preset_row = QHBoxLayout()
        reset_btn = QPushButton("Reset")
        add_btn = QPushButton("Add contrast")
        if on_curve_preset is not None:
            reset_btn.clicked.connect(lambda: on_curve_preset("reset"))
            add_btn.clicked.connect(lambda: on_curve_preset("add_contrast"))
        preset_row.addWidget(reset_btn)
        preset_row.addWidget(add_btn)
        lay.addLayout(preset_row)

        apply_btn = QPushButton("Apply Curves")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(editor.points()))
        lay.addWidget(apply_btn)

        w.curve_editor = editor
        w.reset_btn = reset_btn
        w.add_contrast_btn = add_btn
        w.apply_btn = apply_btn
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ui/test_step_panels.py -q`
Expected: PASS (all step-panel tests green).

- [ ] **Step 5: Commit**

```bash
git add nocturne/ui/step_panels.py tests/ui/test_step_panels.py
git commit -m "feat: Curves panel (embedded CurveEditor + Reset/Add-contrast presets)"
```

---

### Task 5: main_window live preview, presets + commit wiring

**Files:**
- Modify: `nocturne/ui/main_window.py` (import, `__init__` timer, preview + preset methods, `_rebuild_panel`, `_log_step`)
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `apply_curve`, `gentle_s_points` (Task 1); `_preview_base`, `_show_preview`, `current_stage_id`, `apply_current`, `build_panel` (existing); `w.curve_editor` (Task 4); stage `curves` in `PROCESSING_ORDER`/factory (Task 3, so `apply_current` commits it with no extra code).
- Produces: `_on_curve_change(points)`, `_render_curve_preview()`, `_on_curve_preset(kind)`; `_curve_pending`/`_curve_timer`; `on_curve_change`/`on_curve_preset` wired into `build_panel(...)`; `_rebuild_panel` seeds the editor histogram and clears `_curve_pending` on entering the stage; `curves` added to the `_log_step` label-suppression tuple.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_main_window.py` (mirror the existing `_window`, `_make_fits`, `_go_to_id` helpers and the entries-count non-commit idiom):

```python
def test_curve_live_preview_renders_without_commit(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("curves")
    entries_before = [name for name, _ in win.project.entries()]
    win._on_curve_change([(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)])
    win._render_curve_preview()
    assert not win.image_view._item.pixmap().isNull()
    assert [name for name, _ in win.project.entries()] == entries_before  # no commit


def test_curve_preview_updates_histogram(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("curves")
    seen = []
    monkeypatch.setattr(win.histogram_view, "set_image", lambda img: seen.append(img))
    win._on_curve_change([(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)])
    win._render_curve_preview()
    assert seen


def test_curve_add_contrast_preset_seeds_non_identity(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("curves")
    win._on_curve_preset("add_contrast")
    assert win._panel.curve_editor.points() != [(0.0, 0.0), (1.0, 1.0)]
    win._on_curve_preset("reset")
    assert win._panel.curve_editor.points() == [(0.0, 0.0), (1.0, 1.0)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py::test_curve_live_preview_renders_without_commit -q`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_render_curve_preview'`.

- [ ] **Step 3a: Import the core functions**

In `nocturne/ui/main_window.py`, next to `from ..core.hdr import recover_core`:

```python
from ..core.curves import apply_curve, gentle_s_points
```

- [ ] **Step 3b: Add the debounce timer in `__init__`**

After the `recover_core` timer block (ending `self._recover_timer.timeout.connect(self._render_recover_preview)`), add:

```python
        self._curve_pending = None
        self._curve_timer = QTimer(self)
        self._curve_timer.setSingleShot(True)
        self._curve_timer.timeout.connect(self._render_curve_preview)
```

- [ ] **Step 3c: Add the preview + preset methods**

After `_render_recover_preview` (before the `# --- star reduction live preview ---` section), add:

```python
    # --- curves live preview ---
    def _on_curve_change(self, points) -> None:
        """The curve was edited: stash the points and (re)start debounce."""
        self._curve_pending = list(points)
        self._curve_timer.start(90)

    def _render_curve_preview(self) -> None:
        """Non-committing live preview of the current curve."""
        if self.project is None or self.current_stage_id() != "curves":
            return
        img = self._preview_base("curves")
        points = (self._curve_pending if self._curve_pending is not None
                  else self._panel.curve_editor.points())
        self._show_preview(apply_curve(img, points).data)

    def _on_curve_preset(self, kind: str) -> None:
        """Reset or Add-contrast preset button: seed the editor's points."""
        if self.project is None or self.current_stage_id() != "curves":
            return
        if kind == "add_contrast":
            pts = gentle_s_points(self._preview_base("curves").data)
        else:
            pts = [(0.0, 0.0), (1.0, 1.0)]
        self._panel.curve_editor.set_points(pts)   # emits curveChanged -> preview
```

- [ ] **Step 3d: Seed histogram + reset + wire callbacks in `_rebuild_panel`**

In `_rebuild_panel`, next to the other per-stage resets (after the `recover_core` reset block):

```python
        if stage.id == "curves":
            self._curve_pending = None
```

In the same method's `build_panel(...)` call, add the callbacks next to `on_lc_change=self._on_lc_change,`:

```python
            on_lc_change=self._on_lc_change,
            on_curve_change=self._on_curve_change,
            on_curve_preset=self._on_curve_preset,
```

After the panel is built and assigned (near the `import`/`meta_label` seeding block that already checks `stage.kind == "import"`), seed the editor's histogram backdrop:

```python
        if stage.id == "curves" and loaded:
            new_panel.curve_editor.set_histogram(self._preview_base("curves").data)
```

(Place this before `self._right_layout.replaceWidget(...)` swaps the panel in, using `new_panel`, consistent with the existing `meta_label` seeding.)

- [ ] **Step 3e: Suppress the raw points list in the log label**

In `_log_step`, add `"curves"` to the tuple that maps to an empty label (the point list is not user-facing text):

```python
        if stage_id in ("color", "levels", "curves"):
            label = ""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -q`
Expected: PASS (all main-window tests green).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS (all tests green; count = previous total + the new curves/editor/panel/window/factory/pipeline/recipe tests).

- [ ] **Step 6: Commit**

```bash
git add nocturne/ui/main_window.py tests/ui/test_main_window.py
git commit -m "feat: Curves live preview, presets + histogram seeding in main window"
```

---

### Task 6: Real-data validation

**Files:**
- Modify (only if tuning is needed): `nocturne/core/curves.py` (`gentle_s_points` constants)
- Update: `TODO.md` (mark the Curves item done)

**Interfaces:**
- Consumes: the shipped Curves step + editor.
- Produces: validated preset; before/after evidence for sign-off.

- [ ] **Step 1: Drive the app on real data**

```bash
.venv/bin/python -m nocturne
```

Open a stretched target (e.g. `/Volumes/Work2/Images/Astro/NGC 7000_sub/NGC7000_182x20s_61min.fits`), run through Stretch → Levels, then land on **Curves**. Confirm: the histogram backdrop lines up with where the data sits; clicking adds a point, dragging moves it, double-click removes it; the corners stay pinned; **Add contrast** produces a pleasing S without lifting the sky; **Reset** returns to the diagonal; the live preview + top-right histogram track the drag and equal the committed result after Apply.

- [ ] **Step 2: Judge and, if needed, tune the preset**

If the **Add contrast** preset is too strong/weak or the background pin sits wrong, adjust the constants in `gentle_s_points` (`nocturne/core/curves.py`: the `0.10` background percentile, the `0.35`/`0.75` midpoint fractions, the `0.06` S depth), then re-run `.venv/bin/python -m pytest tests/core/test_curves.py -q` to confirm the tests still pass, and repeat Step 1.

- [ ] **Step 3: Capture before/after for sign-off**

Save a Reset (identity) and an Add-contrast screenshot and present them for approval. Do not merge until the user confirms.

- [ ] **Step 4: Mark the backlog item done and commit**

In `TODO.md`, change the "Curves — S-curve / tone curve (HIGH)" item from `- [ ]` to `- [x]` with a "done 2026-07-20" note. If constants were tuned:

```bash
git add nocturne/core/curves.py TODO.md
git commit -m "tune: Curves add-contrast preset validated on real data; mark backlog done"
```

Otherwise commit just the TODO update:

```bash
git add TODO.md
git commit -m "docs: mark Curves / S-curve done (validated on real data)"
```

---

## Self-Review

**Spec coverage:**
- `core/curves.py` `build_lut` (monotone-cubic), `apply_curve` (luminance, hue-preserved, no-op at identity), `gentle_s_points` (background-aware) → Task 1. ✅
- `CurveEditor` widget: draggable interior points, pinned corners, min-gap, add/move/remove, `curveChanged`, histogram backdrop, paint → Task 2. ✅
- Stage after Levels; `POST_STRETCH_IDS`; recipe points round-trip; help topic → Task 3. ✅
- Panel with editor + Reset/Add-contrast presets → Task 4. ✅
- Debounced live preview via `_preview_base`→`_show_preview` (image + histogram); preset handlers; histogram seeding on entry; commit via `apply_current`; log label suppression → Task 5. ✅
- Real-data validation + preset tuning → Task 6. ✅
- Tests: core, widget, panel, window, factory, pipeline (frozen lists), recipe → Tasks 1–5. ✅

**Placeholder scan:** No TBD/"handle edge cases"/"similar to" — every code step contains full code. ✅

**Type consistency:** `apply_curve(img, points)` and `points()` return `list[tuple[float,float]]` consistently across core, step wrapper, editor, panel, and main_window; `build_lut(points, n)` used by both `apply_curve` and the editor's `paintEvent`; callbacks `on_curve_change`/`on_curve_preset` consistent between `step_panels.py` and `main_window.py`; stage id `"curves"` consistent across pipeline, factory, recipe, help, panel kind; recipe serialize (`[[x,y],…]`) and deserialize (`[(x,y),…]`) are inverses (verified by `test_curves_option_round_trip`). ✅
