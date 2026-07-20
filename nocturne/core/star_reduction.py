from __future__ import annotations

import numpy as np

from .image import AstroImage


def reduce_stars(starless: AstroImage, stars: AstroImage, amount: float) -> AstroImage:
    """Shrink + dim the stars via a wing-taper curve, then screen-recombine with
    the starless image.

    Raising the star layer to a power > 1 crushes the dim halo/wings — shrinking
    each star's apparent size — while leaving the bright core a sharp point. So
    stars get smaller *without* the soft blobs a `grey_erosion` leaves behind, and
    faint stars are merely dimmed rather than eroded away entirely. `amount` 0
    leaves the stars untouched; higher = smaller, dimmer stars.
    """
    amount = float(np.clip(amount, 0.0, 1.0))
    s = np.clip(stars.data.astype(np.float32), 0.0, 1.0)
    gamma = 1.0 + amount * 2.5          # 0 -> gamma 1 (no change); 1 -> gamma 3.5
    reduced = s ** gamma
    base = starless.data.astype(np.float32)
    out = 1.0 - (1.0 - base) * (1.0 - reduced)
    return AstroImage(
        np.clip(out, 0.0, 1.0).astype(np.float32),
        is_linear=starless.is_linear,
        metadata=dict(starless.metadata),
    )
