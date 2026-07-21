from __future__ import annotations

import numpy as np
from skimage.filters import gaussian

from .image import AstroImage


def saturate(img: AstroImage, amount: float) -> AstroImage:
    """Re-centred saturation: amount 0=greyscale, 0.5=native, 1=strong boost.
    The boost above native peaks in the nebula midtones and tapers toward BOTH
    the noisy background (so heavy boosts don't detonate colour noise) and bright
    stars (so they keep natural colour); desaturation is uniform. Mono unchanged."""
    if not img.is_color:
        return img.copy()
    S_MAX = 2.5
    t = float(amount)
    data = img.data
    lum = data.mean(axis=2, keepdims=True)
    if t <= 0.5:
        s_px = 2.0 * t                          # 0 -> grey, 0.5 -> native (uniform)
    else:
        s = 1.0 + (2.0 * t - 1.0) * (S_MAX - 1.0)
        # Weight the boost to the midtones: shadow-protect fades it out in the
        # dark (noisy) background; (1 - lum) fades it out toward the highlights.
        shadow_protect = np.clip((lum - 0.12) / 0.18, 0.0, 1.0)  # ~0 below .12, 1 by .30
        s_px = 1.0 + (s - 1.0) * shadow_protect * (1.0 - lum)
    out = np.clip(lum + (data - lum) * s_px, 0.0, 1.0)
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear,
                      metadata=dict(img.metadata))


_MASK_LO_PCT = 25.0        # sky level percentile (mask floor)
_MASK_HI_PCT = 60.0        # low-nebula percentile (mask ramps to 1 by here)
_MASK_SIGMA_FRAC = 0.015   # feather radius as a fraction of the short edge
_GAIN = 1.5                # max chroma boost multiplier at strength 1, mask 1


def _smoothstep(x, a, b):
    t = np.clip((x - a) / max(float(b) - float(a), 1e-6), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _nebula_mask(lum: np.ndarray) -> np.ndarray:
    """A sky-anchored, feathered mask: 0 at/below the sky level, ramping to 1 as
    signal rises above it. `lum` is a 2-D luminance array in [0,1]."""
    lo, hi = np.percentile(lum, [_MASK_LO_PCT, _MASK_HI_PCT])
    m = _smoothstep(lum, lo, hi).astype(np.float32)
    h, w = lum.shape
    sigma = max(1.0, _MASK_SIGMA_FRAC * min(h, w))
    return gaussian(m, sigma=sigma, preserve_range=True).astype(np.float32)


def nebula_saturate(starless: AstroImage, stars: AstroImage,
                    strength: float) -> AstroImage:
    """Boost chroma on the starless layer within the nebula mask, then screen the
    untouched stars back on top — so only nebulosity gains colour (sky and stars
    are unchanged). `strength` 0 = plain recombine."""
    strength = float(np.clip(strength, 0.0, 1.0))
    base = np.clip(starless.data.astype(np.float32), 0.0, 1.0)
    st = np.clip(stars.data.astype(np.float32), 0.0, 1.0)
    if base.ndim == 3 and strength > 0.0:
        lum = base.mean(axis=2, keepdims=True)
        m = _nebula_mask(base.mean(axis=2))[:, :, None]
        base = np.clip(lum + (base - lum) * (1.0 + _GAIN * strength * m), 0.0, 1.0)
    out = 1.0 - (1.0 - base) * (1.0 - st)
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=starless.is_linear, metadata=dict(starless.metadata))
