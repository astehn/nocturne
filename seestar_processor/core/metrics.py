from __future__ import annotations

import numpy as np

from .image import AstroImage


def rms_delta(before: AstroImage, after: AstroImage) -> float | None:
    """Root-mean-square difference between two images as a percent of full scale.
    Returns None when the shapes differ (e.g. after a crop)."""
    if before.data.shape != after.data.shape:
        return None
    diff = after.data.astype(np.float32) - before.data.astype(np.float32)
    return float(np.sqrt(np.mean(diff * diff)) * 100.0)
