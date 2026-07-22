from __future__ import annotations

import numpy as np
from skimage.filters import gaussian

from .image import AstroImage

_SIGMA = 1.5   # gaussian radius for the high-pass; tight, suits undersampled Seestar stars


def sharpen(img: AstroImage, strength: float) -> AstroImage:
    """Free unsharp-mask sharpening fallback for deconvolution (used when RC-Astro
    BlurXTerminator is absent). `strength` in [0, 1] maps to the unsharp amount.

    Implemented directly as a gaussian high-pass — `out = img + amount*(img - blur)`
    — rather than via `skimage.filters.unsharp_mask`, which misbehaves badly on the
    faint LINEAR data this step runs on: it collapses bright star cores to 0 and
    blows other pixels up to ~1e34, so it destroyed stars while appearing to do
    nothing at any strength.
    """
    amount = float(strength) * 2.0
    channel_axis = -1 if img.is_color else None
    data = img.data.astype(np.float32)
    blur = gaussian(data, sigma=_SIGMA, channel_axis=channel_axis, preserve_range=True)
    out = data + amount * (data - blur)
    # Belt-and-braces: never emit non-finite pixels (they would corrupt the export).
    out = np.nan_to_num(out, nan=0.0, posinf=1.0, neginf=0.0)
    return AstroImage(
        np.clip(out, 0.0, 1.0).astype(np.float32),
        is_linear=img.is_linear,
        metadata=dict(img.metadata),
    )
