from __future__ import annotations

import numpy as np
from scipy.ndimage import grey_erosion

from .image import AstroImage


def reduce_stars(starless: AstroImage, stars: AstroImage, amount: float) -> AstroImage:
    """Shrink + dim the stars layer and screen-recombine with the starless image."""
    amount = float(np.clip(amount, 0.0, 1.0))
    s = stars.data.astype(np.float32)
    size = 1 + int(round(amount * 3))  # erosion footprint grows with amount
    if s.ndim == 3:
        eroded = np.stack(
            [grey_erosion(s[..., c], size=(size, size)) for c in range(3)], axis=2
        )
    else:
        eroded = grey_erosion(s, size=(size, size))
    reduced = eroded * (1.0 - 0.4 * amount)
    base = starless.data.astype(np.float32)
    out = 1.0 - (1.0 - base) * (1.0 - reduced)
    return AstroImage(
        np.clip(out, 0.0, 1.0).astype(np.float32),
        is_linear=starless.is_linear,
        metadata=dict(starless.metadata),
    )
