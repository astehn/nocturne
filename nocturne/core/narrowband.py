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
from .saturation import _MASK_SIGMA_FRAC, saturate


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
                           blackpoint: float = 1.0) -> np.ndarray:
    """MTF-match the secondary channel's robust level to the reference's, each
    channel using ITS OWN black point. Degenerate inputs fall back to identity.

    Purely photometric since 2026-09-09. It used to take a `boost` that divided
    the midpoint below, so this one function both matched the channels and chose
    how much oxygen the picture showed — which is why the matched setting was
    also the least colourful one. How loud the oxygen is now belongs to
    NarrowbandParams.oxygen_strength, applied to the RESULT of this function.
    """
    sec = np.clip(np.asarray(secondary, dtype=np.float32), 0.0, 1.0)
    ref = np.clip(np.asarray(reference, dtype=np.float32), 0.0, 1.0)
    return _apply_match(sec, _match_levels(sec, ref, blackpoint))


def _match_levels(sec: np.ndarray, ref: np.ndarray,
                  blackpoint: float) -> tuple[float, float] | None:
    """The (black point, MTF midtone) normalize_to_reference applies, or None
    for its identity fallback. Split out so the gold-and-blue palette can
    measure them on the preview-sized copy and apply them at full size."""
    M_sec, E0_sec = channel_level(sec, blackpoint)
    M_ref, E0_ref = channel_level(ref, blackpoint)
    if 1.0 - M_sec <= 1e-6 or 1.0 - M_ref <= 1e-6:
        return None
    A_sec = E0_sec / (1.0 - M_sec)
    A_ref = E0_ref / (1.0 - M_ref)
    denom = A_sec - 2.0 * A_sec * A_ref + A_ref
    if abs(denom) < 1e-6 or A_sec <= 1e-6 or A_ref <= 1e-6:
        return None
    m = float(np.clip(A_sec * (1.0 - A_ref) / denom, 1e-3, 1.0 - 1e-3))
    return M_sec, m


def _apply_match(sec: np.ndarray, levels: tuple[float, float] | None) -> np.ndarray:
    """`sec` must already be clipped float32, as normalize_to_reference makes it."""
    if levels is None:
        return sec
    M_sec, m = levels
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
    # How loud the oxygen is, applied to the MATCHED OIII plane. 1.0 leaves the
    # photometric match exactly as computed, and is labelled "matched" on the
    # slider. Below 1.0 is hydrogen-leaning and warm; above is oxygen-leaning
    # and cool. Both effects come from the same move: raising it brings the teal
    # out AND drains the reds, because it scales oxygen RELATIVE to hydrogen.
    #
    # 0.85 was CHOSEN BY EYE by Andreas on 2026-09-09, from rendered candidates
    # at 0.60/0.70/0.85/1.00 on M 16 (hydrogen-dominant) and NGC 6992 (the Veil,
    # oxygen-rich), the Veil judged on a native-resolution crop of its filaments.
    # Bright-nebula chroma (0-255) at each, for the record:
    #
    #     strength      0.50   0.60   0.70   0.80   0.90   1.00   1.20
    #     M 16          36.3   30.9   24.2   19.7   16.6   14.4   11.6
    #     NGC 6992      16.1   14.7   12.4   11.1   10.4    9.9    9.3
    #     M 8           64.5   57.4   42.6   31.7   24.5   19.7   13.4
    #     M 17          27.2   26.8   21.8   18.1   15.6   13.8   11.9
    #
    # BY EYE, and deliberately so. Three measured criteria were tried and all
    # three fail; do not replace this with a formula without reading why:
    #
    #  1. "Parity with the input's chroma" answers 1.00 — i.e. change nothing —
    #     but only because it depends on how far through the pipeline the input
    #     already is. A real pre-narrowband image measured 25.0 where the best
    #     reconstruction from its own master measured 14.6, and colour
    #     calibration closes 0.01 of that gap. The criterion silently encodes an
    #     assumption about the user's workflow.
    #  2. "Where the core stops being neutral" is the right idea measured wrongly:
    #     the top 0.5% of luminance on a frame that still has its stars IS the
    #     stars, which are white by construction and unmoved by any setting.
    #  3. A bright-nebula chroma threshold clears at EVERY strength, so there is
    #     no crossing to anchor on.
    #
    # What survives all three is only the shape: lower is warmer and more
    # colourful, monotonically, on every target. There is no optimum in the data,
    # only a preference — so a person chose it.
    oxygen_strength: float = 0.85
    blend_amount: float = 0.6
    highlight_reduction: float = 1.0
    brightness: float = 1.0
    highlight_recover: float = 1.0
    # 0.5 is "native" in saturate() -- no boost at all -- and the HOO palette
    # costs chroma by construction: a warm pink mapped to R=Ha / B=OIII goes
    # neutral wherever the two gases overlap. So the step used to take colour out
    # and put none back, and the result came out slightly flatter than its own
    # input. Measured on the 724-frame IC 1396A master, stretched, nebula chroma
    # against the image the step was handed:
    #
    #     saturation   0.50    0.70    0.85    1.00
    #     no StarX      -7%     -4%     -1%     +1%
    #     with StarX    -7%     -1%     +4%     +9%
    #
    # 0.85 lands on parity instead of a deficit. It costs nothing elsewhere: sky
    # chroma moves 0-1% across the WHOLE slider range, because saturate()'s
    # shadow_protect and this module's protect_background both hold the
    # background back. Andreas and I noticed the flatness independently before
    # either of us measured it (2026-09-08).
    saturation: float = 0.85
    # False, matching what the dialog has always shipped: the brighter combine
    # is the better default. These disagreed, so a recipe or batch run with no
    # explicit option rendered DIFFERENTLY from the same tool used by hand.
    lightness_preserve: bool = False
    protect_background: float = 0.4
    scnr: bool = True


