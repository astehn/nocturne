# Colourise Stars + Noise Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one-press Colourise bring faint stars back visibly (white, tight) and cut the amplified Oxygen-channel noise, both automatically.

**Architecture:** Two changes in `core/palette.py`: (1) `neutralize_stars` lifts the white star layer with a fixed-midtones MTF instead of a gentle gamma; (2) `render_nebula` applies a light total-variation denoise to the faint channels before the big stretch. Both are new `PaletteParams` defaults, so one-press picks them up.

**Tech Stack:** Python 3.13 (`.venv`), NumPy, scikit-image (`denoise_tv_chambolle`, already a dependency), pytest.

## Global Constraints

- Use `.venv/bin/python` / `.venv/bin/pytest`; system python is 3.9 and will fail.
- Stars stay **neutral/white** (`r == g == b`); the fix is brightness only, via a fixed-midtones MTF (`autostretch._mtf`) — NOT the adaptive autostretch (which degenerates/bloats on the sparse star layer).
- Denoise runs **after** `subtract_bg_2d` + `renorm_oiii` and **before** `stretch_channel`, only when `params.denoise > 0`, on both Ha and OIII.
- New `PaletteParams` fields with these exact defaults: `denoise: float = 0.02`, `star_brightness: float = 0.08` (the MTF midtones; lower = brighter stars).
- `neutralize_stars(stars, midtones=0.08)`; `compose` passes `params.star_brightness`.
- No new dependency; `render_nebula` output stays `is_linear=False`.
- Commit co-author trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Known flake: `test_sharpen_changes_image_and_keeps_shape` — rerun alone if it trips.

---

### Task 1: Brighter white stars + faint-channel denoise

**Files:**
- Modify: `seestar_processor/core/palette.py` (imports line 8; `PaletteParams`; `render_nebula`; `neutralize_stars`; `compose`)
- Test: `tests/core/test_palette.py`

**Interfaces:**
- Produces: `PaletteParams(..., denoise=0.02, star_brightness=0.08)`; `neutralize_stars(stars, midtones=0.08)`; `render_nebula` honouring `params.denoise`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/core/test_palette.py`:

```python
def _faint_star_field():
    # realistic sparse star field: power-law brightness (many faint, few bright), linear
    from scipy.ndimage import gaussian_filter
    rng = np.random.default_rng(7)
    H, W = 200, 200
    s = np.zeros((H, W), np.float32)
    for (cy, cx), a in zip(rng.integers(3, H - 3, (500, 2)), (rng.random(500) ** 3)):
        s[cy, cx] += a
    s = gaussian_filter(s, 0.8, mode="constant")
    s = np.clip(s, 0.0, None)
    s /= s.max()
    return AstroImage(np.stack([s, s, s], axis=2).astype(np.float32), is_linear=True)


def test_neutralize_stars_lifts_faint_stars():
    from seestar_processor.core.palette import neutralize_stars
    out = neutralize_stars(_faint_star_field()).data
    lum = out.mean(axis=2)
    star_px = lum[lum > 0.01]
    assert float(np.median(star_px)) > 0.25    # gamma=0.5 gave ~0.20; MTF lift clears 0.25
    assert np.allclose(out[..., 0], out[..., 1]) and np.allclose(out[..., 1], out[..., 2])  # white


def test_palette_params_star_and_denoise_defaults():
    from seestar_processor.core.palette import PaletteParams
    p = PaletteParams()
    assert p.denoise == 0.02 and p.star_brightness == 0.08


def _noisy_dualband_starless():
    rng = np.random.default_rng(2)
    H, W = 160, 160
    yy, xx = np.mgrid[0:H, 0:W]
    sig = np.exp(-(((xx - 80) / 90) ** 2 + ((yy - 80) / 90) ** 2))
    d = np.zeros((H, W, 3), np.float32)
    d[..., 0] = 0.02 + 0.08 * sig                 # Ha
    d[..., 1] = 0.02 + 0.015 * sig                # OIII (weak)
    d[..., 2] = 0.02 + 0.015 * sig
    d += rng.normal(0, 0.006, (H, W, 3)).astype(np.float32)
    return AstroImage(np.clip(d, 0.0, 1.0), is_linear=True)


