# Palette v2 — Starless Narrowband Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Palette tool as an interactive editor operation that removes stars (StarX), colours the starless nebula with live-tweakable sliders (palette / Ha-OIII balance / saturation / SCNR), and screens neutral-white stars back — applied to the current image and recorded in history.

**Architecture:** Extend the Qt-free `core/palette.py` with composition primitives, then rebuild `ui/palette_dialog.py` as an interactive dialog (StarX once → cached layers → downscaled live preview → Apply pushes full-res result into project history). Reuses `RCAstro.remove_stars`, `ui/worker`, `ui/preview.to_qimage`, `core/color`/`core/saturation`.

**Tech Stack:** Python 3.11+, numpy, PySide6, RC-Astro StarXTerminator (optional).

## Global Constraints

- Package is `seestar_processor` (do NOT rename). Use the venv (`.venv/bin/python`, `.venv/bin/pytest`); system python is 3.9 and fails.
- UI tests run headless: prefix with `QT_QPA_PLATFORM=offscreen`.
- `core/` stays Qt-free.
- Palette v2 REPLACES v1's file-in/out dialog. Keep the existing `core/palette.py` v1 functions (`extract_channels`, `hoo`, `pseudo_sho`, `apply_palette`, `subtract_background`) — extend, don't delete.
- All colour work is on the STARLESS nebula; stars are neutralized to white and screened back last.
- pseudo-SHO stays honestly labeled (no real SII).
- Graceful fallback: if RC-Astro isn't configured, apply the palette to the whole image (no star separation) with a note.
- Commit after each task. Create the `palette-v2` branch first (do not start on `main`).

---

## File Structure

- `seestar_processor/core/palette.py` — ADD `PaletteParams`, `neutralize_stars`, `screen`, `render_nebula`, `compose`.
- `seestar_processor/ui/palette_dialog.py` — REBUILD as the interactive dialog.
- `seestar_processor/ui/main_window.py` — `_open_palette` opens the new dialog on the current image; add `_record_palette`.
- Tests: `tests/core/test_palette.py` (extend), `tests/ui/test_palette_dialog.py` (rewrite), `tests/ui/test_main_window.py` (add two).

---

## Task 0: Branch setup

- [ ] **Step 1: Create the feature branch**

```bash
cd /Volumes/Work/Code/Editor
git checkout -b palette-v2
git status   # expect: On branch palette-v2, clean
```

---

## Task 1: `core/palette.py` — compositing primitives

**Files:**
- Modify: `seestar_processor/core/palette.py`
- Test: `tests/core/test_palette.py`

**Interfaces:**
- Consumes: existing `extract_channels(img)`; `AstroImage`.
- Produces:
  - `@dataclass PaletteParams(palette="HOO", balance=0.5, saturation=0.5, scnr=True)`
  - `neutralize_stars(stars: AstroImage) -> AstroImage`
  - `screen(base: np.ndarray, top: np.ndarray) -> np.ndarray`
  - `render_nebula(starless: AstroImage, params: PaletteParams) -> AstroImage`
  - `compose(starless: AstroImage, stars: AstroImage, params: PaletteParams) -> AstroImage`

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_palette.py`:

```python
def test_neutralize_stars_makes_white():
    from seestar_processor.core.palette import neutralize_stars
    out = neutralize_stars(_img([(0.8, 0.2, 0.2)])).data[0, 0]
    assert np.allclose(out, out[0])              # R==G==B (grey/white)
    assert np.isclose(out[0], 0.4, atol=1e-6)    # = mean(0.8,0.2,0.2)


def test_screen_blend_math():
    from seestar_processor.core.palette import screen
    a = np.array([0.5, 0.0], np.float32)
    b = np.array([0.5, 0.3], np.float32)
    out = screen(a, b)
    assert np.isclose(out[0], 0.75)              # 1-(1-.5)(1-.5)
    assert np.isclose(out[1], 0.3)               # screen with 0 base = top


def test_render_nebula_saturation_zero_is_grey():
    from seestar_processor.core.palette import render_nebula, PaletteParams
    out = render_nebula(_img([(0.9, 0.1, 0.3)]), PaletteParams(saturation=0.0)).data[0, 0]
    assert np.allclose(out, out[0], atol=1e-6)   # greyscale


