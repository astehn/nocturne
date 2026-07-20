from __future__ import annotations

import numpy as np

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
