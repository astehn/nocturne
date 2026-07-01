# Palette v3 — Per-Channel Curves Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the palette dialog's global Ha/OIII-balance and saturation sliders with per-channel Black/Mid/White curves (R, G, B independently), so the SHO/Hubble look can be sculpted per channel instead of just re-tinted globally.

**Architecture:** Revise `core/palette.py` — `ChannelCurve`, a per-channel `apply_channel_curve` (reusing the levels math), and a revised `PaletteParams`/`render_nebula` (combine → per-channel curves → SCNR). Rebuild the `ui/palette_dialog.py` control panel to channel tabs (R/G/B) + Black/Mid/White sliders + Reset. StarX-once workflow, preview, history, and RC-Astro fallback are unchanged from v2.

**Tech Stack:** Python 3.11+, numpy, PySide6.

## Global Constraints

- Package is `seestar_processor` (do NOT rename). Use the venv (`.venv/bin/python`, `.venv/bin/pytest`); system python is 3.9 and fails.
- UI tests run headless: prefix with `QT_QPA_PLATFORM=offscreen`.
- `core/` stays Qt-free.
- This EVOLVES the just-merged palette v2. Remove v2's `balance`/`saturation` from `PaletteParams` and `_saturate_rgb`; keep `neutralize_stars`, `screen`, `compose`, `extract_channels`, `hoo`, `pseudo_sho`, `apply_palette`, `subtract_background`.
- Curves are neutral by default (black 0, mid 0.5, white 1) — a no-op, so opening the dialog shows the plain palette combination.
- Mid→gamma mapping: `gamma = 10 ** ((mid - 0.5) * 2)`.
- The dialog signature `PaletteDialog(settings, base, parent=None, on_apply=None)` and MainWindow's `_open_palette`/`_record_palette` are UNCHANGED — do not touch `main_window.py`.
- Commit after each task. Create the `palette-v3` branch first (do not start on `main`).

---

## File Structure

- `seestar_processor/core/palette.py` — replace `PaletteParams`; add `ChannelCurve`, `apply_channel_curve`; rewrite `render_nebula`; delete `_saturate_rgb`.
- `seestar_processor/ui/palette_dialog.py` — replace the control panel (channel tabs + Black/Mid/White + Reset); keep StarX/preview/apply.
- Tests: `tests/core/test_palette.py` (replace the balance/saturation render tests), `tests/ui/test_palette_dialog.py` (update slider references).

---

## Task 0: Branch setup

- [ ] **Step 1: Create the feature branch**

```bash
cd /Volumes/Work/Code/Editor
git checkout -b palette-v3
git status   # expect: On branch palette-v3, clean
```

---

## Task 1: `core/palette.py` — per-channel curves

**Files:**
- Modify: `seestar_processor/core/palette.py`
- Modify: `tests/core/test_palette.py`

**Interfaces:**
- Consumes: existing `extract_channels`, `AstroImage`.
- Produces:
  - `@dataclass ChannelCurve(black=0.0, mid=0.5, white=1.0)`
  - `apply_channel_curve(channel: np.ndarray, curve: ChannelCurve) -> np.ndarray`
  - Revised `@dataclass PaletteParams(palette="HOO", r=ChannelCurve(), g=ChannelCurve(), b=ChannelCurve(), scnr=True)` (fields via `default_factory`)
  - Revised `render_nebula(starless: AstroImage, params: PaletteParams) -> AstroImage`
- Keeps: `neutralize_stars`, `screen`, `compose`, `extract_channels`, `hoo`, `pseudo_sho`, `apply_palette`, `subtract_background`.

