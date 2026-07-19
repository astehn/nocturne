# Levels step rework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Live preview + Auto + clipping indicators + numeric readouts + plainer label for the Levels step. Design: `docs/superpowers/specs/2026-07-19-levels-rework-design.md`.

**Architecture:** two pure core helpers (`auto_levels`, `clipping_masks`); a debounced live-preview render in `MainWindow`; new panel controls wired via callbacks. `apply_levels` unchanged.

**Tech Stack:** Python, NumPy, PySide6, pytest-qt.

## Global Constraints
- No change to `apply_levels` semantics; Levels stays colour-safe + gated after Stretch.
- Live preview never commits — only the Apply button commits (existing path).
- Clipping colours: shadow `(40,120,255)` blue, highlight `(255,60,40)` red.
- Run tests via `.venv/bin/python -m pytest`.

---

### Task 1: core helpers — `auto_levels` + `clipping_masks`
**Files:** Modify `nocturne/core/levels.py`. Test: `tests/core/test_levels.py`.

- [ ] **Step 1: failing tests** (`tests/core/test_levels.py`):
```python
import numpy as np
from nocturne.core.levels import auto_levels, clipping_masks

def _stretched():
    rng = np.random.default_rng(0)
    d = np.clip(rng.normal(0.25, 0.05, (64, 64, 3)).astype(np.float32), 0, 1)
    d[:2, :2] = 0.98  # a few bright pixels
    return d

def test_auto_levels_sane():
    d = _stretched()
    b, g, w = auto_levels(d)
    assert 0.0 <= b < w <= 1.0
    assert 0.4 <= g <= 2.5
    assert b < float(np.median(d)) < w

def test_clipping_masks_flags_extremes():
    d = np.zeros((4, 4, 3), np.float32)
    d[0, 0] = 0.01; d[3, 3] = 0.99
    sh, hi = clipping_masks(d, black=0.05, white=0.95)
    assert sh[0, 0] and hi[3, 3]
    assert not sh[3, 3] and not hi[0, 0]
```

- [ ] **Step 2:** run → fail. `.venv/bin/python -m pytest tests/core/test_levels.py -q`

- [ ] **Step 3: implement** in `nocturne/core/levels.py` (append; `import numpy as np` already present):
```python
def auto_levels(data: np.ndarray) -> tuple[float, float, float]:
    """Suggested (black, gamma, white) for a stretched image — gentle, never
    clips real signal hard."""
    lum = data.mean(axis=2) if data.ndim == 3 else data
    black = float(np.clip(np.percentile(lum, 1.0), 0.0, 0.5))
    white = float(np.percentile(lum, 99.9))
    white = max(white, black + 0.05)
    med = float(np.median(lum))
    x = float(np.clip((med - black) / max(white - black, 1e-4), 1e-3, 0.999))
    gamma = float(np.clip(np.log(x) / np.log(0.35), 0.4, 2.5))
    return black, gamma, white


def clipping_masks(data: np.ndarray, black: float, white: float):
    """Boolean (shadow_clipped, highlight_clipped) per pixel."""
    lum = data.mean(axis=2) if data.ndim == 3 else data
    return lum <= black, lum >= white
```

- [ ] **Step 4:** run → pass. **Step 5: commit** `feat(levels): auto_levels + clipping_masks helpers`.

---

### Task 2: Levels panel controls
**Files:** Modify `nocturne/ui/step_panels.py` (`levels` branch + `build_panel` signature). Test: `tests/ui/test_step_panels.py`.

**Interfaces:** `build_panel(..., on_levels_change=None, on_levels_auto=None, on_levels_clipping=None)`. Panel exposes `w.black_val`, `w.gamma_val`, `w.white_val` (readout labels), `w.auto_btn`, `w.clip_check`.

- [ ] **Step 1: failing test**:
```python
def test_levels_panel_controls(qapp):
    from PySide6.QtWidgets import QCheckBox
    seen = {}
    w = build_panel(_stage("levels"),
                    on_levels_change=lambda b, g, wt: seen.setdefault("chg", (b, g, wt)),
                    on_levels_auto=lambda: seen.setdefault("auto", True),
                    on_levels_clipping=lambda c: seen.setdefault("clip", c))
    assert hasattr(w, "auto_btn") and hasattr(w, "clip_check")
    labels = " ".join(l.text() for l in w.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel))
    assert "Midtones" in labels and "(gamma)" not in labels
    w.black_slider.setValue(20)                 # fires on_levels_change + readout
    assert "chg" in seen
    assert w.black_val.text().strip() != ""
    w.auto_btn.click(); assert seen.get("auto") is True
    w.clip_check.setChecked(True); assert seen.get("clip") is True
```

- [ ] **Step 2:** run → fail.