def test_render_nebula_balance_shifts_ha_oiii():
    from seestar_processor.core.palette import render_nebula, PaletteParams
    px = [(0.6, 0.6, 0.6)]                        # equal Ha and OIII
    ha_heavy = render_nebula(_img(px), PaletteParams(palette="HOO", balance=1.0)).data[0, 0]
    oiii_heavy = render_nebula(_img(px), PaletteParams(palette="HOO", balance=0.0)).data[0, 0]
    assert ha_heavy[0] > ha_heavy[2]             # balance=1 -> red (Ha) dominant
    assert oiii_heavy[2] > oiii_heavy[0]         # balance=0 -> blue (OIII) dominant


def test_render_nebula_scnr_reduces_green():
    from seestar_processor.core.palette import render_nebula, PaletteParams
    px = [(0.2, 0.9, 0.2)]
    with_scnr = render_nebula(_img(px), PaletteParams(scnr=True)).data[0, 0]
    without = render_nebula(_img(px), PaletteParams(scnr=False)).data[0, 0]
    assert with_scnr[1] <= without[1]


def test_compose_screens_stars_back():
    from seestar_processor.core.palette import compose, PaletteParams
    starless = _img([(0.3, 0.4, 0.4), (0.3, 0.4, 0.4)])
    stars = _img([(0.0, 0.0, 0.0), (0.9, 0.9, 0.9)])   # a star only in pixel 1
    out = compose(starless, stars, PaletteParams()).data
    assert out.shape == (1, 2, 3)
    assert out[0, 1].mean() > out[0, 0].mean()          # star pixel is brighter
```

- [ ] **Step 2: Run it, expect failure**

Run: `.venv/bin/pytest tests/core/test_palette.py -q`
Expected: FAIL (`cannot import name 'neutralize_stars'` etc.).

- [ ] **Step 3: Implement**

Add to `seestar_processor/core/palette.py` (keep existing content; add `from dataclasses import dataclass` at the top if not present):

```python
from dataclasses import dataclass


@dataclass
class PaletteParams:
    palette: str = "HOO"        # "HOO" | "pseudo_SHO"
    balance: float = 0.5        # 0 = OIII emphasis .. 0.5 neutral .. 1 = Ha emphasis
    saturation: float = 0.5     # 0 = greyscale .. 0.5 as-mapped .. 1 = strong
    scnr: bool = True           # green suppression on the nebula


def neutralize_stars(stars: AstroImage) -> AstroImage:
    """Replace the stars layer's colour with its luminance -> white stars, so
    they don't clash with the false-colour nebula."""
    if not stars.is_color:
        return stars.copy()
    lum = stars.data.mean(axis=2)
    rgb = np.clip(np.stack([lum, lum, lum], axis=2), 0.0, 1.0).astype(np.float32)
    return AstroImage(rgb, is_linear=stars.is_linear, metadata=dict(stars.metadata))


def screen(base: np.ndarray, top: np.ndarray) -> np.ndarray:
    """Screen blend: 1 - (1-base)*(1-top)."""
    b = np.clip(base, 0.0, 1.0)
    t = np.clip(top, 0.0, 1.0)
    return np.clip(1.0 - (1.0 - b) * (1.0 - t), 0.0, 1.0).astype(np.float32)


def _saturate_rgb(rgb: np.ndarray, saturation: float) -> np.ndarray:
    # k(0)=0 grey, k(0.5)=1 as-mapped, k(1)=2 strong
    k = float(saturation) * 2.0
    lum = rgb.mean(axis=2, keepdims=True)
    return np.clip(lum + k * (rgb - lum), 0.0, 1.0)


def render_nebula(starless: AstroImage, params: PaletteParams) -> AstroImage:
    """Colour the starless nebula: extract Ha/OIII, apply Ha/OIII balance, map to
    the chosen palette, apply saturation, then optional SCNR green suppression."""
    ha, oiii = extract_channels(starless)
    b = float(params.balance)
    ha = np.clip(ha * (2.0 * b), 0.0, 1.0)
    oiii = np.clip(oiii * (2.0 * (1.0 - b)), 0.0, 1.0)
    if params.palette == "pseudo_SHO":
        rgb = np.stack([ha, np.clip(0.5 * ha + 0.5 * oiii, 0.0, 1.0), oiii], axis=2)
    else:  # HOO
        rgb = np.stack([ha, oiii, oiii], axis=2)
    rgb = _saturate_rgb(rgb.astype(np.float32), params.saturation)
    if params.scnr:
        avg_rb = (rgb[..., 0] + rgb[..., 2]) / 2.0
        rgb[..., 1] = np.minimum(rgb[..., 1], avg_rb)
    return AstroImage(np.clip(rgb, 0.0, 1.0).astype(np.float32),
                      is_linear=starless.is_linear, metadata=dict(starless.metadata))


