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
    # unsharp_mask can occasionally hand back non-finite values (a sticky CPU
    # FP-exception flag left by unrelated numpy work upstream leaks into its
    # compiled path). A processing step must never emit NaN — that would corrupt
    # the export — so coerce any non-finite pixel to a defined value before clip.
    out = np.nan_to_num(out, nan=0.0, posinf=1.0, neginf=0.0)
    return AstroImage(
        np.clip(out, 0.0, 1.0).astype(np.float32),
        is_linear=img.is_linear,
        metadata=dict(img.metadata),
    )
