# Second-Tier Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline — chosen). Steps use checkbox (`- [ ]`).

**Goal:** Masked (lightness-aware) saturation, a Local Contrast step (CLAHE), a draggable Before/After split divider, and per-target stretch presets.

**Architecture:** Modify `core/saturation`; add `core/local_contrast` + `steps/local_contrast` + a pipeline stage; add compare mode to `ui/image_view`; add a Target dropdown to the stretch panel.

**Tech Stack:** Python 3.13 (.venv), PySide6, numpy, scikit-image, pytest+pytest-qt.

## Global Constraints
- Spec: `docs/superpowers/specs/2026-06-30-second-tier-polish-design.md`.
- New in-app stage `local_contrast` sits after `noise_sharpen`, before `star_reduction`.
- Before/After becomes a draggable split divider (replaces the whole-image swap).
- Run tests `.venv/bin/pytest`; Python `.venv/bin/python` (3.13); pytest-qt headless.

---

### Task 1: Masked saturation
**Files:** Modify `seestar_processor/core/saturation.py`, `tests/core/test_saturation.py`.

- [ ] **Step 1: Failing test** (add)
```python
def test_highlights_protected_vs_midtones():
    bright = np.tile(np.array([0.95, 0.85, 0.75], np.float32), (4, 4, 1))
    mid = np.tile(np.array([0.45, 0.35, 0.25], np.float32), (4, 4, 1))
    sb = saturate(AstroImage(bright), 1.0).data[0, 0]
    sm = saturate(AstroImage(mid), 1.0).data[0, 0]
    spread_b = sb.max() - sb.min()
    spread_m = sm.max() - sm.min()
    assert (spread_b - (0.95 - 0.75)) < (spread_m - (0.45 - 0.25))  # bright boosted less
```
- [ ] **Step 2: Run → FAIL** (current global boost treats both equally relative to base).
- [ ] **Step 3: Implement** — replace the factor application in `saturate`:
```python
def saturate(img: AstroImage, amount: float) -> AstroImage:
    if not img.is_color or amount <= 0:
        return img.copy()
    data = img.data
    lum = data.mean(axis=2, keepdims=True)
    factor = 1.0 + float(amount) * (1.0 - lum)  # protect highlights/stars
    out = np.clip(lum + (data - lum) * factor, 0.0, 1.0)
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear, metadata=dict(img.metadata))
```
- [ ] **Step 4: Run → PASS** (existing saturation tests still hold: a mid pixel still gains chroma).
- [ ] **Step 5: Commit** `feat: lightness-aware (masked) saturation`.

---

### Task 2: Local Contrast core
**Files:** Create `seestar_processor/core/local_contrast.py`; Test `tests/core/test_local_contrast.py`.
**Interfaces:** `enhance(img, amount) -> AstroImage`.

- [ ] **Step 1: Failing test**
```python
import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.local_contrast import enhance

def _img():
    rng = np.random.default_rng(0)
    return AstroImage(rng.random((48, 48, 3)).astype(np.float32), is_linear=False)

def test_enhance_changes_image_keeps_shape():
    img = _img()
    out = enhance(img, 0.6)
    assert out.data.shape == (48, 48, 3)
    assert out.data.dtype == np.float32
    assert not np.allclose(out.data, img.data)
    assert out.data.min() >= 0 and out.data.max() <= 1
    assert out.is_linear is False

def test_enhance_mono():
    img = AstroImage(np.random.default_rng(1).random((48, 48)).astype(np.float32))
    out = enhance(img, 0.5)
    assert out.data.ndim == 2
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement**
```python
from __future__ import annotations
import numpy as np
from skimage.exposure import equalize_adapthist
from .image import AstroImage

def enhance(img: AstroImage, amount: float) -> AstroImage:
    amount = float(np.clip(amount, 0.0, 1.0))
    data = np.clip(img.data, 0.0, 1.0).astype(np.float32)
    if data.ndim == 2:
        clahe = equalize_adapthist(data, clip_limit=0.01).astype(np.float32)
        out = data * (1 - amount) + clahe * amount
        return AstroImage(np.clip(out, 0, 1).astype(np.float32),
                          is_linear=img.is_linear, metadata=dict(img.metadata))
    lum = data.mean(axis=2)
    clahe = equalize_adapthist(lum, clip_limit=0.01).astype(np.float32)
    new_lum = lum * (1 - amount) + clahe * amount
    ratio = new_lum / np.maximum(lum, 1e-6)
    out = np.clip(data * ratio[..., None], 0.0, 1.0)
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear, metadata=dict(img.metadata))
```
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: add local contrast (CLAHE) core`.

