# Narrowband Colour Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a guided "Narrowband…" colour tool that recolours a stretched, starless dual-band (Ha+OIII) image with a corrected NarrowbandNormalization engine, and is captured by recipes/batch.

**Architecture:** A pure-numpy engine (`core/narrowband.py`, salvaged from the stale `narrowband-core` branch and corrected against Blanshan/Cranfield V8) does MTF median-matching of OIII up to Ha, palette routing, SCNR, tone stages, lightness/background handling. A toolbar dialog (`ui/narrowband_dialog.py`) drives it live on the starless nebula and screens stars back on Apply. A first-class `NarrowbandStep` (params-serialisable) makes it replay in recipes/batch — following the existing **Saturation** pattern (precomputed result for instant display + a serialisable option for recipe replay).

**Tech Stack:** Python, numpy, scikit-image (Lab), PySide6, pytest/pytest-qt. RC-Astro StarXTerminator via `tools/rcastro.RCAstro.remove_stars` (optional; whole-image fallback).

## Global Constraints

- **Never merge `narrowband-core`.** It is a stale reference (125 commits behind `main`). Build clean on a fresh branch off `main`; salvage code by reading it, not merging.
- **Palettes: exactly three** — `"HOO"`, `"Pseudo-SHO"`, `"Pseudo-bicolor"`. Do NOT add HSO/HOS (HSO is identical to Pseudo-SHO once SII=Ha).
- **Engine correctness (verified vs V8):** each channel uses its OWN black point `M` (the `A_ref` fix); `adev` is deviation from the **median**; the SCNR green clamp `G = min((R+B)/2, G)` is restored (HOO and Pseudo-SHO only — Pseudo-bicolor's green is real OIII signal).
- **Data domain:** the tool operates on a **stretched** (`is_linear=False`) image and refuses a linear one, matching Star Spikes.
- **Stars:** StarX split when `rcastro_valid(settings)`, else whole-image with a visible note.
- **WYSIWYG:** the live-committed result and a recipe replay of the same params must match — both go through the same `render()` + `screen()` and StarX split.
- **Attribution:** credit "Bill Blanshan & Mike Cranfield (NarrowbandNormalization); numpy approach cross-checked against SetiAstroSuite (GPL-3.0, Franklin Marek)" in the `core/narrowband.py` module docstring and the Help topic.
- Keep the whole suite green; do not touch `stacking/haoiii.py`.

---

### Task 1: NBN engine — `core/narrowband.py`

**Files:**
- Create: `nocturne/core/narrowband.py`
- Test: `tests/core/test_narrowband.py`

**Interfaces:**
- Consumes: `nocturne.core.autostretch._mtf(m, x)`, `nocturne.core.saturation.saturate(img, amount)`, `nocturne.core.image.AstroImage` (has `.data`, `.is_color`, `.is_linear`, `.metadata`).
- Produces (used by Tasks 2 & 3):
  - `screen(base_ndarray, top_ndarray) -> ndarray`
  - `channel_level(c_ndarray, blackpoint: float) -> (M: float, E0: float)`
  - `normalize_to_reference(secondary, reference, blackpoint=1.0, boost=1.0) -> ndarray`
  - `extract_ha_oiii(img: AstroImage) -> (ha_2d, oiii_2d)` — raises `ValueError` on mono
  - `@dataclass NarrowbandParams` (fields below)
  - `PALETTES = ("HOO", "Pseudo-SHO", "Pseudo-bicolor")`
  - `render(img: AstroImage, params: NarrowbandParams) -> AstroImage` (`is_linear=False`) — raises `ValueError` on mono

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_narrowband.py`:

```python
import numpy as np
import pytest
from nocturne.core.image import AstroImage
from nocturne.core.narrowband import (
    NarrowbandParams, PALETTES, channel_level, extract_ha_oiii,
    normalize_to_reference, render, screen,
)


def _rgb(ha, oiii):
    """Build a colour AstroImage with R=Ha, G=B=OIII (the dual-band layout)."""
    data = np.stack([ha, oiii, oiii], axis=2).astype(np.float32)
    return AstroImage(np.clip(data, 0, 1), is_linear=False)


def test_channel_level_uses_median_black_point():
    c = np.array([0.1, 0.2, 0.2, 0.9], np.float32)   # min .1, median .2
    M, E0 = channel_level(c, blackpoint=1.0)
    assert abs(M - 0.2) < 1e-6                        # min + 1.0*(median-min) = median
    assert E0 > 0


def test_screen_is_symmetric_and_brightens():
    a = np.full((4, 4), 0.4, np.float32)
    b = np.full((4, 4), 0.5, np.float32)
    out = screen(a, b)
    assert np.allclose(out, screen(b, a))
    assert (out >= np.maximum(a, b) - 1e-6).all()


def test_extract_ha_oiii_splits_channels():
    ha = np.full((4, 4), 0.6, np.float32)
    oiii = np.full((4, 4), 0.2, np.float32)
    got_ha, got_oiii = extract_ha_oiii(_rgb(ha, oiii))
    assert np.allclose(got_ha, 0.6) and np.allclose(got_oiii, 0.2)


def test_extract_ha_oiii_rejects_mono():
    with pytest.raises(ValueError):
        extract_ha_oiii(AstroImage(np.zeros((4, 4), np.float32), is_linear=False))


def test_normalize_lifts_weak_oiii_toward_ha():
    rng = np.random.default_rng(0)
    ha = np.clip(0.40 + 0.05 * rng.standard_normal((64, 64)), 0, 1).astype(np.float32)
    oiii = np.clip(0.10 + 0.05 * rng.standard_normal((64, 64)), 0, 1).astype(np.float32)
    out = normalize_to_reference(oiii, ha, blackpoint=1.0, boost=1.0)
    assert np.isfinite(out).all()
    # OIII's median is lifted from ~0.10 up toward Ha's ~0.40
    assert np.median(out) > np.median(oiii) + 0.10


def test_normalize_uses_each_channels_own_black_point():
    # Ha and OIII have DIFFERENT backgrounds -> the per-channel M matters. With the
    # old bug (reference reusing the secondary's M) the match lands far off; the
    # corrected version brings OIII's median close to Ha's.
    rng = np.random.default_rng(1)
    ha = np.clip(0.50 + 0.03 * rng.standard_normal((80, 80)), 0, 1).astype(np.float32)
    oiii = np.clip(0.08 + 0.03 * rng.standard_normal((80, 80)), 0, 1).astype(np.float32)
    out = normalize_to_reference(oiii, ha, blackpoint=1.0, boost=1.0)
    assert abs(np.median(out) - np.median(ha)) < 0.15


def test_oiii_boost_pushes_past_parity():
    rng = np.random.default_rng(2)
    ha = np.clip(0.40 + 0.04 * rng.standard_normal((64, 64)), 0, 1).astype(np.float32)
    oiii = np.clip(0.12 + 0.04 * rng.standard_normal((64, 64)), 0, 1).astype(np.float32)
    base = normalize_to_reference(oiii, ha, boost=1.0)
    boosted = normalize_to_reference(oiii, ha, boost=1.6)
    assert np.median(boosted) > np.median(base)


def test_normalize_degenerate_channel_is_identity_no_nan():
    flat = np.full((16, 16), 0.3, np.float32)
    out = normalize_to_reference(flat, flat, boost=1.0)
    assert np.isfinite(out).all()
    assert np.allclose(out, flat, atol=1e-3)


def test_render_hoo_makes_oiii_regions_bluer():
    # A frame with an OIII-strong patch should gain blue there after HOO render.
    ha = np.full((32, 32), 0.5, np.float32)
    oiii = np.full((32, 32), 0.1, np.float32)
    oiii[8:24, 8:24] = 0.6                           # oxygen-rich patch
    out = render(_rgb(ha, oiii), NarrowbandParams(palette="HOO", protect_background=0.0,
                                                  lightness_preserve=False))
    patch = out.data[16, 16]
    corner = out.data[0, 0]
    assert patch[2] > corner[2]                      # more blue in the OIII patch


def test_render_scnr_suppresses_green_in_hoo():
    rng = np.random.default_rng(3)
    ha = np.clip(0.5 + 0.03 * rng.standard_normal((48, 48)), 0, 1).astype(np.float32)
    oiii = np.clip(0.2 + 0.03 * rng.standard_normal((48, 48)), 0, 1).astype(np.float32)
    img = _rgb(ha, oiii)
    on = render(img, NarrowbandParams(palette="HOO", scnr=True, protect_background=0.0,
                                      lightness_preserve=False)).data
    off = render(img, NarrowbandParams(palette="HOO", scnr=False, protect_background=0.0,
                                       lightness_preserve=False)).data
    assert on[..., 1].mean() <= off[..., 1].mean() + 1e-6   # green not increased by SCNR


def test_render_all_palettes_run_and_are_colour():
    ha = np.full((16, 16), 0.5, np.float32)
    oiii = np.full((16, 16), 0.25, np.float32)
    for pal in PALETTES:
        out = render(_rgb(ha, oiii), NarrowbandParams(palette=pal))
        assert out.data.shape == (16, 16, 3)
        assert out.is_linear is False
        assert np.isfinite(out.data).all()


def test_render_rejects_mono():
    with pytest.raises(ValueError):
        render(AstroImage(np.zeros((8, 8), np.float32), is_linear=False), NarrowbandParams())


def test_protect_background_leaves_dark_sky_closer_to_original():
    ha = np.full((32, 32), 0.05, np.float32)         # dark sky
    oiii = np.full((32, 32), 0.02, np.float32)
    ha[12:20, 12:20] = 0.7                            # bright nebula
    oiii[12:20, 12:20] = 0.5
    img = _rgb(ha, oiii)
    protected = render(img, NarrowbandParams(palette="HOO", protect_background=0.8,
                                             lightness_preserve=False)).data
    whole = render(img, NarrowbandParams(palette="HOO", protect_background=0.0,
                                         lightness_preserve=False)).data
    # dark corner stays closer to the original with protection on
    orig_corner = img.data[0, 0]
    assert np.abs(protected[0, 0] - orig_corner).sum() < np.abs(whole[0, 0] - orig_corner).sum()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/core/test_narrowband.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nocturne.core.narrowband'`.

- [ ] **Step 3: Implement the engine**

Create `nocturne/core/narrowband.py`:

```python
"""Narrowband (Hubble-palette) recolour for dual-band Ha+OIII data.

NarrowbandNormalization: statistically lift the weak OIII channel up to the Ha
reference with a midtones-transfer-function (MTF) median match, then combine and
tame green. Concept & SHO/HOO formulas by Bill Blanshan & Mike Cranfield
(PixInsight NarrowbandNormalization); the numpy approach was cross-checked
against SetiAstroSuite (GPL-3.0, Franklin Marek). Operates on a stretched
(display-space) image.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .autostretch import _mtf
from .image import AstroImage
from .saturation import saturate


def screen(base: np.ndarray, top: np.ndarray) -> np.ndarray:
    """Screen blend 1-(1-base)*(1-top) — used to composite stars back on top."""
    base = np.clip(base, 0.0, 1.0)
    top = np.clip(top, 0.0, 1.0)
    return np.clip(1.0 - (1.0 - base) * (1.0 - top), 0.0, 1.0).astype(np.float32)


def channel_level(c: np.ndarray, blackpoint: float) -> tuple[float, float]:
    """NBN per-channel black point M and robust signal level E0.
    M = min + blackpoint*(median-min); E0 = adev/1.2533 + mean - M, where adev is
    the average absolute deviation from the MEDIAN (PixInsight adev semantics)."""
    c = np.asarray(c, dtype=np.float32)
    lo = float(c.min())
    med = float(np.median(c))
    mean = float(c.mean())
    M = lo + float(blackpoint) * (med - lo)
    adev = float(np.mean(np.abs(c - med)))           # deviation from the MEDIAN
    E0 = adev / 1.2533 + mean - M
    return M, E0


def normalize_to_reference(secondary: np.ndarray, reference: np.ndarray,
                           blackpoint: float = 1.0, boost: float = 1.0) -> np.ndarray:
    """MTF-match the secondary channel's robust level to the reference's, each
    channel using ITS OWN black point. Degenerate inputs fall back to identity."""
    sec = np.clip(np.asarray(secondary, dtype=np.float32), 0.0, 1.0)
    ref = np.clip(np.asarray(reference, dtype=np.float32), 0.0, 1.0)
    M_sec, E0_sec = channel_level(sec, blackpoint)
    M_ref, E0_ref = channel_level(ref, blackpoint)
    if 1.0 - M_sec <= 1e-6 or 1.0 - M_ref <= 1e-6:
        return sec
    A_sec = E0_sec / (1.0 - M_sec)
    A_ref = E0_ref / (1.0 - M_ref)
    denom = A_sec - 2.0 * A_sec * A_ref + A_ref
    if abs(denom) < 1e-6 or A_sec <= 1e-6 or A_ref <= 1e-6:
        return sec
    m = float(np.clip((A_sec * (1.0 - A_ref) / denom) / boost, 1e-3, 1.0 - 1e-3))
    e2 = np.clip((sec - M_sec) / max(1e-6, 1.0 - M_sec), 0.0, 1.0)   # rescale [M,1]
    stretched = _mtf(m, e2)
    sub = np.minimum(sec, M_sec)                                    # sub-blackpoint part
    out = 1.0 - (1.0 - stretched) * (1.0 - sub)                     # ~(~mtf * ~sub)
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def extract_ha_oiii(img: AstroImage) -> tuple[np.ndarray, np.ndarray]:
    """Dual-band → pseudo-channels: Ha = red, OIII = (green+blue)/2. 2D float32."""
    if not img.is_color:
        raise ValueError("Narrowband needs a colour image")
    data = np.clip(img.data, 0.0, 1.0)
    ha = data[..., 0].astype(np.float32)
    oiii = ((data[..., 1] + data[..., 2]) / 2.0).astype(np.float32)
    return ha, oiii


def synthetic_green(ha: np.ndarray, oiii: np.ndarray, amount: float = 0.6) -> np.ndarray:
    """Blanshan/Foraxx dynamic green blend, mixed toward OIII by (1-amount)."""
    ha = np.clip(ha, 0.0, 1.0).astype(np.float32)
    oiii = np.clip(oiii, 0.0, 1.0).astype(np.float32)
    p = np.clip(ha * oiii, 0.0, 1.0)
    w = np.power(p, 1.0 - p).astype(np.float32)
    dynamic = w * ha + (1.0 - w) * oiii
    g = float(amount) * dynamic + (1.0 - float(amount)) * oiii
    return np.clip(g, 0.0, 1.0).astype(np.float32)


def highlight_reduction(x: np.ndarray, amount: float = 1.0) -> np.ndarray:
    """NBN E11. Identity at amount=1.0."""
    x = np.clip(np.asarray(x, dtype=np.float32), 0.0, 1.0)
    m = float(np.clip(1.0 - 0.5 / amount, 1e-3, 1.0 - 1e-3))
    return np.clip(_mtf(m, x) * x + x * (1.0 - x), 0.0, 1.0).astype(np.float32)


def brightness(x: np.ndarray, amount: float = 1.0) -> np.ndarray:
    """NBN E12. Identity at amount=1.0; >1 brighter."""
    x = np.clip(np.asarray(x, dtype=np.float32), 0.0, 1.0)
    m = float(np.clip(0.5 / amount, 1e-3, 1.0 - 1e-3))
    return np.clip(_mtf(m, x), 0.0, 1.0).astype(np.float32)


def highlight_recover(x: np.ndarray, amount: float = 1.0) -> np.ndarray:
    """NBN E13: rescale(x, 0, amount). Identity at amount=1.0."""
    x = np.clip(np.asarray(x, dtype=np.float32), 0.0, 1.0)
    return np.clip(x / max(1e-6, amount), 0.0, 1.0).astype(np.float32)


@dataclass
class NarrowbandParams:
    palette: str = "HOO"
    blackpoint: float = 1.0
    oiii_boost: float = 1.0
    blend_amount: float = 0.6
    highlight_reduction: float = 1.0
    brightness: float = 1.0
    highlight_recover: float = 1.0
    saturation: float = 0.5
    lightness_preserve: bool = True
    protect_background: float = 0.4
    scnr: bool = True


PALETTES = ("HOO", "Pseudo-SHO", "Pseudo-bicolor")


def _combine(ha: np.ndarray, oiii: np.ndarray, palette: str,
             blend_amount: float, scnr: bool = True):
    """Route (Ha, OIII) to (R, G, B) per palette. Dual-band has no real SII, so
    the pseudo palettes reuse Ha. SCNR (green clamp) applies where green is a
    Ha-derived blend (HOO, Pseudo-SHO); Pseudo-bicolor's green is real OIII."""
    if palette == "HOO":
        r, g, b = ha, synthetic_green(ha, oiii, blend_amount), oiii
        if scnr:
            g = np.minimum((r + b) / 2.0, g)
        return r, g, b
    if palette == "Pseudo-SHO":           # gold nebula (R=G=Ha), teal OIII
        r, g, b = ha, ha, oiii
        if scnr:
            g = np.minimum((r + b) / 2.0, g)
        return r, g, b
    if palette == "Pseudo-bicolor":       # magenta (R=B=Ha) / green (G=OIII)
        return ha, oiii, ha
    raise ValueError(f"unknown palette: {palette}")


def render_palette(img: AstroImage, params: NarrowbandParams) -> AstroImage:
    ha, oiii = extract_ha_oiii(img)
    oiii_n = normalize_to_reference(oiii, ha, params.blackpoint, params.oiii_boost)
    r, g, b = _combine(ha, oiii_n, params.palette, params.blend_amount, params.scnr)
    rgb = np.stack([r, g, b], axis=2).astype(np.float32)
    rgb = highlight_reduction(rgb, params.highlight_reduction)
    rgb = brightness(rgb, params.brightness)
    rgb = highlight_recover(rgb, params.highlight_recover)
    tinted = AstroImage(np.clip(rgb, 0.0, 1.0).astype(np.float32),
                        is_linear=False, metadata=dict(img.metadata))
    out = saturate(tinted, params.saturation)
    return AstroImage(np.clip(out.data, 0.0, 1.0).astype(np.float32),
                      is_linear=False, metadata=dict(img.metadata))


def preserve_lightness(recolored: np.ndarray, original: np.ndarray) -> np.ndarray:
    """Keep the ORIGINAL image's CIE-L* and take only colour (a*,b*) from the
    recolour, holding the tonal structure while remapping hue."""
    from skimage.color import lab2rgb, rgb2lab
    lab = rgb2lab(np.clip(recolored, 0.0, 1.0))
    lab[..., 0] = rgb2lab(np.clip(original, 0.0, 1.0))[..., 0]
    return np.clip(lab2rgb(lab), 0.0, 1.0).astype(np.float32)


def nebula_mask(rgb: np.ndarray, protect: float) -> np.ndarray:
    """Soft 0..1 mask isolating bright nebula from dark sky (luminance
    percentiles). protect in [0,1]: higher protects more background."""
    lum = np.clip(rgb, 0.0, 1.0).mean(axis=2).astype(np.float32)
    lo = float(np.percentile(lum, 25))
    hi = float(np.percentile(lum, 99.5))
    if hi - lo < 1e-4:
        return np.ones_like(lum)
    start = lo - 0.3 * (hi - lo) + float(protect) * (hi - lo) * 1.3
    width = max(1e-3, (hi - start) * 0.6)
    x = np.clip((lum - start) / width, 0.0, 1.0)
    return (x * x * (3.0 - 2.0 * x)).astype(np.float32)             # smoothstep


def render(img: AstroImage, params: NarrowbandParams) -> AstroImage:
    """Render the palette, preserve lightness, and optionally confine the
    recolour to the nebula. The single engine entry point the UI/step drive."""
    if not img.is_color:
        raise ValueError("Narrowband needs a colour image")
    original = np.clip(img.data, 0.0, 1.0)
    out = render_palette(img, params)
    if params.lightness_preserve:
        out = AstroImage(preserve_lightness(out.data, original),
                         is_linear=False, metadata=dict(img.metadata))
    if params.protect_background > 0:
        m = nebula_mask(original, params.protect_background)[..., None]
        blended = m * out.data + (1.0 - m) * original
        out = AstroImage(np.clip(blended, 0.0, 1.0).astype(np.float32),
                         is_linear=False, metadata=dict(img.metadata))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/core/test_narrowband.py -q`
Expected: PASS (13 tests).

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (existing count + 13).

- [ ] **Step 6: Commit**

```bash
git add nocturne/core/narrowband.py tests/core/test_narrowband.py
git commit -m "feat(narrowband): corrected NBN engine (per-channel black-point, SCNR, 3 palettes)"
```

---

### Task 2: First-class recipe-captured `NarrowbandStep`

**Files:**
- Create: `nocturne/steps/narrowband_step.py`
- Modify: `nocturne/steps/factory.py` (add a `narrowband` case)
- Modify: `nocturne/recipe.py` (register `Narrowband` + serialize/deserialize)
- Test: `tests/steps/test_narrowband_step.py`

**Interfaces:**
- Consumes: `nocturne.core.narrowband.{NarrowbandParams, render, screen}`; `nocturne.tools.rcastro.RCAstro.remove_stars(img, runner=...)`; `nocturne.settings.{rcastro_valid, resolve_binary}`.
- Produces (used by Task 4): `NarrowbandStep(rcastro_or_none)` with `name = "Narrowband"` and `apply(img, option) -> AstroImage`; `parse_narrowband_option(option) -> NarrowbandParams`. Recipe stage id is `"narrowband"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/steps/test_narrowband_step.py`:

```python
import numpy as np
import pytest
from nocturne.core.image import AstroImage
from nocturne.core.narrowband import NarrowbandParams, render
from nocturne.steps.narrowband_step import NarrowbandStep, parse_narrowband_option
from nocturne.recipe import serialize_option, deserialize_option, _NAME_TO_STAGE, uncaptured_step_names


def _img():
    ha = np.full((16, 16), 0.5, np.float32)
    oiii = np.full((16, 16), 0.2, np.float32)
    return AstroImage(np.stack([ha, oiii, oiii], axis=2), is_linear=False)


def test_parse_option_passthrough_dict_and_default():
    p = NarrowbandParams(palette="Pseudo-SHO", oiii_boost=1.4)
    assert parse_narrowband_option(p) is p
    d = parse_narrowband_option({"palette": "HOO", "oiii_boost": 1.2})
    assert d.palette == "HOO" and d.oiii_boost == 1.2
    assert parse_narrowband_option(None).palette == "HOO"


def test_step_without_rcastro_recolours_whole_image():
    out = NarrowbandStep(None).apply(_img(), NarrowbandParams(palette="HOO"))
    assert out.data.shape == (16, 16, 3)
    assert not np.allclose(out.data, _img().data)      # colour changed


def test_step_mono_raises():
    with pytest.raises(ValueError):
        NarrowbandStep(None).apply(AstroImage(np.zeros((8, 8), np.float32), is_linear=False),
                                   NarrowbandParams())


def test_step_with_rcastro_screens_stars_back():
    img = _img()
    starless = AstroImage(img.data * 0.5, is_linear=False)
    stars = AstroImage(np.zeros_like(img.data), is_linear=False)
    stars.data[4, 4] = [0.9, 0.9, 0.9]

    class FakeRC:
        def remove_stars(self, image, runner=None):
            return starless, stars

    out = NarrowbandStep(FakeRC()).apply(img, NarrowbandParams(palette="HOO"))
    # the star pixel is screened back -> brighter than the recoloured nebula there
    assert out.data[4, 4].max() > 0.5


def test_recipe_round_trip_matches_live(monkeypatch):
    # serialize -> deserialize -> apply must equal a direct apply of the same params
    params = NarrowbandParams(palette="Pseudo-SHO", oiii_boost=1.3, protect_background=0.2)
    live = NarrowbandStep(None).apply(_img(), params).data
    ser = serialize_option("narrowband", params)
    assert isinstance(ser, dict) and ser["palette"] == "Pseudo-SHO"
    back = deserialize_option("narrowband", ser)
    replay = NarrowbandStep(None).apply(_img(), back).data
    assert np.allclose(live, replay)


def test_narrowband_is_recipe_captured_not_uncaptured():
    assert _NAME_TO_STAGE["Narrowband"] == "narrowband"
    assert uncaptured_step_names([("Narrowband", NarrowbandParams())]) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/steps/test_narrowband_step.py -q`
Expected: FAIL — `ModuleNotFoundError: nocturne.steps.narrowband_step` and `KeyError: 'Narrowband'`.

- [ ] **Step 3: Implement the step**

Create `nocturne/steps/narrowband_step.py`:

```python
from __future__ import annotations

import numpy as np

from ..core.image import AstroImage
from ..core.narrowband import NarrowbandParams, render, screen
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro


def parse_narrowband_option(option) -> NarrowbandParams:
    """Accept a NarrowbandParams (live), a plain dict (recipe), or None (default)."""
    if isinstance(option, NarrowbandParams):
        return option
    if isinstance(option, dict):
        import dataclasses
        fields = {f.name for f in dataclasses.fields(NarrowbandParams)}
        return NarrowbandParams(**{k: v for k, v in option.items() if k in fields})
    return NarrowbandParams()


class NarrowbandStep(Step):
    name = "Narrowband"

    def __init__(self, rcastro: RCAstro | None) -> None:
        self._rc = rcastro                       # None -> whole-image (no StarX)
        self._runner = run_cli

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        if not img.is_color:
            raise ValueError("Narrowband needs a colour image")
        params = parse_narrowband_option(option)
        if self._rc is not None:
            starless, stars = self._rc.remove_stars(img, runner=self._runner)
        else:
            starless, stars = img, None
        nebula = render(starless, params)
        if stars is None:
            return nebula
        out = screen(nebula.data, np.clip(stars.data, 0.0, 1.0))
        return AstroImage(out, is_linear=False, metadata=dict(starless.metadata))
```

- [ ] **Step 4: Register in the factory**

In `nocturne/steps/factory.py`, add the import near the other step imports:

```python
from .narrowband_step import NarrowbandStep
```

and add this case immediately before `raise ValueError(stage_id)`:

```python
    if stage_id == "narrowband":
        rc = RCAstro(resolve_binary(settings.rcastro_path)) if rcastro_valid(settings) else None
        step = NarrowbandStep(rc)
        step._runner = rc_runner
        return step
```

- [ ] **Step 5: Register in recipe serialization**

In `nocturne/recipe.py`, after the geometry aliases, register the name→stage mapping:

```python
_NAME_TO_STAGE["Narrowband"] = "narrowband"   # tool step, not a stepper stage
```

In `serialize_option`, add before the final `return option`:

```python
    if stage_id == "narrowband":
        from .core.narrowband import NarrowbandParams
        p = option if isinstance(option, NarrowbandParams) else NarrowbandParams()
        return {
            "palette": p.palette, "blackpoint": p.blackpoint, "oiii_boost": p.oiii_boost,
            "blend_amount": p.blend_amount, "highlight_reduction": p.highlight_reduction,
            "brightness": p.brightness, "highlight_recover": p.highlight_recover,
            "saturation": p.saturation, "lightness_preserve": p.lightness_preserve,
            "protect_background": p.protect_background, "scnr": p.scnr,
        }
```

In `deserialize_option`, add before the final `return value`:

```python
    if stage_id == "narrowband":
        import dataclasses
        from .core.narrowband import NarrowbandParams
        fields = {f.name for f in dataclasses.fields(NarrowbandParams)}
        return NarrowbandParams(**{k: v for k, v in value.items() if k in fields})
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/steps/test_narrowband_step.py -q`
Expected: PASS (6 tests).

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add nocturne/steps/narrowband_step.py nocturne/steps/factory.py nocturne/recipe.py tests/steps/test_narrowband_step.py
git commit -m "feat(narrowband): recipe-captured NarrowbandStep (factory + serialize)"
```

---

### Task 3: Guided tool — `ui/narrowband_dialog.py`

**Files:**
- Create: `nocturne/ui/narrowband_dialog.py`
- Test: `tests/ui/test_narrowband_dialog.py`

**Interfaces:**
- Consumes: `nocturne.core.narrowband.{NarrowbandParams, render, screen}`; `nocturne.settings.{rcastro_valid, resolve_binary}`; `nocturne.tools.rcastro.RCAstro`; `nocturne.ui.{frame_preview.FramePreview, preview.to_qimage, reset_slider.ResetSlider, worker.run_async}`.
- Produces (used by Task 4): `NarrowbandDialog(settings, base, parent=None, on_apply=None, starless=None, stars=None)`; on Apply calls `on_apply(result_astroimage, params)`. Attributes for tests: `palette_box`, `oiii_slider`, `_params()`, `_do_render()`, `apply()`, `_on_starless(layers)`, `_starx_runner`.

- [ ] **Step 1: Write the failing tests**

Create `tests/ui/test_narrowband_dialog.py`:

```python
import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.core.image import AstroImage           # noqa: E402
from nocturne.settings import Settings               # noqa: E402
from nocturne.ui.narrowband_dialog import NarrowbandDialog, PALETTES  # noqa: E402


def _img():
    ha = np.full((40, 40), 0.5, np.float32)
    oiii = np.full((40, 40), 0.2, np.float32)
    oiii[10:30, 10:30] = 0.6
    return AstroImage(np.stack([ha, oiii, oiii], axis=2), is_linear=False)


def _dialog(qtbot, **kw):
    d = NarrowbandDialog(Settings(), _img(), **kw)
    qtbot.addWidget(d)
    return d


def test_palettes_are_the_three_expected():
    assert list(PALETTES) == ["HOO", "Pseudo-SHO", "Pseudo-bicolor"]


def test_dialog_builds_with_seeded_layers(qtbot):
    d = _dialog(qtbot, starless=_img(), stars=None)
    d._on_starless((d._base, None))          # simulate showEvent seeding
    d._do_render()
    assert d.preview.has_image()


def test_oiii_slider_changes_the_render(qtbot):
    d = _dialog(qtbot, starless=_img(), stars=None)
    d._on_starless((d._base, None))
    d.oiii_slider.setValue(50)
    d._do_render()
    low = d.preview_result().data.copy()
    d.oiii_slider.setValue(90)               # push OIII harder
    d._do_render()
    high = d.preview_result().data
    assert not np.allclose(low, high)


def test_apply_screens_stars_back_and_calls_on_apply(qtbot):
    got = []
    stars = AstroImage(np.zeros((40, 40, 3), np.float32), is_linear=False)
    stars.data[5, 5] = [0.95, 0.95, 0.95]
    d = _dialog(qtbot, starless=_img(), stars=stars, on_apply=lambda r, p: got.append((r, p)))
    d._on_starless((d._base, stars))
    d.apply()
    assert got and isinstance(got[0][0], AstroImage)
    assert got[0][0].data[5, 5].max() > 0.5          # star screened back
    assert got[0][1].palette == "HOO"                # params passed through
```

Note: the dialog must expose `preview_result()` returning the last rendered starless `AstroImage`, so the test can compare renders without scraping the canvas.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_narrowband_dialog.py -q`
Expected: FAIL — `ModuleNotFoundError: nocturne.ui.narrowband_dialog`.

- [ ] **Step 3: Implement the dialog**

Create `nocturne/ui/narrowband_dialog.py`. Adapt the salvaged branch dialog with these differences: import `screen` from `..core.narrowband` (not `..core.palette`); `PALETTES = ["HOO", "Pseudo-SHO", "Pseudo-bicolor"]`; `on_apply(result, params)` passes BOTH the image and the params; store the last render in `self._last` and expose `preview_result()`.

```python
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from ..core.image import AstroImage
from ..core.narrowband import NarrowbandParams, render, screen
from ..settings import rcastro_valid, resolve_binary
from ..tools.rcastro import RCAstro
from .frame_preview import FramePreview
from .preview import to_qimage
from .reset_slider import ResetSlider
from .worker import run_async

_PREVIEW_MAX = 640
_DEBOUNCE_MS = 90
PALETTES = ["HOO", "Pseudo-SHO", "Pseudo-bicolor"]


def _downscale(img: AstroImage) -> AstroImage:
    h, w = img.data.shape[:2]
    step = max(1, max(h, w) // _PREVIEW_MAX)
    return AstroImage(np.ascontiguousarray(img.data[::step, ::step]),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


class NarrowbandDialog(QDialog):
    """Interactive narrowband recolour with live preview. Applied to a STARLESS
    nebula so stars keep their natural colour: on open we split stars
    (StarXTerminator, or whole-image without it), the user tweaks the starless
    recolour live, and on Apply the stars are screened back."""

    def __init__(self, settings, base: AstroImage, parent=None, on_apply=None,
                 starless=None, stars=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Narrowband")
        self.resize(1100, 720)
        self._settings = settings
        self._base = base
        self._on_apply = on_apply
        self._pool = QThreadPool.globalInstance()
        self._starx_runner = self._default_starx
        self._starless = starless
        self._stars = stars
        self._prev_starless = None
        self._last = None                 # last rendered starless AstroImage (preview)
        self._fitted = False
        self._started = False

        self.preview = FramePreview()
        self.preview.setMinimumSize(460, 460)

        self.palette_box = QComboBox()
        self.palette_box.addItems(PALETTES)
        self.blend_slider = ResetSlider(60)
        self.oiii_slider = ResetSlider(50)
        self.sat_slider = ResetSlider(50)
        self.bright_slider = ResetSlider(50)
        self.protect_slider = ResetSlider(40)
        self.lightness_check = QCheckBox("Preserve lightness (keep tonal structure)")
        self.lightness_check.setChecked(True)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(_DEBOUNCE_MS)
        self._render_timer.timeout.connect(self._do_render)
        self.palette_box.currentTextChanged.connect(lambda _t: self._schedule_render())
        for s in (self.blend_slider, self.oiii_slider, self.sat_slider,
                  self.bright_slider, self.protect_slider):
            s.valueChanged.connect(lambda _v: self._schedule_render())
        self.lightness_check.toggled.connect(lambda _v: self._schedule_render())

        controls = QFormLayout()
        controls.addRow("Palette", self.palette_box)
        controls.addRow("OIII boost", self.oiii_slider)
        controls.addRow("Green blend", self.blend_slider)
        controls.addRow("Protect background", self.protect_slider)
        controls.addRow("Saturation", self.sat_slider)
        controls.addRow("Brightness", self.bright_slider)
        controls.addRow("", self.lightness_check)
        controls.addRow("", self.reset_btn)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self.apply)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.apply_btn)
        buttons.addWidget(close_btn)

        side = QVBoxLayout()
        side.addLayout(controls)
        side.addStretch(1)
        side.addWidget(self.status)
        side.addLayout(buttons)
        side_wrap = QWidget()
        side_wrap.setLayout(side)
        side_wrap.setMaximumWidth(340)

        body = QHBoxLayout(self)
        body.addWidget(self.preview, 1)
        body.addWidget(side_wrap)

    def _default_starx(self, img: AstroImage):
        rc = RCAstro(resolve_binary(self._settings.rcastro_path))
        return rc.remove_stars(img)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._started:
            return
        self._started = True
        if self._starless is not None:
            self._on_starless((self._starless, self._stars))
            return
        if not rcastro_valid(self._settings):
            self.status.setText("StarX not configured — narrowband applied to the whole "
                                "image (star colour may look off).")
            self._on_starless((self._base, None))
            return
        self.preview.show_message("Removing stars…\n(one-time, then tweak live)")
        self.apply_btn.setEnabled(False)
        run_async(self._pool, lambda: self._starx_runner(self._base),
                  self._on_starless, self._on_error)

    def _on_starless(self, layers) -> None:
        self._starless, self._stars = layers
        self._prev_starless = _downscale(self._starless)
        self.apply_btn.setEnabled(True)
        self._do_render()

    def _on_error(self, exc) -> None:
        self.status.setText(f"Star removal failed: {exc} — using the whole image.")
        self._on_starless((self._base, None))

    def reset(self) -> None:
        self.palette_box.setCurrentIndex(0)
        self.blend_slider.setValue(60)
        self.oiii_slider.setValue(50)
        self.sat_slider.setValue(50)
        self.bright_slider.setValue(50)
        self.protect_slider.setValue(40)
        self.lightness_check.setChecked(True)
        self._do_render()

    def _params(self) -> NarrowbandParams:
        return NarrowbandParams(
            palette=self.palette_box.currentText(),
            blend_amount=self.blend_slider.value() / 100.0,
            oiii_boost=max(0.3, self.oiii_slider.value() / 50.0),
            saturation=self.sat_slider.value() / 100.0,
            brightness=max(0.3, self.bright_slider.value() / 50.0),
            protect_background=self.protect_slider.value() / 100.0,
            lightness_preserve=self.lightness_check.isChecked(),
        )

    def _schedule_render(self) -> None:
        if self._prev_starless is not None:
            self._render_timer.start()

    def _do_render(self) -> None:
        if self._prev_starless is None:
            return
        try:
            self._last = render(self._prev_starless, self._params())
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.preview.show_image(to_qimage(self._last))
        if not self._fitted:
            self._fitted = True
            self.preview.view.fit()

    def preview_result(self) -> AstroImage:
        return self._last

    def apply(self) -> None:
        if self._starless is None:
            self.status.setText("Still removing stars…")
            return
        params = self._params()
        nebula = render(self._starless, params)
        if self._stars is None:
            result = nebula
        else:
            out = screen(nebula.data, np.clip(self._stars.data, 0.0, 1.0))
            result = AstroImage(out, is_linear=False, metadata=dict(self._starless.metadata))
        if self._on_apply is not None:
            self._on_apply(result, params)
        self.accept()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_narrowband_dialog.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nocturne/ui/narrowband_dialog.py tests/ui/test_narrowband_dialog.py
git commit -m "feat(narrowband): guided Narrowband dialog (live preview, StarX-or-whole-image)"
```

---

### Task 4: Toolbar wiring + Help

**Files:**
- Modify: `nocturne/ui/main_window.py` (toolbar action + `_open_narrowband` + `_apply_narrowband`)
- Modify: `nocturne/ui/help_content.py` (a "Narrowband" tool topic)
- Test: `tests/ui/test_main_window.py` (add narrowband integration tests)

**Interfaces:**
- Consumes: `NarrowbandDialog` (Task 3), `NarrowbandStep`/`parse_narrowband_option` semantics (Task 2), existing `_PrecomputedStep`, `self.project.run_step`, `format_log_entry`, `self._refresh`, `load_icon`, `ACCENT`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ui/test_main_window.py` (follow the file's existing `_window`/`_make_fits`/`_go_to_id` helpers):

```python
def test_narrowband_records_recipe_captured_step(qtbot, tmp_path):
    from nocturne.core.narrowband import NarrowbandParams
    from nocturne.recipe import recipe_from_entries
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.6)                                  # need a stretched image
    result = win.project.current()                         # stand-in recoloured result
    win._apply_narrowband(result, NarrowbandParams(palette="HOO", oiii_boost=1.3))
    names = [n for n, _ in win.project.entries()]
    assert "Narrowband" in names
    # and a saved recipe captures it (not dropped)
    recipe = recipe_from_entries(win.project.entries())
    assert any(s["stage"] == "narrowband" for s in recipe.steps)