- [ ] **Step 3: implement** — add the three callbacks to `build_panel`'s signature; rework the `elif stage.kind == "levels":` branch:
  - Keep `black`/`gamma`/`white` ResetSliders + `apply_btn` (Apply path unchanged).
  - For each slider add a small readout `QLabel` (`w.black_val`/`w.gamma_val`/`w.white_val`); a helper `def _emit(*_): ...` connected to all three sliders' `valueChanged` that (a) updates the three readout labels (`f"{black.value()/100:.2f}"`, gamma `f"{gamma.value()/100:.2f}"`, white `f"{white.value()/100:.2f}"`) and (b) calls `on_levels_change(black.value()/100, gamma.value()/100, white.value()/100)` if provided.
  - Add an **"Auto"** `QPushButton` → `on_levels_auto`; a **"Show clipping"** `QCheckBox` → `on_levels_clipping` (`toggled`).
  - Label the midtones row **"Midtones"** (no "(gamma)").
  - Layout order suggestion: Auto button on top, then the three labelled sliders each with its readout, then Show-clipping checkbox, then Apply.
  - `QCheckBox` is not currently imported in step_panels — add it back to the `PySide6.QtWidgets` import.

- [ ] **Step 4:** run → pass. **Step 5: commit** `feat(levels): panel — Auto, Show-clipping, numeric readouts, plainer label`.

---

### Task 3: live preview + clipping render (main_window)
**Files:** Modify `nocturne/ui/main_window.py`. Test: `tests/ui/test_main_window.py`.

- [ ] **Step 1: failing tests** (reuse the window+load helpers; navigate to levels):
```python
def test_levels_auto_sets_sliders(qtbot, tmp_path):
    win = _window(qtbot, tmp_path); win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch"); win.apply_current(0.5)   # need non-linear for levels
    win._go_to_id("levels")
    win._on_levels_auto()
    from nocturne.core.levels import auto_levels
    b, g, wt = auto_levels(win.project.current().data)
    assert abs(win._panel.black_slider.value()/100 - b) < 0.02

def test_levels_clipping_preview_paints(qtbot, tmp_path):
    win = _window(qtbot, tmp_path); win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch"); win.apply_current(0.5)
    win._go_to_id("levels")
    win._on_levels_clipping(True)
    win._on_levels_change(0.4, 1.0, 0.6)   # aggressive clip
    win._render_levels_preview()
    # the rendered qimage should contain the shadow-blue overlay somewhere
    qi = win.image_view._item.pixmap().toImage()
    from PySide6.QtGui import qRed, qGreen, qBlue
    found = any(
        qBlue(qi.pixel(x, y)) > 200 and qRed(qi.pixel(x, y)) < 120
        for y in range(0, qi.height(), 7) for x in range(0, qi.width(), 7))
    assert found
```
(Adjust the `apply_current(0.5)` call to however the existing tests commit a stretch; the goal is a non-linear image so Levels is allowed.)

- [ ] **Step 2:** run → fail.

- [ ] **Step 3: implement** in `main_window.py`:
  - In `__init__`: `self._levels_show_clipping = False`; `self._levels_pending = None`; a single-shot `QTimer` `self._levels_timer` (90 ms) → `self._render_levels_preview`.
  - `_on_levels_change(self, black, gamma, white)`: `self._levels_pending = (black, gamma, white)`; `self._levels_timer.start(90)`.
  - `_on_levels_auto(self)`: guard project/stage; `b,g,w = auto_levels(self.project.current().data)`; set `self._panel.black_slider.setValue(round(b*100))`, gamma `round(g*100)`, white `round(w*100)` (this fires `_on_levels_change`); then `self._render_levels_preview()`.
  - `_on_levels_clipping(self, checked)`: `self._levels_show_clipping = bool(checked)`; `self._render_levels_preview()`.
  - `_render_levels_preview(self)`: return unless on the `levels` stage with a project. Read slider values (from `self._levels_pending` or the panel). `img = self.project.current()`; `out = np.clip(apply_levels(img, b, g, w).data, 0, 1)`; `rgb = (out*255+0.5).astype(np.uint8)`; if 2-D expand to 3. If `self._levels_show_clipping`: `sh, hi = clipping_masks(img.data, b, w)`; `rgb[sh] = (40,120,255)`; `rgb[hi] = (255,60,40)`. Build a QImage (`from .preview import rgb_to_qimage` — factor it out of `to_qimage`, or inline the `QImage(rgb.data, w, h, 3*w, Format_RGB888).copy()` tail). `self.image_view.set_image(qimg)`.
  - Wire the three new callbacks into the `build_panel(...)` call: `on_levels_change=self._on_levels_change, on_levels_auto=self._on_levels_auto, on_levels_clipping=self._on_levels_clipping`.
  - Import `apply_levels`, `auto_levels`, `clipping_masks` from `..core.levels`; `numpy as np` is already imported.
  - Reset `self._levels_show_clipping = False` in `_rebuild_panel` (or when entering the levels stage) so it starts off each visit.

- [ ] **Step 4:** run the two tests → pass. **Step 5: full suite** `.venv/bin/python -m pytest tests/ -q` → all green. **Step 6: commit** `feat(levels): debounced live preview + clipping overlay + Auto`.

---

### Optional Task 4 (small): factor `rgb_to_qimage`
If Task 3 inlined the QImage tail, optionally extract `rgb_to_qimage(rgb_uint8)` in `nocturne/ui/preview.py` and have both `to_qimage` and the levels preview use it. Only if it reduces duplication cleanly; otherwise skip.
