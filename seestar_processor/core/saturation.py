from __future__ import annotations

import numpy as np

from .image import AstroImage


def saturate(img: AstroImage, amount: float) -> AstroImage:
    """Increase colour saturation. `amount` in [0, 1] maps to a chroma factor
    1.0..2.0. Mono images are returned unchanged."""
    if not img.is_color or amount <= 0:
        return img.copy()
    factor = 1.0 + float(amount)
    data = img.data
    lum = data.mean(axis=2, keepdims=True)
    out = np.clip(lum + (data - lum) * factor, 0.0, 1.0)
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear, metadata=dict(img.metadata))