def test_narrowband_refused_on_linear_image(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))                    # linear, pre-stretch
    win._go_to_id("background")
    win._open_narrowband()                                 # should no-op with a status
    names = [n for n, _ in win.project.entries()]
    assert "Narrowband" not in names
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -k narrowband -q`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_open_narrowband'`.

- [ ] **Step 3: Add the toolbar action**

In `nocturne/ui/main_window.py` `_build_toolbar`, add after the Star Spikes action:

```python
        tb.addAction(load_icon("haoiii", ACCENT), "Narrowband…", self._open_narrowband)
```

(Reuse the `haoiii` icon like Star Spikes does; a dedicated icon is deferred polish.)

- [ ] **Step 4: Add the handlers**

In `nocturne/ui/main_window.py`, add these methods next to `_open_star_spikes`/`_apply_star_spikes`:

```python
    def _open_narrowband(self) -> None:
        if self.project is None:
            return
        if self.project.current().is_linear:
            self._status.setText("Stretch the image first — Narrowband works on the "
                                 "stretched image.")
            return
        from .narrowband_dialog import NarrowbandDialog
        NarrowbandDialog(self.settings, self.project.current(), parent=self,
                         on_apply=self._apply_narrowband).exec()

    def _apply_narrowband(self, result, params) -> None:
        if self.project is None or self._busy:
            return
        self.project.run_step(_PrecomputedStep("Narrowband", result), params)
        self.log_panel.append_entry(format_log_entry("Narrowband", params.palette, None))
        self._status.setText("")
        self._refresh()
```

