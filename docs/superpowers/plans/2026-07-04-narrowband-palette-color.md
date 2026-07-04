# Narrowband Palette — Real Colour Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Palette tool produce genuine bicolour (gold/teal) narrowband images from Seestar duo-band LP masters instead of red-monochrome.

**Architecture:** Add pure narrowband-combine helpers to `core/palette.py` (per-channel background-subtract, OIII↔Ha normalization, independent per-channel stretch, Foraxx dynamic blend, hue rotation). Then switch `render_nebula`/`compose`/`PaletteParams` to the new pipeline and rebuild the Palette dialog's controls (drop R/G/B curves; add palette selector + Ha/OIII stretch + Hue + Saturation).

**Tech Stack:** Python 3.13 (`.venv`), NumPy, scikit-image (HSV), PySide6, pytest-qt (`QT_QPA_PLATFORM=offscreen`).

## Global Constraints

- Use `.venv/bin/python` / `.venv/bin/pytest`; system python is 3.9 and will fail. Qt tests: prefix `QT_QPA_PLATFORM=offscreen`.
- The combine order is fixed: extract → background-subtract each channel → normalize OIII to Ha → **stretch Ha and OIII independently** → palette blend → SCNR → hue → saturation → (screen stars).
- Foraxx blend: `p = Ha*OIII; w = p**(1-p); R = Ha; G = w*Ha + (1-w)*OIII; B = OIII`.
- SCNR is max-mask: `G = min(G, max(R, B))`.
- `render_nebula` output is **stretched** → `is_linear=False`.
- Palette selector values: `"Foraxx"` (default) | `"HOO"` | `"pseudo_SHO"`.
- New dialog sliders are `ResetSlider` (0–100 ints): Ha stretch default 60, OIII stretch default 70, Hue default 50 (→0°, maps `(v-50)/50*30` to ±30°), Saturation default 65. Keep SCNR checkbox + Reset button.
- Reuse existing primitives: `autostretch.linked_stretch`, `stretch.amount_to_target`, `saturation.saturate` (amount 0.5 = neutral), `autostretch.autostretch`.
- Commit co-author trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Known flake: `test_sharpen_changes_image_and_keeps_shape` — rerun alone if it trips.

---

### Task 1: Pure narrowband-combine helpers (additive)

**Files:**
- Modify: `seestar_processor/core/palette.py` (add functions + imports; touch nothing else)
- Test: `tests/core/test_palette.py` (add tests)

**Interfaces:**
- Produces: `subtract_bg_2d(channel, percentile=50.0)->ndarray`; `renorm_oiii(ha, oiii)->ndarray`; `stretch_channel(channel, amount)->ndarray`; `foraxx(ha, oiii)->(r,g,b)`; `rotate_hue(rgb, degrees)->ndarray`.

- [ ] **Step 1: Write the failing helper tests**

Add to `tests/core/test_palette.py`:

```python
def test_subtract_bg_2d_drops_pedestal():
    from seestar_processor.core.palette import subtract_bg_2d
    ch = np.full((8, 8), 0.5, dtype=np.float32)
    ch[0, 0] = 0.9
    out = subtract_bg_2d(ch)                 # median 0.5 subtracted
    assert out.min() == 0.0
    assert out[0, 0] == pytest.approx(0.4, abs=1e-6)


def test_renorm_oiii_matches_median_and_mad():
    from seestar_processor.core.palette import renorm_oiii, _mad
    rng = np.random.default_rng(0)
    ha = rng.random((32, 32)).astype(np.float32)
    oiii = (rng.random((32, 32)) * 0.1 + 0.02).astype(np.float32)   # much fainter
    out = renorm_oiii(ha, oiii)
    assert np.median(out) == pytest.approx(np.median(ha), abs=0.05)
    assert _mad(out) == pytest.approx(_mad(ha), abs=0.05)


def test_stretch_channel_lifts_faint_channel():
    from seestar_processor.core.palette import stretch_channel
    faint = np.full((16, 16), 0.05, dtype=np.float32)
    faint[0, 0] = 0.2
    out = stretch_channel(faint, 0.7)
    assert float(np.median(out)) > 0.05        # background lifted well above input


def test_foraxx_hues_by_region():
    from seestar_processor.core.palette import foraxx
    ha = np.array([[0.9, 0.1, 0.9]], dtype=np.float32)   # Ha-only, OIII-only, gold
    oiii = np.array([[0.1, 0.9, 0.4]], dtype=np.float32)
    r, g, b = foraxx(ha, oiii)
    assert r[0, 0] > g[0, 0] and r[0, 0] > b[0, 0]       # Ha-only -> red
    assert b[0, 1] > r[0, 1]                             # OIII-only -> blue/teal
    assert r[0, 2] > g[0, 2] > b[0, 2]                   # gold: R>G>B


def test_rotate_hue_shifts_red_toward_green():
    from seestar_processor.core.palette import rotate_hue
    red = np.zeros((1, 1, 3), dtype=np.float32); red[0, 0, 0] = 1.0
    same = rotate_hue(red, 0.0)
    assert np.allclose(same, red, atol=1e-6)             # 0 deg = identity
    rotated = rotate_hue(red, 120.0)                     # +120 deg -> green
    assert rotated[0, 0, 1] > rotated[0, 0, 0] and rotated[0, 0, 1] > rotated[0, 0, 2]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/core/test_palette.py -q -k "subtract_bg_2d or renorm_oiii or stretch_channel or foraxx or rotate_hue"`
