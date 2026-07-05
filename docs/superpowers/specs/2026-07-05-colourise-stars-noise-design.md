# Colourise — Brighter Stars + Tamed Noise — Design

**Date:** 2026-07-05
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved (design + key decision) — building under standing authorization.

## Motivation

After the one-press Colourise shipped, real-data feedback surfaced two linked issues (both root-caused
via systematic-debugging):

1. **Screened-back stars are too dim.** `neutralize_stars` applies a gentle γ=0.5 curve to the **raw,
   faint, linear** StarX stars-only layer, so the faint majority stay dim against the now-bright
   stretched nebula — only the brightest few show.
2. **Excessive noise.** The Oxygen (OIII) channel's noise is amplified **~40×** through Colourise
   (measured) because `renorm_oiii` scales weak OIII up to Ha and `stretch_channel` stretches it hard.
   That grain drives the user to apply **strong Noise Reduction afterward, which erases the small
   stars** — so the two issues compound.

Decision from discussion: keep stars **neutral/white** (dualband stars go magenta if their colour is
kept), just fix the brightness; and tame the OIII noise **at the source, inside Colourise**.

## Decisions

- **Stars stay white**, but are lifted to real visibility with a **controlled, non-degenerate tone
  curve** (no return of the earlier bloat).
- **Denoise the faint channel(s) before the big stretch** — light, edge-preserving (total-variation),
  gentle enough to avoid a "plastic" look.
- Both are **automatic defaults inside one-press Colourise** (new `PaletteParams` fields) — no new UI
  this pass. Tunable via Advanced… sliders as a fast-follow.
- The StarX remove → colourise-starless → screen-stars-back structure is **unchanged**; only the
  star re-brightening curve and a pre-stretch denoise are added.

## Architecture / changes (all in `core/palette.py`)

### `PaletteParams` — two new fields (defaults used by one-press `PaletteParams()`)
```python
    denoise: float = 0.02          # TV-chambolle weight for the faint channels (0 = off)
    star_brightness: float = 0.08  # MTF midtones for the white-star lift (LOWER = brighter stars)
```

### `neutralize_stars(stars, midtones=0.08)` — brighter white stars, still tight
Replace the fixed-gamma lift with a **fixed-midtones MTF** (`autostretch._mtf`), which strongly lifts
faint star values without the adaptive-autostretch degeneracy that previously bloated stars:
```python
def neutralize_stars(stars: AstroImage, midtones: float = 0.08) -> AstroImage:
    if not stars.is_color:
        return stars.copy()
    lum = _mtf(midtones, np.clip(stars.data.mean(axis=2), 0.0, 1.0))
    rgb = np.clip(np.stack([lum, lum, lum], axis=2), 0.0, 1.0).astype(np.float32)
    return AstroImage(rgb, is_linear=False, metadata=dict(stars.metadata))
```
Evidence: over a bright nebula, faint-star visibility rises ~67%→~83%; single-star footprint 21→29px
(the old degenerate autostretch was 149px). `_STAR_GAMMA` is removed. `compose` passes the param:
`white = neutralize_stars(stars, params.star_brightness)`.

### `render_nebula` — light denoise of the faint channel(s) before stretch
After `subtract_bg_2d` + `renorm_oiii`, and **before** `stretch_channel`, when `params.denoise > 0`
apply an edge-preserving total-variation denoise to the channels (so the aggressive stretch reveals
clean signal, not amplified grain):
```python
    if params.denoise > 0:
        from skimage.restoration import denoise_tv_chambolle
        ha = denoise_tv_chambolle(ha, weight=params.denoise).astype(np.float32)
        oiii = denoise_tv_chambolle(oiii, weight=params.denoise).astype(np.float32)
    ha = stretch_channel(ha, params.ha_stretch)
    oiii = stretch_channel(oiii, params.oiii_stretch)
```
Evidence: OIII flat-field noise after stretch drops ~0.168→~0.050 (≈3.4× less) at weight 0.02, with
core signal preserved (0.494→0.515). Both channels are denoised (OIII benefits most; Ha is only
lightly touched at this gentle weight, preserving nebula detail).

## Data flow

`render_nebula`: extract → bg-subtract → renorm OIII → **denoise (new)** → independent stretch →
Foraxx → SCNR → hue/sat. `compose`: render_nebula(starless) then screen **brighter white stars**
(`neutralize_stars(stars, params.star_brightness)`) back. One-press uses default `PaletteParams()`,
so it gets both fixes automatically.

## Error handling

- `denoise = 0` skips denoising (no-op path).
- Mono star layer → `neutralize_stars` returns a copy unchanged (existing guard).
- `_mtf` is a fixed smooth curve — no degeneracy on the sparse star layer (that was the whole point
  of moving off adaptive autostretch), so no NaN / no bloat.
- No new dependency (`scikit-image` is already used; `denoise_tv_chambolle` confirmed available).

## Testing

- **core** (`tests/core/test_palette.py`):
  - `neutralize_stars` on a realistic sparse star field lifts the faint-star luminance meaningfully
    higher than the old γ=0.5 (assert median star luminance above a threshold that γ=0.5 fails),
    while a single star's footprint stays tight (`> 0.5` px below a bloat threshold, e.g. < 60).
  - Stars stay neutral (`r == g == b`).
  - `render_nebula` with `denoise > 0` reduces flat-field (background) noise vs `denoise = 0` on a
    noisy synthetic dualband image (assert the stretched OIII/background std is meaningfully lower),
    while the nebula core signal is preserved (not flattened to background).
  - `render_nebula` output still `is_linear is False`; `denoise = 0` path unchanged.
  - `PaletteParams` defaults: `denoise == 0.02`, `star_brightness == 0.08`.
- Existing palette + main_window tests stay green (one-press `compose` path picks up the defaults).
- Full suite green (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`).

## Out of scope (fast-follow)

- **Advanced… sliders** for `denoise` and `star_brightness` (this pass ships good auto defaults only).
- Recipe/batch capture of Colourise (already logged as the prior follow-up).

## Verification (by eye)

Re-Colourise a dualband master: the teal/blue areas are visibly cleaner (less grain), and the star
field comes back with the faint stars visible (white, tight) — without needing to apply strong Noise
Reduction afterward, so the stars survive the rest of the workflow.