---

### Task 3: Local Contrast step + pipeline + wiring
**Files:** Create `seestar_processor/steps/local_contrast.py`; Modify `seestar_processor/ui/pipeline.py`, `seestar_processor/ui/step_panels.py`, `seestar_processor/ui/main_window.py`; update `tests/ui/test_pipeline.py`, `tests/ui/test_main_window.py`, `tests/steps/` (new test).

- [ ] **Step 1: Failing test** `tests/steps/test_local_contrast_step.py`
```python
import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.steps.local_contrast import LocalContrastStep

def test_local_contrast_step():
    img = AstroImage(np.random.default_rng(0).random((32, 32, 3)).astype(np.float32))
    out = LocalContrastStep().apply(img, "medium")
    assert out.data.shape == (32, 32, 3)
    assert not np.allclose(out.data, img.data)
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement step**
```python
from __future__ import annotations
from ..core.image import AstroImage
from ..core.local_contrast import enhance
from ..history.step import Step

_AMOUNT = {"light": 0.3, "medium": 0.6, "strong": 0.9}

class LocalContrastStep(Step):
    name = "Local Contrast"
    def options(self) -> list[str]: return ["light", "medium", "strong"]
    def default_option(self) -> str: return "medium"
    def apply(self, img: AstroImage, option: str) -> AstroImage:
        return enhance(img, _AMOUNT[option])
```
- [ ] **Step 4: Pipeline** — in `_IN_APP_TAIL` insert `Stage("local_contrast", "Local Contrast", "process")` after `noise_sharpen` and before `star_reduction`; add `STEP_NAME["local_contrast"]="Local Contrast"`; in `PROCESSING_ORDER` insert `"local_contrast"` after `"noise_sharpen"`.
- [ ] **Step 5: Panel** — in `step_panels.py` add `_PROCESS_OPTIONS["local_contrast"]=["light","medium","strong"]` and `_DESCRIPTIONS["local_contrast"]="Boosts mid-scale structure (local contrast)."`
- [ ] **Step 6: main_window** — `_step_for`: add `if stage_id == "local_contrast": return LocalContrastStep()` (import it).
- [ ] **Step 7: Update tests** — `tests/ui/test_pipeline.py` in-app id list + PROCESSING_ORDER include `local_contrast`; `tests/ui/test_main_window.py` nav sequence + `_step_for` type.
- [ ] **Step 8: Run full suite → PASS.**
- [ ] **Step 9: Commit** `feat: add Local Contrast step to the in-app flow`.

---

### Task 4: Before/After draggable split divider
**Files:** Modify `seestar_processor/ui/image_view.py`, `seestar_processor/ui/main_window.py`; Test `tests/ui/test_image_view.py`, `tests/ui/test_main_window.py`.

**Interfaces:** `ImageView.set_compare(qimage | None)`, `compare_active() -> bool`.

- [ ] **Step 1: Failing test (image_view)**
```python
def test_compare_mode_sets_and_clears(qtbot):
    view = ImageView(); qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.set_compare(_qimage(40, 30))
    assert view.compare_active() is True
    view.set_compare(None)
    assert view.compare_active() is False
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement (image_view)** — add in `__init__`: `self._compare_clip = None`, `self._compare_item = None`, `self._divider = None`, `self._split_x = 0.0`. Methods:
```python
def set_compare(self, qimage) -> None:
    self._teardown_compare()
    if qimage is None:
        return
    from PySide6.QtWidgets import QGraphicsRectItem
    pm = QPixmap.fromImage(qimage)
    self._compare_clip = QGraphicsRectItem()
    self._compare_clip.setPen(QPen(Qt.PenStyle.NoPen))
    self._compare_clip.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemClipsChildrenToShape, True)
    self._compare_clip.setZValue(5)
    self._scene.addItem(self._compare_clip)
    self._compare_item = QGraphicsPixmapItem(pm, self._compare_clip)
    self._divider = QGraphicsRectItem(-1, 0, 2, pm.height())
    self._divider.setBrush(QBrush(_ACCENT))
    self._divider.setPen(QPen(Qt.PenStyle.NoPen))
    self._divider.setZValue(6)
    self._divider.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, True)
    self._divider.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
    self._scene.addItem(self._divider)
    self._split_x = pm.width() / 2
    self._divider.setPos(self._split_x, 0)
    self._apply_split()

def compare_active(self) -> bool:
    return self._compare_item is not None

def _apply_split(self) -> None:
    h = self._compare_item.pixmap().height()
    self._compare_clip.setRect(0, 0, max(0.0, self._split_x), h)

def _teardown_compare(self) -> None:
    for it in (self._divider, self._compare_clip):
        if it is not None:
            self._scene.removeItem(it)
    self._divider = self._compare_clip = self._compare_item = None
```
Add divider drag handling: a `_DividerItem` subclass whose `itemChange` on `ItemPositionChange` clamps y=0, x in [0,width] and calls back `_split_x = x; _apply_split()`. (Mirror the crop `_Body` pattern: constrain to horizontal, update split on move.) For the test only set/clear matters; implement the drag callback for real use.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: main_window** — make Before/After drive compare:
```python
def _toggle_before_after(self) -> None:
    if self.project is None:
        self._ba_act.setChecked(False)
        return
    if self._ba_act.isChecked():
        before, _ = self.project.before_after()
        self.image_view.set_compare(to_qimage(before))
    else:
        self.image_view.set_compare(None)
```
Remove the old `self._before_after` swap branch in `_refresh` (render `project.current()` always); drop `self._before_after`. Re-assert the compare after a step if still checked is out of scope — toggling re-arms it.
- [ ] **Step 6: Update main_window test** — replace any `_before_after` assertion; add:
```python
def test_before_after_toggle_enables_compare(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch"); win.apply_current(0.5)
    win._ba_act.setChecked(True); win._toggle_before_after()
    assert win.image_view.compare_active() is True
    win._ba_act.setChecked(False); win._toggle_before_after()
    assert win.image_view.compare_active() is False
```
- [ ] **Step 7: Run full suite → PASS.**
- [ ] **Step 8: Commit** `feat: draggable Before/After split divider`.