def compose(starless: AstroImage, stars: AstroImage, params: PaletteParams) -> AstroImage:
    """render_nebula(starless), then screen neutralize_stars(stars) back on top."""
    nebula = render_nebula(starless, params)
    white = neutralize_stars(stars)
    out = screen(nebula.data, white.data)
    return AstroImage(out, is_linear=starless.is_linear, metadata=dict(starless.metadata))
```

- [ ] **Step 4: Run tests, expect pass**

Run: `.venv/bin/pytest tests/core/test_palette.py -q`
Expected: PASS (existing v1 palette tests still pass too).

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/core/palette.py tests/core/test_palette.py
git commit -m "feat: palette compositing (render_nebula, neutralize_stars, screen, compose)"
```

---

## Task 2: Rebuild `ui/palette_dialog.py` — interactive starless dialog

**Files:**
- Rewrite: `seestar_processor/ui/palette_dialog.py`
- Rewrite: `tests/ui/test_palette_dialog.py`

**Interfaces:**
- Consumes: `core.palette.PaletteParams/render_nebula/compose`, `ui.preview.to_qimage`, `ui.worker.run_async`, `settings.rcastro_valid/resolve_binary`, `tools.rcastro.RCAstro`.
- Produces:
  - `class PaletteDialog(QDialog)` with `__init__(self, settings, base, parent=None, on_apply=None)`.
  - Attributes for tests: `hoo_radio`, `sho_radio`, `balance_slider`, `sat_slider`, `scnr_check`, `preview` (QLabel), `status`, `_async` (bool), `_starx_enabled` (bool), `_starx_runner` (callable(img)->(starless,stars)), `_starless`, `_stars`.
  - Methods: `start()` (kick off StarX or fallback), `apply()` (compose full-res → on_apply → close).

- [ ] **Step 1: Write the failing test**

Replace the entire contents of `tests/ui/test_palette_dialog.py` with:

```python
import numpy as np
import pytest

pytest.importorskip("PySide6")
from seestar_processor.settings import Settings  # noqa: E402
from seestar_processor.core.image import AstroImage  # noqa: E402
from seestar_processor.ui.palette_dialog import PaletteDialog  # noqa: E402


def _color(seed=0):
    rng = np.random.default_rng(seed)
    return AstroImage(rng.random((40, 50, 3)).astype(np.float32), is_linear=False)


def _fake_starx(img):
    # synthetic starless + a stars layer, same shape
    starless = AstroImage(img.data * 0.5, is_linear=img.is_linear)
    stars = AstroImage(img.data * 0.5, is_linear=img.is_linear)
    return starless, stars


def test_dialog_runs_starx_and_renders(qtbot):
    dlg = PaletteDialog(Settings(), _color())
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg._starx_enabled = True
    dlg._starx_runner = _fake_starx
    dlg.start()
    assert dlg._starless is not None and dlg._stars is not None
    assert not dlg.preview.pixmap().isNull()          # preview rendered


def test_slider_change_rerenders(qtbot):
    dlg = PaletteDialog(Settings(), _color())
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg._starx_enabled = True
    dlg._starx_runner = _fake_starx
    dlg.start()
    before = dlg.preview.pixmap().cacheKey()
    dlg.sat_slider.setValue(95)                        # should trigger a re-render
    assert dlg.preview.pixmap().cacheKey() != before


def test_apply_records_result(qtbot):
    got = {}
    dlg = PaletteDialog(Settings(), _color(), on_apply=lambda r: got.setdefault("r", r))
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg._starx_enabled = True
    dlg._starx_runner = _fake_starx
    dlg.start()
    dlg.sho_radio.setChecked(True)
    dlg.apply()
    assert "r" in got and got["r"].data.shape == (40, 50, 3)


def test_fallback_without_rcastro(qtbot):
    # Settings() has no RC-Astro path -> _starx_enabled False -> whole-image path
    dlg = PaletteDialog(Settings(), _color())
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg.start()
    assert dlg._starx_enabled is False
    assert dlg._stars is None                          # no star layer to screen back
    assert not dlg.preview.pixmap().isNull()           # still renders (whole-image)
```

- [ ] **Step 2: Run it, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_palette_dialog.py -q`
Expected: FAIL (new `PaletteDialog(settings, base, ...)` signature / attributes don't exist yet).

- [ ] **Step 3: Implement the dialog**

Replace the entire contents of `seestar_processor/ui/palette_dialog.py` with:

```python
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QSlider, QVBoxLayout, QWidget,
)