- [ ] **Step 5: Add the Help topic**

In `nocturne/ui/help_content.py`, locate the `_t("star_spikes", "Star Spikes", …)` entry (in the Tools section) and add this entry immediately after it. If the file has a separate list of topic ids for the Help-window table of contents, add `"narrowband"` there too, in the same place `"star_spikes"` appears.

```python
    _t("narrowband", "Narrowband",
       "Natural Hubble-palette colour from dual-band (Ha + OIII) data.",
       "<p>The Seestar dual-band filter captures two real signals: <b>Ha</b> "
       "(hydrogen, red) and <b>OIII</b> (oxygen). Because Ha is usually much "
       "stronger than OIII, a plain colour combine looks orange. Narrowband first "
       "lifts the weak OIII up to Ha's level, so oxygen shows as real teal/blue.</p>"
       "<h4>How to use it</h4>"
       "<p>Finish your normal processing first (Narrowband works on the stretched "
       "image), then click <b>Narrowband…</b> in the toolbar. Pick a <b>Palette</b>, "
       "and use <b>OIII boost</b> to bring out the oxygen — it is the key control for "
       "Seestar data. <b>Protect background</b> keeps the dark sky its natural colour; "
       "<b>Preserve lightness</b> keeps your tonal structure while only the colour "
       "changes. Watch the live preview, then Apply.</p>"
       "<h4>Palettes</h4>"
       "<p><b>HOO</b> — natural (red-gold nebula, teal oxygen). "
       "<b>Pseudo-SHO</b> — a gold/teal &quot;Hubble&quot; look. "
       "<b>Pseudo-bicolor</b> — magenta nebula, green oxygen. There is no real sulfur "
       "(SII) in dual-band data, so the pseudo palettes are stylistic arrangements of "
       "the two real signals.</p>"
       "<h4>Stars</h4>"
       "<p>With StarXTerminator (RC-Astro) installed, stars are removed first so they "
       "keep their natural colour, then added back on top. Without it, the whole image "
       "is recoloured and star colour may look off.</p>"
       "<h4>Credit</h4>"
       "<p>Normalization concept and palette formulas by Bill Blanshan &amp; Mike "
       "Cranfield (PixInsight NarrowbandNormalization).</p>"),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window.py -k narrowband -q`
Expected: PASS (2 tests).

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add nocturne/ui/main_window.py nocturne/ui/help_content.py tests/ui/test_main_window.py
git commit -m "feat(narrowband): toolbar Narrowband tool + help topic"
```

---

## After all tasks

- Whole-branch review (opus) covering: engine fidelity vs the V8 math in the spec (per-channel `M`, SCNR scope, tone stages), WYSIWYG (live commit == recipe replay), RC-Astro-absent path, no regression to `haoiii`.
- **User real-data validation** on Seestar HOO (NGC 7000, Pacman): OIII boost brings out teal, background stays neutral, stars correctly coloured with RC-Astro, the three palettes are distinct. Iterate on the pseudo-palette channel math / default slider values per the user's eye.
- Then `superpowers:finishing-a-development-branch`.

## Notes / deferred (from the spec, do NOT build here)

- Free star-mask fallback (sep) for starless without RC-Astro.
- Continuum subtraction (`OIII − k·Ha`).
- A dedicated toolbar icon for Narrowband.
- Per-channel manual curves / additional palettes.
