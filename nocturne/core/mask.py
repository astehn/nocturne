from __future__ import annotations

import numpy as np
from skimage.filters import gaussian

# Blur radius as a FRACTION of the shorter side, never a pixel count: a
# decimated preview and a full-resolution apply must select the same structure,
# which is what keeps the preview equal to the export.
#
# 0.005 is the smallest swept value whose speckle falls below one 8-bit step,
# i.e. below what the mask could express at all. Measured on NGC 7000 (163x20s)
# and the M 31 mosaic, band edge placed ON the sky level — the worst case, where
# the sky's own noise straddles the ramp. Mean neighbouring-pixel difference of
# the mask over sky, at the default feather:
#
#     blur      NGC 7000    M 31
#     none        0.1364    0.1169     <- an eighth of the mask's range, on noise
#     0.002       0.0068    0.00041
#     0.005       0.0020    0.00041    <- both under 1/255 = 0.0039
#     0.020       0.00047   0.00039
#
# Larger values keep helping but buy nothing visible and cost mask fidelity.
_SMOOTH_FRAC = 0.005

# Sky noise after the stretch measured 0.0057 (NGC 7000) and 0.0057 (M 31), so
# this default ramp is ~14x the noise it has to ride over. A feather of 0.02 is
# only 3.5x it and speckles an order of magnitude worse at any blur setting.
_FEATHER = 0.08

_MIN_PRESET_SPAN = 0.05   # a preset must never hand back an empty band


def smoothstep(x: np.ndarray, a: float, b: float) -> np.ndarray:
    """Hermite ramp from 0 at `a` to 1 at `b`.

    Private copies of this live in saturation.py, enhance.py and hdr.py; this is
    the public one. Those three are deliberately left alone — migrating them
    would touch three tested modules for no change in behaviour.
    """
    t = np.clip((x - a) / max(float(b) - float(a), 1e-6), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def range_mask(lum: np.ndarray, lo: float, hi: float,
               feather: float = _FEATHER,
               smooth_frac: float = _SMOOTH_FRAC) -> np.ndarray:
    """Select the luminance BAND between `lo` and `hi`, softly.

    Every other mask here is one-sided — zero at sky, ramping to 1 as signal
    rises, then flat — so "the galaxy's arms but not its core" could not be
    expressed at all, whichever adjustment it fed.

    The ramps sit OUTSIDE the band, so inside [lo, hi] the mask is exactly 1
    whatever the feather, and lo=0/hi=1 is exactly 1 everywhere. Ramps placed
    inside would need a clamp to stop them overlapping, and getting that clamp
    wrong applies the caller's effect at partial strength everywhere with no
    control to explain it.

    The luminance is blurred BEFORE the band is applied, not after: "is this
    pixel in the band" has to be answered from signal, because a per-pixel
    decision on noisy data gives a speckled mask, and anything applied through a
    speckled mask arrives as noise.
    """
    lum = np.clip(np.asarray(lum, dtype=np.float32), 0.0, 1.0)
    if smooth_frac > 0.0 and lum.ndim == 2:
        sigma = max(1.0, float(smooth_frac) * min(lum.shape))
        lum = gaussian(lum, sigma=sigma, preserve_range=True).astype(np.float32)
    f = max(float(feather), 0.0)
    if f > 0.0:
        rise = smoothstep(lum, lo - f, lo)
        fall = 1.0 - smoothstep(lum, hi, hi + f)
    else:
        rise = (lum >= lo).astype(np.float32)
        fall = (lum <= hi).astype(np.float32)
    return np.clip(rise * fall, 0.0, 1.0).astype(np.float32)


BAND_PRESETS = ("Whole image", "Bright areas", "Midtones", "Object, not the core")

# How many sky-sigmas above the sky level each preset's bounds sit. Measured on
# the stretched M 31 mosaic (sky 0.256, sigma 0.041): the arms only separate
# from the sky above ~3 sigma, and the core sits above ~12.
_PRESET_SIGMAS = {
    "Bright areas": (3.0, None),
    "Midtones": (2.0, 8.0),
    "Object, not the core": (3.0, 12.0),
}


def band_preset(lum: np.ndarray, name: str) -> tuple[float, float]:
    """Band bounds for a named preset, derived from THIS image's statistics.

    Absolute constants cannot work. On a stretched M 31 mosaic the sky sits at
    0.256, so a fixed band of 0.12..0.80 — which is what the design originally
    specified — contains the entire sky and selects 87% of the frame, the exact
    inverse of "the object". Rendered, it masked everything except the core.

    The bounds returned are absolute, and that is what gets stored: the preset
    is a starting point computed once from the image in front of you, not a mode
    that silently re-fits itself on every image a recipe touches.
    """
    if name == "Whole image":
        return (0.0, 1.0)
    if name not in _PRESET_SIGMAS:
        raise ValueError(f"unknown band preset: {name!r} (expected one of {BAND_PRESETS})")

    lum = np.asarray(lum, dtype=np.float32)
    v = lum[lum > 0.0]                     # a mosaic is zero-padded outside its footprint
    if v.size == 0:
        return (0.0, 1.0)
    med = float(np.median(v))
    below = v[v < med]
    sigma = max(float(below.std()) if below.size else 0.0, 1e-3)

    lo_k, hi_k = _PRESET_SIGMAS[name]
    lo = med + lo_k * sigma
    hi = 1.0 if hi_k is None else med + hi_k * sigma
    # A bright image can push both bounds past 1.0; an empty band would make the
    # tool silently inert, so keep a usable span at the top of the range instead.
    lo = float(np.clip(lo, 0.0, 1.0 - 2 * _MIN_PRESET_SPAN))
    hi = float(np.clip(hi, lo + _MIN_PRESET_SPAN, 1.0))
    return (lo, hi)