Expected: FAIL with `ImportError`/`cannot import name`.

- [ ] **Step 3: Add the helpers and imports**

In `seestar_processor/core/palette.py`, add these imports near the top (after `from .image import AstroImage`):

```python
from .autostretch import autostretch, linked_stretch
from .saturation import saturate
from .stretch import amount_to_target
```

Add the functions (place them after `pseudo_sho`, before `_PALETTE_FNS`):

```python
def subtract_bg_2d(channel: np.ndarray, percentile: float = 50.0) -> np.ndarray:
    """Drop a 2D channel's sky pedestal to ~0 (subtract a low/median percentile)."""
    bg = float(np.percentile(channel, percentile))
    return np.clip(channel.astype(np.float32) - bg, 0.0, 1.0)


def _mad(x: np.ndarray) -> float:
    return float(np.median(np.abs(x - np.median(x))))


def renorm_oiii(ha: np.ndarray, oiii: np.ndarray) -> np.ndarray:
    """Match OIII to Ha (median + MAD) so the faint channel isn't steamrolled
    (Siril ExtractHaOIII normalization)."""
    mad_o = _mad(oiii)
    a = (_mad(ha) / mad_o) if mad_o > 1e-9 else 1.0
    out = a * (oiii - np.median(oiii)) + np.median(ha)
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def stretch_channel(channel: np.ndarray, amount: float) -> np.ndarray:
    """Independent nonlinear stretch of one 2D channel. `amount` in [0, 1]."""
    return linked_stretch(channel.astype(np.float32),
                          amount_to_target(amount)).astype(np.float32)


def foraxx(ha: np.ndarray, oiii: np.ndarray):
    """Foraxx dynamic HOO blend: Ha+OIII overlap -> gold, OIII-only -> teal,
    Ha-only -> red. Returns (r, g, b) 2D float32."""
    p = np.clip(ha * oiii, 0.0, 1.0)
    w = np.power(p, 1.0 - p).astype(np.float32)
    r = ha.astype(np.float32)
    g = (w * ha + (1.0 - w) * oiii).astype(np.float32)
    b = oiii.astype(np.float32)
    return r, g, b


def rotate_hue(rgb: np.ndarray, degrees: float) -> np.ndarray:
    """Rotate overall hue by `degrees` (via HSV). 0 = identity."""
    if abs(degrees) < 1e-6:
        return np.clip(rgb, 0.0, 1.0).astype(np.float32)
    from skimage.color import hsv2rgb, rgb2hsv
    hsv = rgb2hsv(np.clip(rgb, 0.0, 1.0))
    hsv[..., 0] = np.mod(hsv[..., 0] + degrees / 360.0, 1.0)
    return np.clip(hsv2rgb(hsv), 0.0, 1.0).astype(np.float32)
```

- [ ] **Step 4: Run to verify they pass (and nothing else broke)**

Run: `.venv/bin/pytest tests/core/test_palette.py -q`
Expected: PASS (new + all existing palette tests still green — Task 1 is additive).

- [ ] **Step 5: Commit**