def test_render_nebula_denoise_reduces_noise_preserves_signal():
    from seestar_processor.core.palette import render_nebula, PaletteParams
    img = _noisy_dualband_starless()
    off = render_nebula(img, PaletteParams(denoise=0.0)).data
    on = render_nebula(img, PaletteParams(denoise=0.02)).data
    # background corner (signal-free) is cleaner with denoise
    assert on[:30, :30].std() < off[:30, :30].std() * 0.8
    # central nebula signal survives (not flattened to background)
    assert on[70:90, 70:90].mean() > on[:30, :30].mean() + 0.1
    assert render_nebula(img, PaletteParams()).is_linear is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/core/test_palette.py -q -k "lifts_faint_stars or star_and_denoise_defaults or denoise_reduces_noise"`
Expected: FAIL — `PaletteParams` has no `denoise`/`star_brightness`; `neutralize_stars` gamma lift gives median ~0.20 (< 0.25); denoise not applied.

- [ ] **Step 3: Add the imports and PaletteParams fields**

In `seestar_processor/core/palette.py`, change the autostretch import (line 8):
```python
from .autostretch import _mtf, linked_stretch
```

Add the two fields to `PaletteParams` (after `scnr: bool = True`):
```python
    denoise: float = 0.02          # TV-chambolle weight for the faint channels (0 = off)
    star_brightness: float = 0.08  # MTF midtones for the white-star lift (lower = brighter stars)
```

- [ ] **Step 4: Add the denoise to `render_nebula`**

In `render_nebula`, replace the two `stretch_channel` lines with the denoise block followed by the stretch:
```python
    if params.denoise > 0:
        from skimage.restoration import denoise_tv_chambolle
        ha = denoise_tv_chambolle(ha, weight=params.denoise).astype(np.float32)
        oiii = denoise_tv_chambolle(oiii, weight=params.denoise).astype(np.float32)
    ha = stretch_channel(ha, params.ha_stretch)
    oiii = stretch_channel(oiii, params.oiii_stretch)
```

- [ ] **Step 5: Brighten `neutralize_stars` (MTF) and remove `_STAR_GAMMA`**

Replace the `_STAR_GAMMA = 0.5` line and the `neutralize_stars` function with:
```python
def neutralize_stars(stars: AstroImage, midtones: float = 0.08) -> AstroImage:
    """White (colour-neutral) star layer, lifted with a FIXED-midtones MTF so the
    faint majority stay visible over the stretched nebula without bloating.

    Do NOT use the adaptive autostretch here: the StarX 'stars_only' layer is
    sparse (mostly black), so its median/MAD collapse to ~0 and the adaptive
    midtones solve degenerates into an extreme threshold that blows stars to
    white blobs. A fixed midtones (default 0.08) lifts faint stars while a smooth
    curve keeps them tight."""
    if not stars.is_color:
        return stars.copy()
    lum = _mtf(midtones, np.clip(stars.data.mean(axis=2), 0.0, 1.0))
    rgb = np.clip(np.stack([lum, lum, lum], axis=2), 0.0, 1.0).astype(np.float32)
    return AstroImage(rgb, is_linear=False, metadata=dict(stars.metadata))
```

- [ ] **Step 6: Pass `star_brightness` through `compose`**

In `compose`, change the star line:
```python
    white = neutralize_stars(stars, params.star_brightness)
```

- [ ] **Step 7: Run the palette tests**

Run: `.venv/bin/pytest tests/core/test_palette.py -q`
Expected: PASS — new tests plus all existing (notably `test_neutralize_stars_does_not_bloat`, whose single-star footprint stays tight at ~29px < 40, and `test_neutralize_stars_makes_white`).

- [ ] **Step 8: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: all pass (rerun the known sharpen flake alone if it trips).

- [ ] **Step 9: Commit**

```bash
git add seestar_processor/core/palette.py tests/core/test_palette.py
git commit -m "feat: brighter white Colourise stars (MTF lift) + faint-channel denoise"
```

---

## Self-Review

- **Spec coverage:** star brightness via fixed-midtones MTF keeping white (Step 5), `star_brightness`/`denoise` params + defaults (Step 3), denoise before stretch on both channels (Step 4), `compose` passes the param (Step 6), tests for lift/white/denoise/defaults/is_linear (Step 1) — all covered.
- **Placeholder scan:** none — full code in every step.
- **Type consistency:** `neutralize_stars(stars, midtones=0.08)`, `PaletteParams(denoise, star_brightness)`, `_mtf` import, and `denoise_tv_chambolle(weight=...)` used identically across the edits and tests.
- **Regression guard:** existing `test_neutralize_stars_does_not_bloat` (<40px) still passes with the MTF (measured ~29px); `test_neutralize_stars_makes_white` still holds (r==g==b); `denoise=0` path leaves render unchanged for callers that pass it.
- **Grounding:** MTF m=0.08 → faint-star visibility ~67%→~83%, footprint 21→29px; TV weight 0.02 → OIII noise ~0.168→~0.050 with core signal preserved (both measured before writing the plan).
