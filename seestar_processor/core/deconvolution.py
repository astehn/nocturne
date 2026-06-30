from __future__ import annotations

import numpy as np
from skimage.filters import unsharp_mask

from .image import AstroImage


def sharpen(img: AstroImage, strength: float) -> AstroImage:
    """Free high-pass (unsharp-mask) sharpening fallback for deconvolution.

    `strength` in [0, 1] maps to the unsharp-mask amount.
    """
    channel_axis = -1 if img.is_color else None
    out = unsharp_mask(
        img.data,
        radius=2.0,
        amount=float(strength) * 2.0,
        channel_axis=channel_axis,
        preserve_range=True,
    )
    return AstroImage(
        np.clip(out, 0.0, 1.0).astype(np.float32),
        is_linear=img.is_linear,
        metadata=dict(img.metadata),
    )
