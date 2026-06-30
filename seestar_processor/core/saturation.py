from __future__ import annotations

import numpy as np

from .image import AstroImage


def saturate(img: AstroImage, amount: float) -> AstroImage:
    """Increase colour saturation, lightness-aware: the boost fades toward bright
    pixels so stars/highlights keep natural colour. Mono is returned unchanged."""
    if not img.is_color or amount <= 0:
        return img.copy()
    data = img.data
    lum = data.mean(axis=2, keepdims=True)
    factor = 1.0 + float(amount) * (1.0 - lum)  # full boost in shadows, ~none in highlights
    out = np.clip(lum + (data - lum) * factor, 0.0, 1.0)
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear, metadata=dict(img.metadata))