GOLD_BLUE = "SHO-style (gold and blue)"

PALETTES = ("HOO", "Pseudo-SHO", "Pseudo-bicolor", GOLD_BLUE)

# Only HOO builds a synthetic green, so the Green blend amount reaches the
# picture there and nowhere else: Pseudo-SHO takes green straight from Ha and
# Pseudo-bicolor straight from OIII. Measured rather than assumed — between
# blend 0.00 and 1.00, HOO moves by 0.081 and the other two by exactly
# 0.000000. The dialog greys the slider out for the rest, and
# test_which_palettes_use_the_green_blend_is_measured_not_asserted re-measures
# this so the constant cannot drift away from what _combine actually does.
PALETTES_USING_BLEND = frozenset({"HOO"})

# What each palette does, in the user's terms rather than the formula's. The
# dropdown reads HOO / Pseudo-SHO / Pseudo-bicolor, which tells a newcomer
# nothing about what they are about to get. Colour words are MEASURED: rendering
# pure Ha against pure OIII gives Ha 1.00/0.02/0.00 and OIII 0.00/0.42/0.95 in
# HOO, 0.95/0.42/0.00 and 0.00/0.00/1.00 in Pseudo-SHO, and 0.88/0.00/0.88 and
# 0.00/1.00/0.00 in Pseudo-bicolor — and a test re-measures it, because a
# description that drifts from the picture is worse than no description.
PALETTE_DESCRIPTIONS = {
    "HOO": "Hydrogen red, oxygen teal. The most natural-looking of the four, "
           "and the only one where Green blend does anything.",
    "Pseudo-SHO": "Hubble-like: hydrogen gold, oxygen blue. Dualband data holds no "
                  "real SII, so hydrogen stands in for it — hence \u201cpseudo\u201d.",
    "Pseudo-bicolor": "Hydrogen magenta, oxygen green. The boldest and least "
                      "natural of the four.",
    GOLD_BLUE: "Gold hydrogen, steel-blue oxygen \u2014 the Hubble look, built from "
               "the differences in your own picture.",
}

