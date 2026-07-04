from __future__ import annotations

import numpy as np

from .image import AstroImage


def saturate(img: AstroImage, amount: float) -> AstroImage:
    """Re-centred saturation: amount 0=greyscale, 0.5=native, 1=strong boost.
    The boost above native tapers toward highlights so bright stars keep natural
    colour; desaturation is uniform. Mono is returned unchanged."""
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
        s_px = 1.0 + (s - 1.0) * (1.0 - lum)    # taper boost toward highlights
    out = np.clip(lum + (data - lum) * s_px, 0.0, 1.0)
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear,
                      metadata=dict(img.metadata))
