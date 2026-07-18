# Narrowband palette — Increment 1: the core normalization engine

**Date:** 2026-07-18
**Status:** Approved (Increment 1 of a multi-increment feature)
**Scope:** new `nocturne/core/narrowband.py` + tests + a real-data validation script. **No app/UI changes, nothing removed** — those are Increment 2.

## Background

Nocturne's two current narrowband features (the raw-CFA Ha/OIII stacking extractor and the "Colourise" step on Stretch) are rudimentary. We are replacing the *colour* side with a function inspired by PixInsight's **NarrowbandNormalization** (NBN), which Seestar users run on their broadband LP images to get pleasing Hubble-style palettes.

**Fixed input domain:** broadband OSC, LP-tinted, from the Seestar S30 Pro. No real narrowband, ever. This is a stylization tuned for that data; success = the result matches what NBN produces in PI on the same image, judged by the user's eye.

This increment builds ONLY the pure-numpy core engine for the **HOO palette** (the physically-native mode for dual-band Ha+OIII) and validates it on a real Seestar master. Later increments add the standalone dialog + removal of old code (Inc 2), the SHO/HOS looks and full control set (Inc 3+).

## The NBN algorithm (verbatim core, reimplemented in numpy)

From Bill Blanshan's published PixelMath (astroguide.starlust.de). Notation: `~x = 1-x`; `mtf(m,x) = ((m-1)x)/((2m-1)x - m)` (PixInsight midtones transfer function — already implemented as `nocturne/core/autostretch._mtf`, reuse it). Defaults: Blackpoint=1.0, OIIIBoost=1.0, HLReduction=1.0, Brightness=1.0, HLRecover=1.0.

Per-channel `M` and `E0`, then a level `A` normalized by the **secondary (OIII) channel's** headroom (verbatim source: `A0 = E0/~M[1]`, where channel 1 is the one being normalized — so both Ha and OIII levels share the divisor `1 - M_oiii`):
```
M_c  = min(C) + Blackpoint*(median(C) - min(C))       # black point (Blackpoint=1 → start at median)
E0_c = adev(C)/1.2533 + mean(C) - M_c                 # robust signal level (adev = mean abs dev)
A_ha   = E0_ha   / (1 - M_oiii)                        # both divided by the OIII channel's headroom
A_oiii = E0_oiii / (1 - M_oiii)                        # (guard: if 1 - M_oiii <= 1e-6 → identity, skip)
```
Normalize the secondary channel (OIII) to the reference (Ha):
```
E1 = (A_oiii*(1 - A_ha) / (A_oiii - 2*A_oiii*A_ha + A_ha)) / OIIIBoost   # solve MTF midtone
E2 = rescale(oiii, M_oiii, 1)                          # clip below black point, rescale to [0,1]
oiii_norm = ~( ~mtf(E1, E2) * ~min(oiii, M_oiii) )     # apply MTF, re-attach sub-blackpoint part
```
Final tone adjustments (identity at default 1.0):
```
E11 = (mtf(~(1/HLReduction*0.5), x)*x) + (x*~x)        # highlight reduction
E12 = mtf(1/Brightness*0.5, E11)                       # brightness
E13 = rescale(E12, 0, HLRecover)                       # highlight recover
```

## Design — `nocturne/core/narrowband.py`

Pure numpy, Qt-free. Operates on a **stretched** (display-range) RGB image — because in the real workflow this is a *finishing* step applied after all other edits (the validation script stretches the linear master first).