- [ ] **Step 1: Update the tests (replace v2's balance/saturation render tests)**

In `tests/core/test_palette.py`, DELETE these three tests (they test removed controls):
`test_render_nebula_saturation_zero_is_grey`, `test_render_nebula_balance_shifts_ha_oiii`,
`test_render_nebula_scnr_reduces_green`.

Then add these tests:

```python
def test_apply_channel_curve_neutral_is_noop():
    from seestar_processor.core.palette import apply_channel_curve, ChannelCurve
    ch = np.array([[0.0, 0.25, 0.5, 0.75, 1.0]], np.float32)
    out = apply_channel_curve(ch, ChannelCurve())        # black 0, mid .5, white 1
    assert np.allclose(out, ch, atol=1e-6)


def test_apply_channel_curve_white_point_brightens():
    from seestar_processor.core.palette import apply_channel_curve, ChannelCurve
    ch = np.array([[0.5]], np.float32)
    out = apply_channel_curve(ch, ChannelCurve(white=0.5))  # pull white down -> brighter
    assert out[0, 0] > 0.5


def test_apply_channel_curve_black_point_darkens():
    from seestar_processor.core.palette import apply_channel_curve, ChannelCurve
    ch = np.array([[0.3]], np.float32)
    out = apply_channel_curve(ch, ChannelCurve(black=0.2))  # lift black -> darker lows
    assert out[0, 0] < 0.3


def test_apply_channel_curve_mid_gamma():
    from seestar_processor.core.palette import apply_channel_curve, ChannelCurve
    ch = np.array([[0.5]], np.float32)
    assert np.isclose(apply_channel_curve(ch, ChannelCurve(mid=0.5))[0, 0], 0.5, atol=1e-6)
    assert apply_channel_curve(ch, ChannelCurve(mid=0.8))[0, 0] > 0.5   # brighter mids
    assert apply_channel_curve(ch, ChannelCurve(mid=0.2))[0, 0] < 0.5   # darker mids


def test_render_nebula_neutral_curves_equals_plain_palette():
    from seestar_processor.core.palette import render_nebula, PaletteParams, hoo
    img = _img([(0.9, 0.2, 0.4), (0.3, 0.7, 0.6)])
    # neutral curves + scnr off == plain HOO combination
    out = render_nebula(img, PaletteParams(palette="HOO", scnr=False)).data
    plain = hoo(img).data
    assert np.allclose(out, plain, atol=1e-6)


def test_render_nebula_per_channel_independent():
    from seestar_processor.core.palette import render_nebula, PaletteParams, ChannelCurve
    img = _img([(0.8, 0.5, 0.5), (0.6, 0.5, 0.5)])
    base = render_nebula(img, PaletteParams(scnr=False)).data
    # pull RED white down -> red mean rises; green/blue unchanged
    tweaked = render_nebula(
        img, PaletteParams(r=ChannelCurve(white=0.5), scnr=False)).data
    assert tweaked[..., 0].mean() > base[..., 0].mean()
    assert np.allclose(tweaked[..., 1], base[..., 1], atol=1e-6)
    assert np.allclose(tweaked[..., 2], base[..., 2], atol=1e-6)


def test_render_nebula_scnr_reduces_green():
    from seestar_processor.core.palette import render_nebula, PaletteParams
    img = _img([(0.2, 0.9, 0.2)])
    with_scnr = render_nebula(img, PaletteParams(scnr=True)).data[0, 0]
    without = render_nebula(img, PaletteParams(scnr=False)).data[0, 0]
    assert with_scnr[1] <= without[1]
```

- [ ] **Step 2: Run it, expect failure**

Run: `.venv/bin/pytest tests/core/test_palette.py -q`
Expected: FAIL (`cannot import name 'ChannelCurve'` / `PaletteParams` has no `r`).

- [ ] **Step 3: Implement**

In `seestar_processor/core/palette.py`: ensure `from dataclasses import dataclass, field` at the top. REPLACE the existing `PaletteParams` dataclass and the `_saturate_rgb` + `render_nebula` block with:

```python
@dataclass
class ChannelCurve:
    black: float = 0.0    # 0..1 input black point
    mid: float = 0.5      # 0..1 slider; 0.5 = neutral gamma
    white: float = 1.0    # 0..1 input white point


@dataclass
class PaletteParams:
    palette: str = "HOO"                         # "HOO" | "pseudo_SHO"
    r: ChannelCurve = field(default_factory=ChannelCurve)
    g: ChannelCurve = field(default_factory=ChannelCurve)
    b: ChannelCurve = field(default_factory=ChannelCurve)
    scnr: bool = True                            # green suppression on the nebula


def apply_channel_curve(channel: np.ndarray, curve: ChannelCurve) -> np.ndarray:
    """Levels on a single 2D channel: remap [black, white] -> [0,1] then midtone
    gamma. Mirrors core/levels.apply_levels. gamma = 10**((mid-0.5)*2)."""
    black = float(curve.black)
    white = max(float(curve.white), black + 1e-4)
    gamma = 10.0 ** ((float(curve.mid) - 0.5) * 2.0)
    x = np.clip((channel - black) / (white - black), 0.0, 1.0)
    return np.power(x, 1.0 / gamma).astype(np.float32)


def render_nebula(starless: AstroImage, params: PaletteParams) -> AstroImage:
    """Extract Ha/OIII, combine into the chosen palette, sculpt each channel with
    its curve, then optional SCNR green suppression."""
    ha, oiii = extract_channels(starless)
    if params.palette == "pseudo_SHO":
        rgb = [ha, np.clip(0.5 * ha + 0.5 * oiii, 0.0, 1.0), oiii]
    else:  # HOO
        rgb = [ha, oiii, oiii]
    r = apply_channel_curve(rgb[0], params.r)
    g = apply_channel_curve(rgb[1], params.g)
    b = apply_channel_curve(rgb[2], params.b)
    out = np.stack([r, g, b], axis=2)
    if params.scnr:
        avg_rb = (out[..., 0] + out[..., 2]) / 2.0
        out[..., 1] = np.minimum(out[..., 1], avg_rb)
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=starless.is_linear, metadata=dict(starless.metadata))
```

Delete the old `_saturate_rgb` function if it is still present.

- [ ] **Step 4: Run tests, expect pass**

Run: `.venv/bin/pytest tests/core/test_palette.py -q`
Expected: PASS (kept v1/compose/neutralize/screen tests still pass).

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/core/palette.py tests/core/test_palette.py
git commit -m "feat: per-channel curves replace balance/saturation in palette core"
```

---

## Task 2: `ui/palette_dialog.py` — channel tabs + Black/Mid/White + Reset

**Files:**
- Modify: `seestar_processor/ui/palette_dialog.py`
- Modify: `tests/ui/test_palette_dialog.py`

**Interfaces:**
- Consumes: `core.palette.PaletteParams`, `ChannelCurve`, `render_nebula`, `compose`.
- Produces (dialog attributes): `hoo_radio`, `sho_radio`, `r_radio`, `g_radio`, `b_radio`,
  `black_slider`, `mid_slider`, `white_slider`, `scnr_check`, `reset_btn`, `preview`,
  `_curves` (dict "R"/"G"/"B" → ChannelCurve), `_active_channel` (str). Methods `_params()`,
  `_select_channel(name)`, `reset()`. StarX/preview/apply seams unchanged.

- [ ] **Step 1: Update the dialog tests**

In `tests/ui/test_palette_dialog.py`, the existing `test_slider_change_rerenders` uses
`dlg.sat_slider` which no longer exists. REPLACE that one test with the following two, and
add the reset test (keep the other tests — `test_dialog_runs_starx_and_renders`,
`test_apply_records_result`, `test_fallback_without_rcastro` — as they are):

```python
def test_channel_curve_change_rerenders(qtbot):
    dlg = PaletteDialog(Settings(), _color())
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg._starx_enabled = True
    dlg._starx_runner = _fake_starx
    dlg.start()
    before = dlg.preview.pixmap().cacheKey()
    dlg.white_slider.setValue(40)                     # move active channel's white point
    assert dlg.preview.pixmap().cacheKey() != before


def test_channel_tab_stores_and_repopulates(qtbot):
    dlg = PaletteDialog(Settings(), _color())
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg._starx_enabled = True
    dlg._starx_runner = _fake_starx
    dlg.start()
    dlg.r_radio.setChecked(True)                      # editing R
    dlg.white_slider.setValue(30)
    assert dlg._curves["R"].white == 0.30
    dlg.g_radio.setChecked(True)                      # switch to G
    assert dlg.white_slider.value() == 100            # G still neutral -> white 1.0
    dlg.r_radio.setChecked(True)                      # back to R
    assert dlg.white_slider.value() == 30             # R's stored value restored


def test_reset_returns_curves_to_neutral(qtbot):
    dlg = PaletteDialog(Settings(), _color())
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg._starx_enabled = True
    dlg._starx_runner = _fake_starx
    dlg.start()
    dlg.r_radio.setChecked(True)
    dlg.black_slider.setValue(40)
    dlg.reset()
    assert all(c.black == 0.0 and c.mid == 0.5 and c.white == 1.0
               for c in dlg._curves.values())
    assert dlg.black_slider.value() == 0
```

- [ ] **Step 2: Run it, expect failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_palette_dialog.py -q`
Expected: FAIL (`sho`/curve attributes changed; `r_radio`/`black_slider`/`reset` missing).

- [ ] **Step 3: Implement**

In `seestar_processor/ui/palette_dialog.py`, replace the control-panel construction and the
`_params`/`_render_preview` region. Specifically:

Update the imports line to include `ChannelCurve`:

```python
from ..core.palette import ChannelCurve, PaletteParams, compose, render_nebula
```

Replace the block that builds `self.hoo_radio ... self.scnr_check` and their signal
connections (the palette radios, balance/sat sliders, scnr) with:

```python
        self.hoo_radio = QRadioButton("HOO")
        self.sho_radio = QRadioButton("Pseudo-SHO (no real SII)")
        self.hoo_radio.setChecked(True)

        # per-channel curve state; sliders edit the active channel
        self._curves = {"R": ChannelCurve(), "G": ChannelCurve(), "B": ChannelCurve()}
        self._active_channel = "R"
        self.r_radio = QRadioButton("R")
        self.g_radio = QRadioButton("G")
        self.b_radio = QRadioButton("B")
        self.r_radio.setChecked(True)

        self.black_slider = self._slider()
        self.mid_slider = self._slider()
        self.white_slider = self._slider()
        # neutral curve = black 0 / mid 0.5 / white 1.0 (the _slider factory defaults
        # to 50, which is only correct for mid). Signals are connected later, so these
        # setValue calls do not fire _on_slider.
        self.black_slider.setValue(0)
        self.white_slider.setValue(100)

        self.scnr_check = QCheckBox("Green suppression (SCNR)")
        self.scnr_check.setChecked(True)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        for w in (self.hoo_radio, self.sho_radio):
            w.toggled.connect(self._render_preview)
        self.r_radio.toggled.connect(lambda on: on and self._select_channel("R"))
        self.g_radio.toggled.connect(lambda on: on and self._select_channel("G"))
        self.b_radio.toggled.connect(lambda on: on and self._select_channel("B"))
        for s in (self.black_slider, self.mid_slider, self.white_slider):
            s.valueChanged.connect(self._on_slider)
        self.scnr_check.toggled.connect(self._render_preview)
```

Replace the controls-layout block (the `QFormLayout` that added Palette / balance / sat /
scnr rows) with:

```python
        controls = QFormLayout()
        pal = QHBoxLayout()
        pal.addWidget(self.hoo_radio)
        pal.addWidget(self.sho_radio)
        pal_wrap = QWidget()
        pal_wrap.setLayout(pal)
        controls.addRow("Palette", pal_wrap)
        chan = QHBoxLayout()
        chan.addWidget(self.r_radio)
        chan.addWidget(self.g_radio)
        chan.addWidget(self.b_radio)
        chan_wrap = QWidget()
        chan_wrap.setLayout(chan)
        controls.addRow("Channel", chan_wrap)
        controls.addRow("Black", self.black_slider)
        controls.addRow("Mid", self.mid_slider)
        controls.addRow("White", self.white_slider)
        controls.addRow("", self.scnr_check)
        controls.addRow("", self.reset_btn)
```

Add these methods (replacing the old `_params`; keep `_slider`, `_result`, `_render_preview`,
`start`, StarX handlers, `apply`):

```python
    def _select_channel(self, name: str) -> None:
        self._active_channel = name
        c = self._curves[name]
        for slider, val in ((self.black_slider, c.black),
                            (self.mid_slider, c.mid), (self.white_slider, c.white)):
            slider.blockSignals(True)
            slider.setValue(round(val * 100))
            slider.blockSignals(False)
        self._render_preview()

    def _on_slider(self, _value: int) -> None:
        self._curves[self._active_channel] = ChannelCurve(
            black=self.black_slider.value() / 100.0,
            mid=self.mid_slider.value() / 100.0,
            white=self.white_slider.value() / 100.0,
        )
        self._render_preview()

    def reset(self) -> None:
        self._curves = {"R": ChannelCurve(), "G": ChannelCurve(), "B": ChannelCurve()}
        self._select_channel(self._active_channel)

    def _params(self) -> PaletteParams:
        return PaletteParams(
            palette="HOO" if self.hoo_radio.isChecked() else "pseudo_SHO",
            r=self._curves["R"], g=self._curves["G"], b=self._curves["B"],
            scnr=self.scnr_check.isChecked(),
        )
```

(If the old code referenced `self.balance_slider` / `self.sat_slider` anywhere else, remove
those references. `_result` and `_render_preview` already call `_params()`, so they need no
change.)

- [ ] **Step 4: Run tests, expect pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_palette_dialog.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/ui/palette_dialog.py tests/ui/test_palette_dialog.py
git commit -m "feat: palette dialog per-channel curve controls (R/G/B Black/Mid/White + Reset)"
```

---

## Task 3: Full suite + backlog note

**Files:**
- Modify: `TODO.md`

- [ ] **Step 1: Run the whole suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass. If `test_sharpen_changes_image_and_keeps_shape` fails, it's the known
pre-existing flake — rerun it alone to confirm it passes.

- [ ] **Step 2: Update the backlog**

In `TODO.md`, under the palette entry, append a sub-bullet:

```markdown
      - v3: per-channel Black/Mid/White curves (R/G/B) replace the global balance/saturation
        sliders, so the SHO look is sculpted per channel, not globally re-tinted.
```

- [ ] **Step 3: Commit**

```bash
git add TODO.md
git commit -m "docs: note palette v3 per-channel curves in backlog"
```

---

## Definition of Done

- All tasks committed on `palette-v3`; full suite green.
- Palette dialog shows palette radio + R/G/B channel tabs + Black/Mid/White sliders + SCNR +
  Reset; moving a slider changes only the active channel; switching channels preserves each
  channel's values; Reset restores the plain palette combination.
- After merge: validate on the real Pelican (IC 5070) master — sculpt per channel to a genuine
  gold/teal SHO look with white stars, confirming no global re-tint.
- Finish with **superpowers:finishing-a-development-branch**.
```
