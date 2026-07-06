from __future__ import annotations

import numpy as np
from skimage.exposure import equalize_adapthist

from .image import AstroImage


def enhance(img: AstroImage, amount: float) -> AstroImage:
    """Local-contrast (CLAHE) boost on luminance, blended by `amount` in [0, 1].
    Color is rescaled by the luminance ratio so hue is preserved."""
    amount = float(np.clip(amount, 0.0, 1.0))
    data = np.clip(img.data, 0.0, 1.0).astype(np.float32)
    if data.ndim == 2:
        clahe = equalize_adapthist(data, clip_limit=0.01).astype(np.float32)
        out = data * (1 - amount) + clahe * amount
        return AstroImage(
            np.clip(out, 0.0, 1.0).astype(np.float32),
            is_linear=img.is_linear, metadata=dict(img.metadata),
        )
    lum = data.mean(axis=2)
    clahe = equalize_adapthist(lum, clip_limit=0.01).astype(np.float32)
    new_lum = lum * (1 - amount) + clahe * amount
    ratio = new_lum / np.maximum(lum, 1e-6)
    out = np.clip(data * ratio[..., None], 0.0, 1.0)
    return AstroImage(
        out.astype(np.float32), is_linear=img.is_linear, metadata=dict(img.metadata)
    )
