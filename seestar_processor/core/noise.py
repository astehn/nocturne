from __future__ import annotations

import numpy as np
from skimage.restoration import denoise_tv_chambolle

from .image import AstroImage


def reduce_noise(img: AstroImage, strength: float) -> AstroImage:
    """Free total-variation denoising fallback for noise reduction.

    `strength` in [0, 1] maps to the TV regularization weight.
    """
    channel_axis = -1 if img.is_color else None
    weight = 0.01 + float(strength) * 0.12
    out = denoise_tv_chambolle(img.data, weight=weight, channel_axis=channel_axis)
    return AstroImage(
        np.clip(out, 0.0, 1.0).astype(np.float32),
        is_linear=img.is_linear,
        metadata=dict(img.metadata),
    )
