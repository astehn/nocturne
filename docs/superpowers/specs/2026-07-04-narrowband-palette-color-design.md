# Narrowband Palette — Real Colour from Duo-Band Data — Design

**Date:** 2026-07-04
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved (direction + key decisions) — building under standing authorization.

## Motivation

Seestar LP-filter (dual-band Ha + OIII) masters contain a two-colour narrowband signal, but the
current Palette tool produces a **red-monochrome** result. Root cause (confirmed by research across
PixInsight/Siril/RC-Astro workflows): Ha is 3–10× brighter than OIII, and the tool combines the
channels with **no per-channel normalization and no independent stretch**, so Ha dominates and OIII
is crushed into the noise floor. The per-channel Black/Mid/White curves are *levels* — they change a
channel's brightness but cannot manufacture the colour separation that was flattened away. The goal
is to make the tool produce a genuine bicolour (gold dust / teal-blue core) image like a classic
HOO/Foraxx rendering.

## Decisions (from discussion)

- **Evolve the existing Palette tool** (keep StarX star-split, live preview, apply-as-one-history-
  step). Rebuild its *internals* and controls.
- **Remove** the R/G/B channel tabs and Black/Mid/White curves entirely (they caused the "affects
  the whole image" confusion and can't create colour).
- **Separate Ha and OIII stretch sliders** (full manual control) — the independent stretch is the
  fix for red-monochrome.
- **Add the Foraxx dynamic palette** (default) alongside HOO and pseudo-SHO.
- **Add Hue + Saturation finishing** (the "HSL" the user wanted).
- The tool assumes the **linear master** as input (run before the global Stretch); it does its own
  per-channel stretch. If the input is already non-linear, still run but show a gentle hint.
- **Honest expectation** (documented in-app copy, not code): from a bright northern-summer LP sky,
  OIII is faint, so teal/blue starts subtle/noisy; darker skies + more OIII time raise the ceiling.

## Architecture / changes

### `core/palette.py`

Reworked `PaletteParams` (drop the three `ChannelCurve`s; `ChannelCurve`/`apply_channel_curve` are
removed as dead once curves are gone):
```python
@dataclass
class PaletteParams:
    palette: str = "Foraxx"        # "Foraxx" | "HOO" | "pseudo_SHO"
    ha_stretch: float = 0.6        # [0,1] aggressiveness for the Ha channel
    oiii_stretch: float = 0.7      # [0,1] — a touch stronger to lift weak OIII
    hue_deg: float = 0.0           # global hue rotation, degrees, [-30, +30]
    saturation: float = 0.65       # [0,1] -> core.saturation.saturate amount (0.5 = neutral)
    scnr: bool = True              # green suppression
```

New / changed pure functions (all numpy, testable, Qt-free):
- `subtract_bg_2d(channel, percentile=50.0) -> np.ndarray` — per-channel pedestal removal (2D form
  of the existing `subtract_background`; reuse/adapt).
- `renorm_oiii(ha, oiii) -> np.ndarray` — median+MAD match of OIII to Ha (mirrors the proven
  `stacking/haoiii.renorm_oiii`; add to core so the feature is self-contained. Optional later dedup:
  have the stacker import it from core).
- `stretch_channel(channel, amount) -> np.ndarray` — independent nonlinear stretch of one 2D
  channel, reusing the existing autostretch primitive
  (`autostretch.linked_stretch(channel, stretch.amount_to_target(amount))`, applied to the 2D array).
- `foraxx(ha, oiii) -> (r, g, b)` — dynamic blend:
  ```python
  p = ha * oiii
  w = np.power(p, 1.0 - p)          # per-pixel weight 0..1
  r = ha
  g = w * ha + (1.0 - w) * oiii
  b = oiii
  ```
  (`hoo` and `pseudo_sho` kept.)
- `rotate_hue(rgb, degrees) -> np.ndarray` — via `skimage.color.rgb2hsv` → add `degrees/360` to H
  (mod 1) → `hsv2rgb`.

Rewritten `render_nebula(starless, params)` — order of operations:
1. `ha, oiii = extract_channels(starless)` (starless linear RGB → Ha=R, OIII=(G+B)/2).
2. `ha = subtract_bg_2d(ha)`, `oiii = subtract_bg_2d(oiii)`.
3. `oiii = renorm_oiii(ha, oiii)`.
4. `ha = stretch_channel(ha, params.ha_stretch)`, `oiii = stretch_channel(oiii, params.oiii_stretch)`.
5. blend per `params.palette` (Foraxx / HOO / pseudo_SHO) → `rgb`.
6. optional SCNR (`params.scnr`): `g = min(g, max(r, b))` (research: HOO usually fine, but Seestar
   Bayer bleed adds green — keep as a toggle, default on).
7. `rgb = rotate_hue(rgb, params.hue_deg)`; `rgb = saturate(AstroImage(rgb), params.saturation).data`.
8. return `AstroImage(clip(rgb), is_linear=False, metadata=...)` — **output is now stretched**
   (`is_linear=False`), so the user does not run the global Stretch afterward.

`compose(starless, stars, params)` — render nebula (now stretched), then screen a **stretched**
white-star layer on top: `neutralize_stars` must auto-stretch the star luminance
(`autostretch.autostretch` on the mean) before screening, so stars remain visible on the stretched
nebula (currently it screens a linear/dark star layer, which would vanish).

### `ui/palette_dialog.py`

- **Remove:** the R/G/B `QRadioButton` channel tabs, the black/mid/white `ResetSlider`s, `_slider`
  curve wiring, `_select_channel`, and the per-channel `ChannelCurve` state.
- **Add** (all `ResetSlider`, double-click-to-reset; sliders are 0–100 ints mapped to params):
  - Palette radio: **Foraxx** (default) / HOO / pseudo-SHO.
  - **Ha stretch** (default 60 → 0.60), **OIII stretch** (default 70 → 0.70).
  - **Hue** (default 50 → 0°; maps `(v-50)/50*30` → [-30,+30]°).
  - **Saturation** (default 65 → 0.65).
  - Keep the **Remove green (SCNR)** checkbox and the **Reset** button.
- Each control change rebuilds `PaletteParams` and calls `_render_preview` (existing).
- If `self._base.is_linear` is False, show a non-blocking status hint: "Palette works best on the
  linear master — run it before the Stretch step."
- Apply records one "Palette" history step (unchanged path via `on_apply`).

## Data flow

StarX split (existing) → `render_nebula`/`compose` on the **linear** starless/stars → normalized,
independently-stretched Ha/OIII → palette blend → SCNR → hue/sat → screen stars → one stretched
"Palette" `AstroImage` recorded as a history step. Live preview uses the same path on a downscaled
copy (existing `_prev_starless`/`_prev_stars`).

## Error handling

- Non-colour input → `extract_channels` raises (existing guard in `_open_palette`).
- Weak/zero OIII → `renorm_oiii` guards `MAD==0`; result leans red (honest — that's the data).
- Already-stretched input → still renders; UI hint shown. No crash (stretch of near-[0,1] data is
  gentle/monotonic).
- StarX unavailable → falls back to whole-image (existing behaviour retained).

## Testing

- **core** (`tests/core/test_palette.py`):
  - `foraxx`: a strong-Ha+strong-OIII pixel → R and G high, i.e. gold (G ≈ Ha); OIII-only pixel →
    G,B > R (teal); Ha-only pixel → R > G,B (red). Assert those channel orderings.
  - **Not-monochrome:** an image with OIII ≪ Ha, after `render_nebula`, has real chroma — assert the
    per-pixel channel spread (max−min across RGB) mean exceeds a threshold that a naive equal-weight
    combine would fail (guards the regression this feature fixes).
  - `renorm_oiii`: output median ≈ Ha median and MAD ≈ Ha MAD.
  - `stretch_channel`: raises the median of a faint channel toward the mid-target (independent
    stretch actually lifts OIII).
  - `rotate_hue`: rotating a pure-red input by +30° moves its HSV hue by ~30°; 0° is identity.
  - `render_nebula` output `is_linear is False`.
  - `PaletteParams` defaults; `ChannelCurve`/`apply_channel_curve` removed (delete their old tests).
- **ui** (`tests/ui/test_palette_dialog.py`):
  - Dialog exposes a palette radio (Foraxx/HOO/pseudo_SHO) and `ha_stretch`/`oiii_stretch`/`hue`/
    `saturation` `ResetSlider`s; has **no** black/mid/white sliders or R/G/B tabs.
  - SCNR checkbox + Reset button present; moving a slider updates the built `PaletteParams`.
  - `is_linear=False` base shows the hint.
- Full suite green (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`).

## Verification (by eye)

Open a Seestar LP master, run Background, open **Palette** on the linear image: default Foraxx yields
a gold/teal bicolour (not red). OIII-stretch lifts the teal; Hue tunes gold↔orange; Saturation
deepens colour; SCNR tames green; stars screen back white. Apply → one undoable "Palette" step; export.