Functions:
- `extract_ha_oiii(img: AstroImage) -> tuple[np.ndarray, np.ndarray]` — Ha = red channel, OIII = (green+blue)/2, both 2D float32 in [0,1]. Raises `ValueError` on a mono image. (Same mapping as the old `palette.extract_channels`; this is the broadband→pseudo-channel step.)
- `channel_level(c: np.ndarray, blackpoint: float) -> tuple[float, float]` — returns `(M, A)` per the formulas above. `A` guarded: if `1 - M <= 1e-6`, return `A = 0`.
- `normalize_to_reference(secondary, reference, blackpoint, boost) -> np.ndarray` — the NBN core: compute levels, solve `E1`, apply MTF, re-attach. **Degenerate guards:** if the `E1` denominator `|A_oiii - 2·A_oiii·A_ha + A_ha| < 1e-6`, or either level is ~0 (faint/empty OIII from a bright LP sky — common), return the secondary unchanged (identity, no NaN). Clamp `E1` to a sane midtone range (e.g. [1e-3, 1-1e-3]).
- `synthetic_green(ha, oiii, amount: float) -> np.ndarray` — Blanshan/Foraxx dynamic blend: `w = (ha*oiii)**(1 - ha*oiii)`; `g = amount*(w*ha + (1-w)*oiii) + (1-amount)*oiii`. `amount` in [0,1], default 0.6 (blends toward the dynamic green; 0 = pure OIII). (Exact NBN Mode1–4 are closed-source; this is the published family NBN is built on — deferred refinement.)
- `highlight_reduction(x, amount)`, `brightness(x, amount)`, `highlight_recover(x, amount)` — the E11/E12/E13 tone stages; each is identity when `amount == 1.0`.
- `NarrowbandParams` dataclass: `palette: str = "HOO"`, `blackpoint: float = 1.0`, `oiii_boost: float = 1.0`, `blend_amount: float = 0.6`, `highlight_reduction: float = 1.0`, `brightness: float = 1.0`, `highlight_recover: float = 1.0`, `saturation: float = 0.6`.
- `render_hoo(img: AstroImage, params: NarrowbandParams) -> AstroImage` — the pipeline:
  1. `ha, oiii = extract_ha_oiii(img)`
  2. `oiii_n = normalize_to_reference(oiii, ha, params.blackpoint, params.oiii_boost)`
  3. HOO combine: `R = ha`, `G = synthetic_green(ha, oiii_n, params.blend_amount)`, `B = oiii_n`
  4. per-channel tone: `highlight_reduction` → `brightness` → `highlight_recover` (identity at defaults)
  5. `saturate(...)` (reuse `core/saturation.saturate`)
  6. return `AstroImage(rgb, is_linear=False, metadata=...)`

Reuse: `autostretch._mtf`, `saturation.saturate`. No dependency on `core/palette.py` (which Increment 2 removes).

## Data flow / validation

Validation script (scratch, not committed): load the NGC 7000 LP master, `apply_stretch(…, 0.5)` to get a display-range image (mirrors "finishing step on the edited image"), run `render_hoo` at defaults, save centre crops. Also render the current `palette.render_nebula`/`foraxx` HOO output for side-by-side. The user compares both against NBN's HOO result in PixInsight on the same file and tells us how close it lands. Iterate `synthetic_green`/defaults on the pure module until it tracks PI.

## Error handling

- Mono image → `ValueError("Narrowband palette needs a colour image")`.
- Degenerate/empty OIII (bright LP sky) → normalization returns identity, no NaN/crash (guards above).
- All output clamped to [0,1] float32.

## Testing (`tests/core/test_narrowband.py`)

- `mtf` endpoints (via the reused helper): x=0→0, x=1→1.
- `channel_level`: on a synthetic channel, M interpolates min→median by blackpoint; A ≥ 0.
- `normalize_to_reference`: a faint synthetic OIII (low median) is lifted so its post-normalization level is much closer to Ha's than before (assert the level gap shrinks); a boost>1 lifts it further.
- Degenerate: all-zero OIII, and OIII≈Ha, → finite output, no NaN, no crash.
- `synthetic_green`: Ha-dominant pixel → green nearer Ha; OIII-dominant → green nearer OIII; amount=0 → equals OIII.
- Tone stages identity at amount=1.0; `brightness<1`/`>1` darkens/brightens monotonically.
- `render_hoo`: output is colour, [0,1], shape matches; a faint-OIII synthetic input yields visible non-red (teal) pixels where OIII exists (the core win); does not blow out to white; does not spatially blur (per-pixel op).
- `NarrowbandParams` defaults.

## Out of scope (later increments)

- The standalone "Narrowband Palette…" toolbar tool + dialog + live preview; removing `palette.py`/`palette_dialog.py`/Colourise (Increment 2).
- SHO/HOS looks (synthetic SII), exact NBN blend modes, LAB Lightness, SCNR fine control, recipe serialization (Increment 3+).