```bash
git add seestar_processor/core/palette.py tests/core/test_palette.py
git commit -m "feat: narrowband combine helpers (bg-subtract, renorm, stretch, foraxx, hue)"
```

---

### Task 2: Switch Palette to the new combine + rebuild the dialog

Core and UI change together because they share the `PaletteParams` contract; splitting would leave the suite red at the boundary.

**Files:**
- Modify: `seestar_processor/core/palette.py` (`PaletteParams`, `render_nebula`, `neutralize_stars`, `_PALETTE_FNS`/`PALETTES`; remove `ChannelCurve`/`apply_channel_curve`)
- Modify: `seestar_processor/ui/palette_dialog.py` (controls rework)
- Test: `tests/core/test_palette.py`, `tests/ui/test_palette_dialog.py`

**Interfaces:**
- Consumes: the Task 1 helpers.
- Produces: `PaletteParams(palette="Foraxx", ha_stretch=0.6, oiii_stretch=0.7, hue_deg=0.0, saturation=0.65, scnr=True)`; `render_nebula(starless, params) -> AstroImage(is_linear=False)`; dialog attrs `foraxx_radio`/`hoo_radio`/`sho_radio`, `ha_slider`/`oiii_slider`/`hue_slider`/`sat_slider`, `scnr_check`, `reset_btn`, `hint`.

- [ ] **Step 1: Write/adjust the failing core tests**

In `tests/core/test_palette.py`:

(a) **Delete** these obsolete tests (curves are gone): `test_apply_channel_curve_neutral_is_noop`, `test_apply_channel_curve_white_point_brightens`, `test_apply_channel_curve_black_point_darkens`, `test_apply_channel_curve_mid_gamma`, `test_render_nebula_neutral_curves_equals_plain_palette`, `test_render_nebula_per_channel_independent`.

(a2) **Update** `test_apply_palette_dispatch_and_unknown` — its `assert set(PALETTES) == {"HOO", "pseudo_SHO"}` line must become `assert set(PALETTES) == {"Foraxx", "HOO", "pseudo_SHO"}` (Foraxx is added to the dispatch), and add `assert apply_palette(img, "Foraxx").data.shape == img.data.shape`. The `pytest.raises(ValueError)` for `"SHO"` stays.

(b) **Replace** `test_render_nebula_scnr_reduces_green` and `test_compose_screens_stars_back` and **add** new tests:

```python
def test_palette_params_defaults():
    from seestar_processor.core.palette import PaletteParams
    p = PaletteParams()
    assert p.palette == "Foraxx"
    assert p.ha_stretch == 0.6 and p.oiii_stretch == 0.7
    assert p.hue_deg == 0.0 and p.saturation == 0.65 and p.scnr is True


def _bicolour_starless():
    # left half Ha-strong (red), right half OIII-strong (green+blue)
    import numpy as np
    from seestar_processor.core.image import AstroImage
    d = np.zeros((20, 20, 3), dtype=np.float32)
    d[:, :10, 0] = 0.6                       # Ha (red) left
    d[:, 10:, 1] = 0.6; d[:, 10:, 2] = 0.6   # OIII (g+b) right
    d += 0.02                                # faint pedestal
    return AstroImage(d, is_linear=True)


def test_render_nebula_is_not_monochrome():
    from seestar_processor.core.palette import render_nebula, PaletteParams
    out = render_nebula(_bicolour_starless(), PaletteParams(scnr=False, hue_deg=0.0)).data
    left, right = out[:, :10], out[:, 10:]
    assert left[..., 0].mean() > left[..., 2].mean()      # left leans red
    assert right[..., 2].mean() > right[..., 0].mean()    # right leans blue/teal
    spread = (out.max(axis=2) - out.min(axis=2)).mean()
    assert spread > 0.05                                  # real chroma, not grey


def test_render_nebula_output_is_stretched():
    from seestar_processor.core.palette import render_nebula, PaletteParams
    out = render_nebula(_bicolour_starless(), PaletteParams())
    assert out.is_linear is False


def test_render_nebula_hoo_greenblue_equal():
    import numpy as np
    from seestar_processor.core.palette import render_nebula, PaletteParams
    out = render_nebula(_bicolour_starless(),
                        PaletteParams(palette="HOO", scnr=False, hue_deg=0.0,
                                      saturation=0.5)).data
    assert np.allclose(out[..., 1], out[..., 2], atol=1e-5)   # HOO: G == B


def test_render_nebula_scnr_reduces_green():
    from seestar_processor.core.palette import render_nebula, PaletteParams
    common = dict(palette="HOO", hue_deg=0.0, saturation=0.5)
    on = render_nebula(_bicolour_starless(), PaletteParams(scnr=True, **common)).data
    off = render_nebula(_bicolour_starless(), PaletteParams(scnr=False, **common)).data
    assert on[..., 1].sum() <= off[..., 1].sum() + 1e-6      # green not increased


def test_compose_screens_stars_back():
    import numpy as np
    from seestar_processor.core.image import AstroImage
    from seestar_processor.core.palette import compose, render_nebula, PaletteParams
    starless = _bicolour_starless()
    stars = AstroImage(np.zeros((20, 20, 3), np.float32), is_linear=True)
    stars.data[5, 5] = 0.9                                   # one bright star
    params = PaletteParams()
    out = compose(starless, stars, params).data
    nebula = render_nebula(starless, params).data
    assert out[5, 5].mean() >= nebula[5, 5].mean()          # star brightened the pixel
```