---

### Task 5: Per-target stretch presets
**Files:** Modify `seestar_processor/ui/step_panels.py`, `tests/ui/test_step_panels.py`.

- [ ] **Step 1: Failing test**
```python
def test_stretch_target_sets_slider(qtbot):
    w = build_panel(_stage("stretch"), on_apply=lambda v: None)
    qtbot.addWidget(w)
    w.target_box.setCurrentText("Nebula")
    assert w.stretch_slider.value() == 60
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** — in the stretch panel branch, before the slider, add:
```python
STRETCH_TARGET_DEFAULTS = {"Auto": 50, "Nebula": 60, "Galaxy": 40, "Cluster": 50}
```
(module level) and in the stretch branch:
```python
        target = QComboBox()
        target.addItems(list(STRETCH_TARGET_DEFAULTS))
        target.currentTextChanged.connect(
            lambda t: slider.setValue(STRETCH_TARGET_DEFAULTS[t])
        )
        lay.addWidget(QLabel("Target"))
        lay.addWidget(target)
        w.target_box = target
```
(place after `slider` is created so the lambda can reference it; add the widgets in order Target then Aggressiveness).
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: per-target stretch presets`.

---

## Verification (end to end)
`.venv/bin/python -m seestar_processor`: Saturation no longer over-colors bright stars; a Local Contrast step appears after Noise & Sharpen and visibly boosts structure; Before/After shows a draggable divider (before|after) you can slide; the Stretch panel has a Target dropdown that moves the slider.

## Self-Review
- Coverage: masked saturation (T1), local contrast core+step+pipeline+wiring (T2,T3), split divider (T4), target presets (T5).
- Types: `saturate(img,amount)`, `enhance(img,amount)`, `LocalContrastStep`, `ImageView.set_compare/compare_active`, `STRETCH_TARGET_DEFAULTS`, `target_box` — consistent across tasks.