from ..core.image import AstroImage
from ..core.palette import PaletteParams, compose, render_nebula
from ..settings import rcastro_valid, resolve_binary
from ..tools.rcastro import RCAstro
from .preview import to_qimage
from .worker import run_async

_PREVIEW_MAX = 700  # long-side pixels for the interactive preview


def _downscale(img: AstroImage) -> AstroImage:
    h, w = img.data.shape[:2]
    step = max(1, max(h, w) // _PREVIEW_MAX)
    return AstroImage(np.ascontiguousarray(img.data[::step, ::step]),
                      is_linear=img.is_linear)


class PaletteDialog(QDialog):
    def __init__(self, settings, base: AstroImage, parent=None, on_apply=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Narrowband palette")
        self.setMinimumWidth(720)
        self._settings = settings
        self._base = base
        self._on_apply = on_apply
        self._pool = QThreadPool.globalInstance()
        self._async = True
        self._starx_enabled = rcastro_valid(settings)
        self._starx_runner = self._default_starx
        self._starless = None
        self._stars = None
        self._prev_starless = None
        self._prev_stars = None

        self.preview = QLabel("Removing stars…")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(480, 360)

        self.hoo_radio = QRadioButton("HOO")
        self.sho_radio = QRadioButton("Pseudo-SHO (no real SII)")
        self.hoo_radio.setChecked(True)
        self.balance_slider = self._slider()      # Ha <-> OIII
        self.sat_slider = self._slider()          # saturation
        self.scnr_check = QCheckBox("Green suppression (SCNR)")
        self.scnr_check.setChecked(True)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        for w in (self.hoo_radio, self.sho_radio):
            w.toggled.connect(self._render_preview)
        for s in (self.balance_slider, self.sat_slider):
            s.valueChanged.connect(self._render_preview)
        self.scnr_check.toggled.connect(self._render_preview)

        controls = QFormLayout()
        pal = QHBoxLayout()
        pal.addWidget(self.hoo_radio)
        pal.addWidget(self.sho_radio)
        pal_wrap = QWidget()
        pal_wrap.setLayout(pal)
        controls.addRow("Palette", pal_wrap)
        controls.addRow("Ha ◄─► OIII", self.balance_slider)
        controls.addRow("Saturation", self.sat_slider)
        controls.addRow("", self.scnr_check)

        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self.apply)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(apply_btn)
        buttons.addWidget(close_btn)

        body = QHBoxLayout()
        body.addWidget(self.preview, 2)
        side = QVBoxLayout()
        side.addLayout(controls)
        side.addStretch(1)
        side.addWidget(self.status)
        side.addLayout(buttons)
        side_wrap = QWidget()
        side_wrap.setLayout(side)
        body.addWidget(side_wrap, 1)

        root = QVBoxLayout(self)
        root.addLayout(body)

        self.start()

    # --- slider factory ---
    def _slider(self) -> QSlider:
        s = QSlider(Qt.Orientation.Horizontal)
        s.setMinimum(0)
        s.setMaximum(100)
        s.setValue(50)
        return s

    # --- StarX ---
    def _default_starx(self, img: AstroImage):
        rc = RCAstro(resolve_binary(self._settings.rcastro_path))
        return rc.remove_stars(img)

    def start(self) -> None:
        if not self._starx_enabled:
            self._starless = self._base
            self._stars = None
            self.status.setText("StarX not configured — palette applied to the whole image.")
            self._cache_previews()
            self._render_preview()
            return
        self.status.setText("Removing stars…")
        if self._async:
            run_async(self._pool, lambda: self._starx_runner(self._base),
                      self._on_starless, self._on_error)
        else:
            try:
                self._on_starless(self._starx_runner(self._base))
            except Exception as exc:  # noqa: BLE001
                self._on_error(exc)

    def _on_starless(self, layers) -> None:
        self._starless, self._stars = layers
        self.status.setText("")
        self._cache_previews()
        self._render_preview()

    def _on_error(self, exc) -> None:
        self.status.setText(f"Star removal failed: {exc}")

    def _cache_previews(self) -> None:
        self._prev_starless = _downscale(self._starless)
        self._prev_stars = _downscale(self._stars) if self._stars is not None else None

    # --- params + render ---
    def _params(self) -> PaletteParams:
        return PaletteParams(
            palette="HOO" if self.hoo_radio.isChecked() else "pseudo_SHO",
            balance=self.balance_slider.value() / 100.0,
            saturation=self.sat_slider.value() / 100.0,
            scnr=self.scnr_check.isChecked(),
        )

    def _result(self, starless: AstroImage, stars) -> AstroImage:
        params = self._params()
        if stars is not None:
            return compose(starless, stars, params)
        return render_nebula(starless, params)

    def _render_preview(self) -> None:
        if self._prev_starless is None:
            return
        result = self._result(self._prev_starless, self._prev_stars)
        self.preview.setPixmap(QPixmap.fromImage(to_qimage(result)))

    # --- apply ---
    def apply(self) -> None:
        if self._starless is None:
            self.status.setText("Still working…")
            return
        result = self._result(self._starless, self._stars)
        if self._on_apply is not None:
            self._on_apply(result)
        self.accept()
```

- [ ] **Step 4: Run tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_palette_dialog.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/palette_dialog.py tests/ui/test_palette_dialog.py
git commit -m "feat: interactive starless palette dialog (StarX once, live preview, sliders)"
```

---

## Task 3: Wire MainWindow + full suite + backlog

**Files:**
- Modify: `seestar_processor/ui/main_window.py` (`_open_palette`, add `_record_palette`)
- Modify: `tests/ui/test_main_window.py` (add two tests)
- Modify: `TODO.md`

**Interfaces:**
- Consumes: `PaletteDialog(settings, base, parent, on_apply)`, `Project.run_step`, `_PrecomputedStep`.
- Produces: `MainWindow._open_palette()` (guarded, opens dialog on current image), `MainWindow._record_palette(result)` (records a "Palette" history step).

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_main_window.py`:

```python
def test_open_palette_requires_image(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)          # no image loaded
    win._open_palette()
    assert "open" in win._status.text().lower()


def test_record_palette_adds_history_step(qtbot, tmp_path):
    import numpy as np
    from seestar_processor.core.image import AstroImage
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._record_palette(AstroImage(np.zeros((12, 12, 3), np.float32), is_linear=False))
    assert win.project.entries()[-1][0] == "Palette"
```

- [ ] **Step 2: Run it, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py::test_record_palette_adds_history_step tests/ui/test_main_window.py::test_open_palette_requires_image -q`
Expected: FAIL (`_record_palette` missing; `_open_palette` still opens the old file dialog / no guard).

- [ ] **Step 3: Implement**

In `seestar_processor/ui/main_window.py`, replace the existing `_open_palette` method (around lines 157-160) with:

```python
    def _open_palette(self) -> None:
        if self.project is None:
            self._status.setText("Open or stack an image first.")
            return
        base = self.project.current()
        if not base.is_color:
            self._status.setText("Palette needs a colour image.")
            return
        from .palette_dialog import PaletteDialog
        PaletteDialog(self.settings, base, self, on_apply=self._record_palette).exec()

    def _record_palette(self, result) -> None:
        self.project.run_step(_PrecomputedStep("Palette", result), "")
        self._status.setText("")
        self.log_panel.append_entry(format_log_entry("Palette", "", None))
        self._refresh()
```

(`format_log_entry` and `_PrecomputedStep` are already imported/defined in this module.)

- [ ] **Step 4: Run tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_main_window.py -q`
Expected: PASS.

- [ ] **Step 5: Full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass. If `test_sharpen_changes_image_and_keeps_shape` fails, it is a known pre-existing flake — rerun it alone to confirm it passes.

- [ ] **Step 6: Update the backlog**

In `TODO.md`, update the palette entry to note the starless v2:

```markdown
- [x] **Narrowband palette (HOO / pseudo-SHO), starless workflow.** Interactive "Palette…"
      on the current image: StarX removes stars (once), the starless nebula is coloured with
      live sliders (palette, Ha/OIII balance, saturation, SCNR), white stars are screened
      back, and Apply records a "Palette" history step. Falls back to whole-image without
      RC-Astro. `core/palette.py` + `ui/palette_dialog.py`.
```

- [ ] **Step 7: Commit**

```bash
git add seestar_processor/ui/main_window.py tests/ui/test_main_window.py TODO.md
git commit -m "feat: wire interactive Palette dialog into editor (history-recorded) + backlog"
```

---

## Definition of Done

- All tasks committed on `palette-v2`; full suite green.
- "Palette…" on a loaded colour image opens the interactive dialog; StarX runs once; sliders
  live-preview; Apply records an undoable "Palette" step. No RC-Astro → whole-image fallback.
- After merge: validate on the real Pelican (IC 5070) master — confirm white stars over a
  gold/teal nebula, and tune the balance/saturation defaults by eye.
- Finish with **superpowers:finishing-a-development-branch**.
```
