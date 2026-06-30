# OSC Quick Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline — chosen). Steps use checkbox (`- [ ]`).

**Goal:** Add green removal (SCNR) to the Color step, a live histogram + a Levels step, and a Star Reduction step.

**Architecture:** Pure core functions (`color` SCNR, `histogram`, `levels`, `star_reduction`) + their steps/panels; two new in-app pipeline stages (`levels`, `star_reduction`); a `HistogramView` widget shown in the right column and refreshed from the current image.

**Tech Stack:** Python 3.13 (.venv), PySide6, numpy, scipy, pytest+pytest-qt.

## Global Constraints
- Spec: `docs/superpowers/specs/2026-06-30-osc-quick-wins-design.md`.
- In-app order: load, destination, crop, background, color, stretch, **levels**, saturation, noise_sharpen, **star_reduction**, export. External path unchanged.
- `PROCESSING_ORDER = [crop, background, color, stretch, levels, saturation, noise_sharpen, star_reduction]`.
- `STEP_NAME` adds `levels→"Levels"`, `star_reduction→"Star Reduction"`.
- Star Reduction requires StarX (gated on `rcastro_valid`; no free fallback).
- Run tests `.venv/bin/pytest`; Python `.venv/bin/python` (3.13); pytest-qt headless.

---

### Task 1: SCNR green removal in Color
**Files:** Modify `seestar_processor/core/color.py`, `tests/core/test_color.py`.
**Interfaces:** `ColorSettings` gains `remove_green: bool = False`; `apply_color` applies SCNR average-neutral when color + remove_green.

- [ ] **Step 1: Failing test** (add to `tests/core/test_color.py`)
```python
def test_remove_green_clamps_green_excess():
    data = np.full((8, 8, 3), 0.3, dtype=np.float32)
    data[..., 1] = 0.8  # green excess
    out = apply_color(AstroImage(data),
                      ColorSettings(neutralize_background=False, white_balance=False,
                                    remove_green=True))
    assert out.data[..., 1].max() <= 0.3 + 1e-6  # clamped to (r+b)/2 = 0.3
```
- [ ] **Step 2: Run → FAIL** (ColorSettings has no `remove_green`).
- [ ] **Step 3: Implement** — add field + SCNR at the end of `apply_color`:
```python
@dataclass
class ColorSettings:
    neutralize_background: bool = True
    white_balance: bool = True
    remove_green: bool = False
```
…and before the final `return`, after the white-balance block:
```python
    if settings.remove_green:
        avg_rb = (data[..., 0] + data[..., 2]) / 2.0
        data[..., 1] = np.minimum(data[..., 1], avg_rb)
```
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: add SCNR green removal to Color`.

---

### Task 2: Histogram (core + widget)
**Files:** Create `seestar_processor/core/histogram.py`, `seestar_processor/ui/histogram_view.py`; Test `tests/core/test_histogram.py`, `tests/ui/test_histogram_view.py`.
**Interfaces:** `histogram(img, bins=256) -> dict[str, np.ndarray]` (`{"r","g","b"}` or `{"l"}`); `HistogramView(QWidget).set_image(AstroImage)`.

- [ ] **Step 1: Failing test (core)**
```python
import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.histogram import histogram


def test_color_histogram_channels_and_counts():
    h = histogram(AstroImage(np.full((10, 10, 3), 0.5, np.float32)), bins=256)
    assert set(h) == {"r", "g", "b"}
    assert all(len(v) == 256 for v in h.values())
    assert int(h["r"].sum()) == 100