# The gold-and-blue palette's own Oxygen strength default (spec D3, Andreas
# 2026-10-08: of 30/60/100% on his five targets, 30 is "a touch of blue" and 100
# "a lot"). NarrowbandParams.oxygen_strength keeps 0.85 because the old palettes
# replay stored projects from it; this one gets its 0.60 from palette_defaults().
GOLD_BLUE_OXYGEN_DEFAULT = 0.60
# D5, hydrogen toward gold. Inside the nebula this palette already paints
# hydrogen at hue 27-32 deg on all five exports; what kept IC 1805 (7.1 deg) and
# M 16 (12.6 deg) red-brown at Protect 40% is the protected ORIGINAL, which
# holds 71% of M 16's coloured pixels below mask 0.1. No change to the gold
# itself moved them (hue 33->45 deg, +40-70% chroma: IC 1805 at most 10.8,
# M 16 12.7). The protect level does, and leaves the sky alone — warm hue and
# chroma (0-255) of the darkest 20% of the frame, at protect 0.40 / 0.25 / 0.20:
#   IC 1805  7.1 / 22.1 / 24.9 deg, sky 3.8 / 3.8 / 3.9 (input 3.8)
#   M 16    12.6 / 17.6 / 20.9 deg, sky 2.4 / 2.4 / 2.5 (input 2.4)
#   IC 1396A 23.9 / 29.2 / 30.2,  NGC 7000 22.1 / 27.8 / 28.9 (both <= 35)
GOLD_BLUE_PROTECT_DEFAULT = 0.20


def palette_defaults(palette: str) -> NarrowbandParams:
    """The parameters a palette starts from. Identical to NarrowbandParams() for
    the three old palettes, so nothing they render can move."""
    if palette == GOLD_BLUE:
        return NarrowbandParams(palette=palette, oxygen_strength=GOLD_BLUE_OXYGEN_DEFAULT,
                                protect_background=GOLD_BLUE_PROTECT_DEFAULT)
    return NarrowbandParams(palette=palette)


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


def render_palette(img: AstroImage, params: NarrowbandParams,
                   has_stars: bool = True) -> AstroImage:
    if params.palette == GOLD_BLUE:
        return _render_gold_blue(img, params, has_stars, None)
    ha, oiii = extract_ha_oiii(img)
    oiii_n = normalize_to_reference(oiii, ha, params.blackpoint)
    # Strength rides on TOP of the match, so the photometry stays honest. An MTF
    # rather than a multiply: x2.0 on a plain multiply would clip bright oxygen.
    oiii_s = brightness(oiii_n, params.oxygen_strength)
    r, g, b = _combine(ha, oiii_s, params.palette, params.blend_amount, params.scnr)
    rgb = np.stack([r, g, b], axis=2).astype(np.float32)
    rgb = highlight_reduction(rgb, params.highlight_reduction)
    rgb = highlight_recover(rgb, params.highlight_recover)
    tinted = AstroImage(np.clip(rgb, 0.0, 1.0).astype(np.float32),
                        is_linear=False, metadata=dict(img.metadata))
    out = saturate(tinted, params.saturation, protect_highlights=has_stars)
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
    m = (x * x * (3.0 - 2.0 * x)).astype(np.float32)                # smoothstep
    # ...then FEATHER it. The smoothstep is per pixel, so the boundary followed
    # the noise: on a real IC 1396A render the steepest step was a full 0->1 in
    # ONE pixel and 4.00% of the frame jumped by more than 0.25, which reads as a
    # hard edge around the nebula. Same constant saturation.py already uses, and
    # a FRACTION of the short edge — so the 640 px preview and the full-resolution
    # Apply get proportionally the same softness.
    from scipy.ndimage import gaussian_filter
    sigma = max(1.0, _MASK_SIGMA_FRAC * min(lum.shape))
    if sigma >= 8.0:
        # Blur at quarter resolution and scale back. The answer is a blur tens of
        # pixels wide, so quarter-resolution sampling sits far above anything it
        # can resolve. Measured on a real 8.3 MP mask: 87 ms against 775 for the
        # direct blur, mean difference 0.003 — invisible in a blend, and it keeps
        # this off the critical path of an Apply that had just been unfrozen.
        from skimage.transform import resize
        small = gaussian_filter(m[::4, ::4], sigma=sigma / 4.0)
        m = resize(small, lum.shape, order=1, preserve_range=True)
    else:
        m = gaussian_filter(m, sigma=sigma)      # small frame: blur it directly
    return np.clip(m, 0.0, 1.0).astype(np.float32)


# --- "SHO-style (gold and blue)" -------------------------------------------
# Recipe R6 of docs/superpowers/research/2026-10-08-narrowband-prior-art.md §9.
# After the oxygen match nearly every nebula pixel has the SAME oxygen share
# t = O/(Ha+O) (0.36-0.50 on his five exports), so colouring by t itself paints
# one muddy in-between colour. Colouring by t RELATIVE to the picture's own
# spread separates the gases, and building the colour in OKLab lets the gold
# <-> steel-blue transition pass through a quiet neutral instead of green.

