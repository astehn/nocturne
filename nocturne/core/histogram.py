from __future__ import annotations

import numpy as np

from .image import AstroImage


def histogram(img: AstroImage, bins: int = 256) -> dict:
    """Per-channel pixel counts over [0, 1]. Color -> {'r','g','b'}, mono -> {'l'}."""
    data = np.clip(img.data, 0.0, 1.0)
    if data.ndim == 2:
        counts, _ = np.histogram(data, bins=bins, range=(0.0, 1.0))
        return {"l": counts}
    out = {}
    for i, key in enumerate(("r", "g", "b")):
        counts, _ = np.histogram(data[..., i], bins=bins, range=(0.0, 1.0))
        out[key] = counts
    return out