- [ ] **Step 2: Run to verify the core tests fail**

Run: `.venv/bin/pytest tests/core/test_palette.py -q`
Expected: FAIL — new fields/behaviour not implemented yet (and the deleted tests are gone).

- [ ] **Step 3: Rework `core/palette.py`**

Replace `PaletteParams` (and delete `ChannelCurve` + `apply_channel_curve`):

```python
@dataclass
class PaletteParams:
    palette: str = "Foraxx"        # "Foraxx" | "HOO" | "pseudo_SHO"
    ha_stretch: float = 0.6        # [0,1] Ha channel stretch aggressiveness
    oiii_stretch: float = 0.7      # [0,1] OIII channel stretch (a touch stronger)
    hue_deg: float = 0.0           # global hue rotation, degrees
    saturation: float = 0.65       # saturate() amount; 0.5 = neutral
    scnr: bool = True              # green suppression
```

Add `"Foraxx"` to the dispatch:

```python
PALETTES = ("Foraxx", "HOO", "pseudo_SHO")
```
and update `_PALETTE_FNS`:
```python
def _foraxx_image(img: AstroImage) -> AstroImage:
    ha, oiii = extract_channels(img)
    return _image_like(foraxx(ha, oiii), img)


_PALETTE_FNS = {"Foraxx": _foraxx_image, "HOO": hoo, "pseudo_SHO": pseudo_sho}
```

Replace `render_nebula`:

```python
def render_nebula(starless: AstroImage, params: PaletteParams) -> AstroImage:
    """Full narrowband combine: extract Ha/OIII, background-subtract, normalize,
    stretch each channel independently, blend, SCNR, hue + saturation."""
    ha, oiii = extract_channels(starless)
    ha = subtract_bg_2d(ha)
    oiii = subtract_bg_2d(oiii)
    oiii = renorm_oiii(ha, oiii)
    ha = stretch_channel(ha, params.ha_stretch)
    oiii = stretch_channel(oiii, params.oiii_stretch)
    if params.palette == "HOO":
        r, g, b = ha, oiii, oiii
    elif params.palette == "pseudo_SHO":
        r, g, b = ha, np.clip(0.5 * ha + 0.5 * oiii, 0.0, 1.0), oiii
    else:  # Foraxx
        r, g, b = foraxx(ha, oiii)
    out = np.stack([r, g, b], axis=2).astype(np.float32)
    if params.scnr:
        cap = np.maximum(out[..., 0], out[..., 2])          # max-mask SCNR
        out[..., 1] = np.minimum(out[..., 1], cap)
    out = rotate_hue(out, params.hue_deg)
    out = saturate(AstroImage(out, is_linear=False), params.saturation).data
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=False, metadata=dict(starless.metadata))
```

Replace `neutralize_stars` so stars survive on the stretched nebula:

```python
def neutralize_stars(stars: AstroImage) -> AstroImage:
    """White (colour-neutral) star layer, auto-stretched so stars stay visible
    over the stretched nebula."""
    if not stars.is_color:
        return stars.copy()
    lum = autostretch(AstroImage(stars.data.mean(axis=2)))
    rgb = np.clip(np.stack([lum, lum, lum], axis=2), 0.0, 1.0).astype(np.float32)
    return AstroImage(rgb, is_linear=False, metadata=dict(stars.metadata))
```

(`compose` and `screen` are unchanged. Remove the now-unused `field` import only if nothing else uses it — `PaletteParams` no longer needs `field(default_factory=...)`; keep `dataclass`.)

- [ ] **Step 4: Run the core tests**

Run: `.venv/bin/pytest tests/core/test_palette.py -q`
Expected: PASS. (The `test_apply_palette_dispatch_and_unknown` test still passes — `apply_palette("Foraxx", img)` now dispatches; unknown still raises. If that test hard-codes only HOO/pseudo_SHO, it still passes since those keys remain.)

- [ ] **Step 5: Write/adjust the failing dialog tests**

In `tests/ui/test_palette_dialog.py`:

(a) **Delete** `test_channel_tab_stores_and_repopulates` and `test_reset_returns_curves_to_neutral` (channel tabs/curves removed).

(b) **Replace** `test_channel_curve_change_rerenders`, `test_palette_sliders_are_reset_sliders`, `test_palette_slider_double_click_resets` with:

```python
def test_slider_change_rerenders(qtbot):
    dlg = PaletteDialog(Settings(), _color())
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg._starx_enabled = True
    dlg._starx_runner = _fake_starx
    dlg.start()
    before = dlg.preview.pixmap().cacheKey()
    dlg.oiii_slider.setValue(90)
    assert dlg.preview.pixmap().cacheKey() != before


def test_new_controls_present_and_no_old_curves(qtbot):
    from seestar_processor.ui.reset_slider import ResetSlider
    dlg = _make_dialog(qtbot)
    assert isinstance(dlg.ha_slider, ResetSlider) and dlg.ha_slider._default == 60
    assert isinstance(dlg.oiii_slider, ResetSlider) and dlg.oiii_slider._default == 70
    assert isinstance(dlg.hue_slider, ResetSlider) and dlg.hue_slider._default == 50
    assert isinstance(dlg.sat_slider, ResetSlider) and dlg.sat_slider._default == 65
    assert dlg.foraxx_radio.isChecked()                       # Foraxx default
    assert not hasattr(dlg, "black_slider") and not hasattr(dlg, "r_radio")


def test_params_reflect_sliders(qtbot):
    dlg = _make_dialog(qtbot)
    dlg.oiii_slider.setValue(80)
    dlg.hue_slider.setValue(50)
    p = dlg._params()
    assert p.palette == "Foraxx"
    assert p.oiii_stretch == 0.80 and p.hue_deg == 0.0


def test_reset_returns_sliders_to_defaults(qtbot):
    dlg = _make_dialog(qtbot)
    dlg.ha_slider.setValue(20)
    dlg.reset()
    assert dlg.ha_slider.value() == 60 and dlg.oiii_slider.value() == 70


def test_linear_hint_shown_for_stretched_input(qtbot):
    # _color() builds an is_linear=False image -> hint should be visible
    dlg = _make_dialog(qtbot)
    assert "linear" in dlg.hint.text().lower()
```

Keep `test_dialog_runs_starx_and_renders`, `test_apply_records_result` (its `dlg.sho_radio.setChecked(True)` still valid), and `test_fallback_without_rcastro` unchanged.