def test_mono_histogram():
    h = histogram(AstroImage(np.zeros((4, 4), np.float32)), bins=64)
    assert set(h) == {"l"} and len(h["l"]) == 64
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement `core/histogram.py`**
```python
from __future__ import annotations
import numpy as np
from .image import AstroImage

def histogram(img: AstroImage, bins: int = 256) -> dict:
    data = np.clip(img.data, 0.0, 1.0)
    if data.ndim == 2:
        counts, _ = np.histogram(data, bins=bins, range=(0.0, 1.0))
        return {"l": counts}
    out = {}
    for i, key in enumerate(("r", "g", "b")):
        counts, _ = np.histogram(data[..., i], bins=bins, range=(0.0, 1.0))
        out[key] = counts
    return out
```
- [ ] **Step 4: Run → PASS.** Commit later with the widget.
- [ ] **Step 5: Failing test (widget)** `tests/ui/test_histogram_view.py`
```python
import numpy as np, pytest
pytest.importorskip("PySide6")
from seestar_processor.core.image import AstroImage  # noqa: E402
from seestar_processor.ui.histogram_view import HistogramView  # noqa: E402

def test_histogram_view_accepts_image(qtbot):
    v = HistogramView(); qtbot.addWidget(v)
    v.set_image(AstroImage(np.random.rand(16, 16, 3).astype(np.float32)))
    assert v._hist is not None
```
- [ ] **Step 6: Implement `ui/histogram_view.py`**
```python
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget
from ..core.histogram import histogram

_COLORS = {"r": "#ff5555", "g": "#55ff55", "b": "#5599ff", "l": "#cccccc"}


class HistogramView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(90)
        self._hist = None

    def set_image(self, img) -> None:
        self._hist = histogram(img, bins=256)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#131417"))
        if not self._hist:
            return
        w, h = self.width(), self.height()
        peak = max(int(c.max()) for c in self._hist.values()) or 1
        n = len(next(iter(self._hist.values())))
        for key, counts in self._hist.items():
            p.setPen(QPen(QColor(_COLORS[key])))
            for x in range(n):
                bx = int(x / n * w)
                bh = int(counts[x] / peak * (h - 2))
                p.drawLine(bx, h, bx, h - bh)
```
- [ ] **Step 7: Run both → PASS.**
- [ ] **Step 8: Commit** `feat: add histogram core + HistogramView widget`.

---

### Task 3: Levels (core + step + panel-ready)
**Files:** Create `seestar_processor/core/levels.py`, `seestar_processor/steps/levels.py`; Test `tests/core/test_levels.py`, `tests/steps/test_levels_step.py`.
**Interfaces:** `apply_levels(img, black, gamma, white) -> AstroImage`; `LevelsStep.apply(img, (black,gamma,white))`.

- [ ] **Step 1: Failing test (core)** `tests/core/test_levels.py`
```python
import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.levels import apply_levels

def test_identity():
    d = np.linspace(0, 1, 64, dtype=np.float32).reshape(8, 8)
    out = apply_levels(AstroImage(d), 0.0, 1.0, 1.0)
    assert np.allclose(out.data, d, atol=1e-6)

def test_raise_black_point_darkens():
    d = np.full((8, 8), 0.3, np.float32)
    out = apply_levels(AstroImage(d), 0.2, 1.0, 1.0)
    assert np.median(out.data) < 0.3

def test_gamma_above_one_brightens():
    d = np.full((8, 8), 0.3, np.float32)
    out = apply_levels(AstroImage(d), 0.0, 2.0, 1.0)
    assert np.median(out.data) > 0.3

def test_preserves_linear_flag_and_range():
    out = apply_levels(AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=False),
                       0.1, 1.5, 0.9)
    assert out.is_linear is False
    assert out.data.min() >= 0 and out.data.max() <= 1
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement `core/levels.py`**
```python
from __future__ import annotations
import numpy as np
from .image import AstroImage

def apply_levels(img: AstroImage, black: float, gamma: float, white: float) -> AstroImage:
    white = max(white, black + 1e-4)
    x = np.clip((img.data - black) / (white - black), 0.0, 1.0)
    out = np.power(x, 1.0 / max(gamma, 1e-3))
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear,
                      metadata=dict(img.metadata))
```
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Failing test (step)** `tests/steps/test_levels_step.py`
```python
import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.steps.levels import LevelsStep

def test_levels_step_applies_tuple():
    out = LevelsStep().apply(AstroImage(np.full((8, 8), 0.3, np.float32)), (0.2, 1.0, 1.0))
    assert np.median(out.data) < 0.3
```
- [ ] **Step 6: Implement `steps/levels.py`**
```python
from __future__ import annotations
from ..core.image import AstroImage
from ..core.levels import apply_levels
from ..history.step import Step

class LevelsStep(Step):
    name = "Levels"
    def options(self) -> list[str]: return []
    def default_option(self) -> str: return ""
    def apply(self, img: AstroImage, option) -> AstroImage:
        black, gamma, white = option if option else (0.0, 1.0, 1.0)
        return apply_levels(img, black, gamma, white)