_OK_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                   [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
_OK_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                   [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]])
# float32 throughout the image path: float64 made this palette 2.3 s against
# Pseudo-SHO's 1.0 s on an 11.5 MP frame. Against the float64 bench renders of
# his five exports the output moved by at most 7.2e-7 (1/5000 of an 8-bit level).
_OK_M1_T = np.ascontiguousarray(_OK_M1.T, dtype=np.float32)
_OK_M2_T = np.ascontiguousarray(_OK_M2.T, dtype=np.float32)
_OK_M1_INV_T = np.ascontiguousarray(np.linalg.inv(_OK_M1).T, dtype=np.float32)
_OK_M2_INV_T = np.ascontiguousarray(np.linalg.inv(_OK_M2).T, dtype=np.float32)


def _srgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    c = np.clip(np.asarray(rgb, dtype=np.float32), 0.0, 1.0)
    lin = np.where(c <= 0.04045, c / np.float32(12.92),
                   ((c + np.float32(0.055)) / np.float32(1.055)) ** np.float32(2.4))
    return np.cbrt(lin @ _OK_M1_T) @ _OK_M2_T


def _oklab_to_srgb(lab: np.ndarray) -> np.ndarray:
    lin = ((np.asarray(lab, dtype=np.float32) @ _OK_M2_INV_T) ** 3) @ _OK_M1_INV_T
    lin = np.clip(lin, 0.0, 1.0)
    return np.where(lin <= 0.0031308, np.float32(12.92) * lin,
                    np.float32(1.055) * lin ** np.float32(1 / 2.4) - np.float32(0.055))


def _ab_direction(rgb) -> np.ndarray:
    ab = _srgb_to_oklab(np.array(rgb, dtype=np.float32))[1:].astype(np.float64)
    return (ab / np.hypot(*ab)).astype(np.float32)


_GB_GOLD_RGB = (0.86, 0.58, 0.22)
_GB_STEEL_RGB = (0.25, 0.56, 0.78)
_GB_GOLD = _ab_direction(_GB_GOLD_RGB)
_GB_STEEL = _ab_direction(_GB_STEEL_RGB)

# OKLab chroma at full distance from the picture's middle, at the shared
# Saturation default (0.85). The bench's "vivid" setting, which landed four of
# five targets inside his examples' saturation range (study §9).
_GB_CHROMA = 0.13
_GB_SAT_REF = 0.85
# Shape of the colour ramp away from the middle: below 1 lifts the colour of
# pixels only slightly off the middle (study §9 "vivid").
_GB_GAMMA = 0.6
# Less colour in the darkest parts: full chroma from this OKLab L upward.
_GB_DARK_L = 0.6
# The nebula the centre and spread are measured over: the protect-background
# mask at its default, fixed so moving Protect background never re-colours the
# nebula itself.
_GB_MASK_PROTECT = 0.4
# Stats are measured on a copy no larger than this, block-averaged by the same
# rule as nocturne.ui.preview.downscale (PREVIEW_MAX = 640), so the dialog's
# preview and the full-size Apply measure the identical array (spec D6).
_GB_STATS_EDGE = 640
# The centre and spread are read from t BLURRED by this fraction of the stats
# copy's short edge (as nebula_mask feathers by _MASK_SIGMA_FRAC), so pixel
# noise and the block-average step stop inflating the spread. Measured on a
# pure-Ha synthetic at step 1/2/3 and noise 0.003/0.006/0.01: unblurred
# 0.0126-0.0328 (noise 0.01 at step 1 was 27% blue past the floor), at 0.005
# 0.0114-0.0125 in all nine. His real spreads barely move (M 16 0.0443->0.0432,
# NGC 6992 0.183->0.154; the others within 0.005); 0.015 began to eat them.
_GB_T_SIGMA_FRAC = 0.005