- [ ] **Step 6: Run to verify the dialog tests fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_palette_dialog.py -q`
Expected: FAIL (new attrs/controls not present yet).

- [ ] **Step 7: Rebuild the dialog controls**

In `seestar_processor/ui/palette_dialog.py`:

Update the import line (drop `ChannelCurve`):
```python
from ..core.palette import PaletteParams, compose, render_nebula
```

Replace the control construction block (the `hoo_radio`/`sho_radio` + per-channel section, lines ~50–100) with:

```python
        self.foraxx_radio = QRadioButton("Foraxx (dynamic)")
        self.hoo_radio = QRadioButton("HOO")
        self.sho_radio = QRadioButton("Pseudo-SHO (no real SII)")
        self.foraxx_radio.setChecked(True)

        self.ha_slider = ResetSlider(60)
        self.oiii_slider = ResetSlider(70)
        self.hue_slider = ResetSlider(50)
        self.sat_slider = ResetSlider(65)

        self.scnr_check = QCheckBox("Green suppression (SCNR)")
        self.scnr_check.setChecked(True)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset)
        self.hint = QLabel(
            "" if self._base.is_linear else
            "Palette works best on the linear master — run it before the Stretch step.")
        self.hint.setWordWrap(True)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        for r in (self.foraxx_radio, self.hoo_radio, self.sho_radio):
            r.toggled.connect(self._render_preview)
        for s in (self.ha_slider, self.oiii_slider, self.hue_slider, self.sat_slider):
            s.valueChanged.connect(lambda _v: self._render_preview())
        self.scnr_check.toggled.connect(self._render_preview)

        controls = QFormLayout()
        pal = QHBoxLayout()
        pal.addWidget(self.foraxx_radio)
        pal.addWidget(self.hoo_radio)
        pal.addWidget(self.sho_radio)
        pal_wrap = QWidget()
        pal_wrap.setLayout(pal)
        controls.addRow("Palette", pal_wrap)
        controls.addRow("Ha stretch", self.ha_slider)
        controls.addRow("OIII stretch", self.oiii_slider)
        controls.addRow("Hue", self.hue_slider)
        controls.addRow("Saturation", self.sat_slider)
        controls.addRow("", self.scnr_check)
        controls.addRow("", self.reset_btn)
        controls.addRow("", self.hint)
```

Delete the `_slider` factory, `_select_channel`, `_on_slider`, and the `self._curves`/`self._active_channel` state. Replace `reset` and `_params`:

```python
    def reset(self) -> None:
        self.foraxx_radio.setChecked(True)
        self.ha_slider.setValue(60)
        self.oiii_slider.setValue(70)
        self.hue_slider.setValue(50)
        self.sat_slider.setValue(65)
        self.scnr_check.setChecked(True)
        self._render_preview()

    def _params(self) -> PaletteParams:
        if self.hoo_radio.isChecked():
            palette = "HOO"
        elif self.sho_radio.isChecked():
            palette = "pseudo_SHO"
        else:
            palette = "Foraxx"
        return PaletteParams(
            palette=palette,
            ha_stretch=self.ha_slider.value() / 100.0,
            oiii_stretch=self.oiii_slider.value() / 100.0,
            hue_deg=(self.hue_slider.value() - 50) / 50.0 * 30.0,
            saturation=self.sat_slider.value() / 100.0,
            scnr=self.scnr_check.isChecked(),
        )
```

Make sure `self.hint` is added to the side layout is handled by `controls.addRow("", self.hint)` above (no separate `side.addWidget` needed). Everything else (`start`, `_on_starless`, `_result`, `_render_preview`, `apply`, StarX) is unchanged.

- [ ] **Step 8: Run the dialog tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_palette_dialog.py -q`
Expected: PASS.

- [ ] **Step 9: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass (rerun the known sharpen flake alone if it trips).

- [ ] **Step 10: Commit**

```bash
git add seestar_processor/core/palette.py seestar_processor/ui/palette_dialog.py \
        tests/core/test_palette.py tests/ui/test_palette_dialog.py
git commit -m "feat: real narrowband colour palette (normalize + independent stretch + Foraxx + hue/sat)"
```

---

## Self-Review

- **Spec coverage:** helpers (T1); order-of-ops render, Foraxx default, independent stretch, hue/sat, SCNR max-mask, stretched output, stretched stars (T2 core); control rework + linear hint (T2 ui); tests incl. the not-monochrome regression guard — covered.
- **Placeholders:** none — complete code in every step.
- **Type consistency:** `PaletteParams(palette, ha_stretch, oiii_stretch, hue_deg, saturation, scnr)`, helper signatures, and dialog attrs (`foraxx_radio`/`ha_slider`/`oiii_slider`/`hue_slider`/`sat_slider`/`hint`) are used identically across core, dialog, and tests.
- **Green-at-boundary:** T1 is additive (suite stays green). T2 changes the shared `PaletteParams` contract in core AND ui together, so the suite is green only at T2's end — the reason they're one task.
- **Reuse:** `linked_stretch`, `amount_to_target`, `saturate`, `autostretch` reused; no reimplementation.