```
- [ ] **Step 7: Run → PASS.**
- [ ] **Step 8: Commit** `feat: add Levels (core + step)`.

---

### Task 4: Star reduction (core + step)
**Files:** Create `seestar_processor/core/star_reduction.py`, `seestar_processor/steps/star_reduction.py`; Test `tests/core/test_star_reduction.py`, `tests/steps/test_star_reduction_step.py`.
**Interfaces:** `reduce_stars(starless, stars, amount) -> AstroImage`; `StarReductionStep(rcastro)` options light/medium/strong.

- [ ] **Step 1: Failing test (core)** `tests/core/test_star_reduction.py`
```python
import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.star_reduction import reduce_stars

def _stars():
    s = np.zeros((32, 32, 3), np.float32)
    s[16, 16] = 1.0  # a star
    return AstroImage(s)

def test_reduces_star_brightness():
    starless = AstroImage(np.full((32, 32, 3), 0.1, np.float32))
    out = reduce_stars(starless, _stars(), 0.9)
    assert out.data.shape == (32, 32, 3)
    # combined max stays <=1 and the star is dimmer than a plain screen of the full star
    full = 1 - (1 - starless.data) * (1 - _stars().data)
    assert out.data.max() <= full.max() + 1e-6
    assert out.data[16, 16].max() < full[16, 16].max()

def test_preserves_is_linear():
    starless = AstroImage(np.full((8, 8, 3), 0.1, np.float32), is_linear=False)
    stars = AstroImage(np.zeros((8, 8, 3), np.float32))
    assert reduce_stars(starless, stars, 0.5).is_linear is False
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement `core/star_reduction.py`**
```python
from __future__ import annotations
import numpy as np
from scipy.ndimage import grey_erosion
from .image import AstroImage

def reduce_stars(starless: AstroImage, stars: AstroImage, amount: float) -> AstroImage:
    amount = float(np.clip(amount, 0.0, 1.0))
    s = stars.data.astype(np.float32)
    size = 1 + int(round(amount * 3))  # erosion footprint grows with amount
    if s.ndim == 3:
        eroded = np.stack([grey_erosion(s[..., c], size=(size, size)) for c in range(3)], axis=2)
    else:
        eroded = grey_erosion(s, size=(size, size))
    reduced = eroded * (1.0 - 0.4 * amount)
    base = starless.data.astype(np.float32)
    out = 1.0 - (1.0 - base) * (1.0 - reduced)
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=starless.is_linear, metadata=dict(starless.metadata))
```
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Failing test (step)** `tests/steps/test_star_reduction_step.py`
```python
import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.tools.base import write_temp_fits
from seestar_processor.tools.rcastro import RCAstro
from seestar_processor.steps.star_reduction import StarReductionStep

def test_uses_starx_and_recombines():
    img = AstroImage(np.full((16, 16, 3), 0.2, np.float32), is_linear=False)
    calls = {}
    def fake(args):
        calls["args"] = args
        out = args[args.index("-o") + 1]
        write_temp_fits(AstroImage(img.data * 0.5), out)  # starless
        import os
        write_temp_fits(AstroImage(img.data * 0.5), os.path.join(os.path.dirname(out), "s-sxt.fits"))
    step = StarReductionStep(RCAstro("/fake")); step._runner = fake
    out = step.apply(img, "medium")
    assert "sxt" in calls["args"]
    assert out.data.shape == (16, 16, 3)
```
- [ ] **Step 6: Implement `steps/star_reduction.py`**
```python
from __future__ import annotations
from ..core.image import AstroImage
from ..core.star_reduction import reduce_stars
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro

_AMOUNT = {"light": 0.3, "medium": 0.6, "strong": 0.9}

class StarReductionStep(Step):
    name = "Star Reduction"
    def __init__(self, rcastro: RCAstro) -> None:
        self._rc = rcastro
        self._runner = run_cli
    def options(self) -> list[str]: return ["light", "medium", "strong"]
    def default_option(self) -> str: return "medium"
    def apply(self, img: AstroImage, option: str) -> AstroImage:
        starless, stars = self._rc.remove_stars(img, runner=self._runner)
        return reduce_stars(starless, stars, _AMOUNT[option])
```
- [ ] **Step 7: Run → PASS.**
- [ ] **Step 8: Commit** `feat: add Star Reduction (core + step)`.