# D4, the floor for hydrogen-only objects. Colour is relative, so a picture
# with no real oxygen would still split into gold and blue along whatever
# variation its oxygen share has. The blue's chroma ramps from 0 at a spread
# (p10-p90 of blurred t on the stats copy) of LO to full at HI. Measured
# 2026-10-08 with the blur above:
#   pure-hydrogen constructions (G=B = a least-squares line in R, i.e. leak and
#   background with the real oxygen taken out, of his five exports):
#     NGC 7000 0.0041, NGC 6992 0.0162, IC 1396A 0.0188, IC 1805 0.0206,
#     M 16 0.0385;  synthetic Ha + 12.7% leak, any size/noise above: <= 0.0132,
#     640x480 near noise-free: 0.0253
#   his five real exports: M 16 0.0432, NGC 7000 0.0518, IC 1805 0.0709,
#     IC 1396A 0.1268, NGC 6992 0.1538
# LO sits above every pure-hydrogen construction but M 16's own (whose fitted
# line still carries M 16's oxygen, so it gets ~0.75); HI is just under M 16,
# the least-spread real picture whose OIII core must stay blue. Synthetic
# 1920x1080 pure Ha: 10.0% blue without the floor, 0.0% with it.
# BLIND SPOT, for the owner: p10-p90 cannot see an oxygen region smaller than
# ~10% of the nebula mask. A small OIII knot in a hydrogen field leaves the
# spread at the hydrogen value, so the floor dims that knot's blue.
GB_FLOOR_SPREAD_LO = 0.028
GB_FLOOR_SPREAD_HI = 0.042
# The gold's chroma relative to the blue's. At x1.00 (with the 20% protect
# default below) warm saturation ran IC 1396A 0.58, IC 1805 0.60, M 16 0.54,
# NGC 6992 0.74, NGC 7000 0.50 against his examples' 0.25-0.55; at x0.85
# 0.51 / 0.54 / 0.51 / 0.65 / 0.44, warm hue 28.9 / 23.6 / 19.5 / 29.2 / 27.1.
# x0.75 cost M 16's hue (18.6) for little.
_GB_GOLD_SCALE = 0.85


@dataclass(frozen=True)
class GoldBlueStats:
    """What the gold-and-blue palette measures from the whole picture. Passed
    from the dialog's preview to Apply so both colour every pixel by the same
    numbers; replay recomputes them from the same downscale and gets the same.

    match:      (OIII black point, MTF midtone) of the oxygen match, or None.
    centre:     median oxygen share over the nebula.
    spread:     its 10th-90th percentile width (never below 1e-4).
    blue_floor: 0..1 scale on the blue's chroma (D4); small spread -> less blue.
    """
    match: tuple[float, float] | None
    centre: float
    spread: float
    blue_floor: float


