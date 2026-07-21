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