---

### Task 5: Pipeline + panels + main_window wiring
**Files:** Modify `seestar_processor/ui/pipeline.py`, `seestar_processor/ui/step_panels.py`, `seestar_processor/ui/main_window.py`; update `tests/ui/test_pipeline.py`, `tests/ui/test_step_panels.py`, `tests/ui/test_main_window.py`.

**Pipeline:** add to `_IN_APP_TAIL` (in order): `Stage("levels","Levels","levels")` after stretch — but stretch is in `_CORE`. So the in-app tail becomes `[levels, saturation, noise_sharpen, star_reduction, export]` with `Stage("levels","Levels","levels")`, `Stage("star_reduction","Star Reduction","process")`. Add to `STEP_NAME` and `PROCESSING_ORDER`.

**Panels (`step_panels.py`):**
- color "auto" panel: add `QCheckBox("Remove green cast")` (checked); Apply emits `ColorSettings(remove_green=cb.isChecked())` (import `ColorSettings`); expose `remove_green_check`.
- new `levels` kind: 3 `QSlider`s (black 0–100, gamma 10–300, white 0–100, default 0/100/100) + Apply → `on_apply((black/100, gamma/100, white/100))`; expose `black_slider`, `gamma_slider`, `white_slider`, `apply_btn`.
- `star_reduction` uses the existing `process` kind (add to `_PROCESS_OPTIONS["star_reduction"] = ["light","medium","strong"]`); the process branch's disabled-note text is GraXpert-specific — generalize: show note only for background/star_reduction with stage-appropriate text (`"Needs RC-Astro …"` for star_reduction).

**main_window:**
- `_step_for`: `levels → LevelsStep()`; `star_reduction → StarReductionStep(RCAstro(resolve_binary(rcastro_path)))` with `_runner=self._rc_runner` (only built when valid; gate via panel).
- `_rebuild_panel`: `star_reduction` → `apply_enabled = loaded and rcastro_valid`.
- `_log_step`: `color` label `""`; `levels` label `""` (tuple option); others as before.
- `_refresh`: `self.histogram_view.set_image(<displayed image>)`.
- `__init__`: add `self.histogram_view = HistogramView()` at the top of the right column (`self._right_layout.insertWidget(0, self.histogram_view)` before the panel, or add before `_panel`).

- [ ] **Step 1: Update `pipeline.py`** (stages, STEP_NAME, PROCESSING_ORDER) and run `tests/ui/test_pipeline.py` — update expected in-app id list to include `levels` and `star_reduction`; fix next/prev assertions.
- [ ] **Step 2: Update `step_panels.py`** (color checkbox, levels panel, star_reduction options + note) and `tests/ui/test_step_panels.py` (color emits ColorSettings with remove_green; levels emits the tuple; star_reduction gated note).
- [ ] **Step 3: Update `main_window.py`** (histogram in right column + `_refresh`; `_step_for` levels/star_reduction; `_rebuild_panel` gating; `_log_step` color/levels labels) and `tests/ui/test_main_window.py` (nav sequence includes levels + star_reduction; `_step_for` returns LevelsStep/StarReductionStep; levels apply stays on step; histogram_view exists).
- [ ] **Step 4: Run full suite** `.venv/bin/pytest -q` → all pass, pristine.
- [ ] **Step 5: Commit** `feat: wire SCNR toggle, histogram, Levels and Star Reduction into the UI`.

---

## Verification (end to end)
`.venv/bin/python -m seestar_processor`: histogram shows top-right and updates per step; Color has a "Remove green cast" toggle; the in-app flow has Levels (3 sliders) after Stretch and Star Reduction (gated on RC-Astro) before Export; Levels darkens/brightens per the sliders; Star Reduction shrinks stars.

## Self-Review
- Coverage: SCNR (T1), histogram+widget (T2), Levels core+step (T3), star reduction core+step (T4), all UI wiring + pipeline + log labels (T5).
- Types: `ColorSettings.remove_green`, `histogram(img,bins)->dict`, `apply_levels(img,black,gamma,white)`, `LevelsStep.apply(img,(b,g,w))`, `reduce_stars(starless,stars,amount)`, `StarReductionStep(rcastro)` — used consistently across tasks and wiring.