def _stats_copy(data: np.ndarray) -> np.ndarray:
    """Core twin of nocturne.ui.preview.downscale (no Qt here); a test pins the
    two to the same array."""
    from skimage.transform import downscale_local_mean
    h, w = data.shape[:2]
    step = max(1, max(h, w) // _GB_STATS_EDGE)
    if step == 1:
        return data
    blocks = (step, step, 1) if data.ndim == 3 else (step, step)
    return np.ascontiguousarray(downscale_local_mean(data, blocks).astype(np.float32))


def _oxygen_share(ha: np.ndarray, o: np.ndarray) -> np.ndarray:
    return o / np.maximum(ha + o, 1e-6)


def _blue_floor(spread: float) -> float:
    lo, hi = GB_FLOOR_SPREAD_LO, GB_FLOOR_SPREAD_HI
    if hi <= lo:
        return 1.0
    return float(np.clip((spread - lo) / (hi - lo), 0.0, 1.0))


def gold_blue_stats(img: AstroImage, blackpoint: float = 1.0) -> GoldBlueStats:
    """Measure the gold-and-blue statistics from the preview-sized copy of
    `img` (the image itself when it is already that small)."""
    if not img.is_color:
        raise ValueError("Narrowband needs a colour image")
    small = np.clip(_stats_copy(np.asarray(img.data, dtype=np.float32)), 0.0, 1.0)
    ha = small[..., 0].astype(np.float32)
    oiii = ((small[..., 1] + small[..., 2]) / 2.0).astype(np.float32)
    match = _match_levels(oiii, ha, blackpoint)
    t = _oxygen_share(ha, _apply_match(oiii, match))
    from scipy.ndimage import gaussian_filter
    t = gaussian_filter(t, sigma=max(1e-3, _GB_T_SIGMA_FRAC * min(t.shape)))
    sel = nebula_mask(small, _GB_MASK_PROTECT) > 0.5
    vals = t[sel] if sel.any() else t.ravel()
    centre = float(np.median(vals))
    p10, p90 = np.percentile(vals, [10, 90])
    spread = max(float(p90 - p10), 1e-4)
    return GoldBlueStats(match=match, centre=centre, spread=spread,
                         blue_floor=_blue_floor(spread))


def _render_gold_blue(img: AstroImage, params: NarrowbandParams, has_stars: bool,
                      stats: GoldBlueStats | None) -> AstroImage:
    st = stats if stats is not None else gold_blue_stats(img, params.blackpoint)
    data = np.clip(np.asarray(img.data, dtype=np.float32), 0.0, 1.0)
    ha, oiii = extract_ha_oiii(img)
    t = _oxygen_share(ha, _apply_match(oiii, st.match))
    oxygen = float(params.oxygen_strength)
    # Less oxygen moves the balance point toward oxygen, so fewer pixels turn
    # blue; at 1.0 the picture's own median is the middle.
    centre = st.centre + (1.0 - oxygen) * 0.5 * st.spread
    d = np.clip((t - centre) / st.spread, -0.5, 0.5) * 2.0       # -1 hydrogen .. +1 oxygen
    w = np.abs(d) ** _GB_GAMMA                                     # 0 at the middle: never green
    chroma = _GB_CHROMA * max(0.0, float(params.saturation)) / _GB_SAT_REF
    blue = d > 0
    gold_amt = chroma * w * _GB_GOLD_SCALE
    blue_amt = chroma * w * oxygen * st.blue_floor
    amt = np.where(blue, blue_amt, gold_amt)
    lab = _srgb_to_oklab(data)
    L = lab[..., 0]
    amt = amt * np.clip(L / _GB_DARK_L, 0.0, 1.0)
    if has_stars:
        # Stars are still in this layer: leave the brightest white rather than
        # tint them by whatever share their colour happens to give. The 0.15
        # width in L is a JUDGEMENT, not a measurement — no star-bearing frame
        # was benched (the bench is starless; stars are screened back).
        amt = amt * np.clip((1.0 - L) / np.float32(0.15), 0.0, 1.0)
    direction = np.where(blue[..., None], _GB_STEEL, _GB_GOLD)
    lab[..., 1:] = direction * amt[..., None]
    rgb = _oklab_to_srgb(lab).astype(np.float32)
    rgb = highlight_reduction(rgb, params.highlight_reduction)
    rgb = highlight_recover(rgb, params.highlight_recover)
    return AstroImage(np.clip(rgb, 0.0, 1.0).astype(np.float32),
                      is_linear=False, metadata=dict(img.metadata))


def render(img: AstroImage, params: NarrowbandParams, *,
           has_stars: bool = True, stats: GoldBlueStats | None = None) -> AstroImage:
    """Render the palette, preserve lightness, and optionally confine the
    recolour to the nebula. The single engine entry point the UI/step drive.

    `has_stars=False` says this layer is starless, which lets the saturation
    boost reach the nebula core instead of being tapered away from it. The
    CALLER decides, because narrowband is not always starless: without StarX
    configured both the dialog and the step recolour the whole frame, stars
    included, and there the taper is still doing its job.

    `stats` is read by the gold-and-blue palette only (see gold_blue_stats);
    without it the palette measures them from this image's preview-sized copy.
    That palette always keeps the picture's own lightness, so Preserve
    lightness does not apply to it."""
    if not img.is_color:
        raise ValueError("Narrowband needs a colour image")
    original = np.clip(img.data, 0.0, 1.0)
    if params.palette == GOLD_BLUE:
        out = _render_gold_blue(img, params, has_stars, stats)
    else:
        out = render_palette(img, params, has_stars)
    if params.lightness_preserve and params.palette != GOLD_BLUE:
        out = AstroImage(preserve_lightness(out.data, original),
                         is_linear=False, metadata=dict(img.metadata))
    # Brightness is applied to the FINAL image (after the lightness step) so the
    # slider always works — under Preserve lightness it would otherwise be
    # overwritten by the original's L* and appear dead.
    out = AstroImage(brightness(out.data, params.brightness),
                     is_linear=False, metadata=dict(img.metadata))
    if params.protect_background > 0:
        m = nebula_mask(original, params.protect_background)[..., None]
        blended = m * out.data + (1.0 - m) * original
        out = AstroImage(np.clip(blended, 0.0, 1.0).astype(np.float32),
                         is_linear=False, metadata=dict(img.metadata))
    return out
