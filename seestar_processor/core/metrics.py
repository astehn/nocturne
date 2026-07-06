from __future__ import annotations

import numpy as np

from .autostretch import autostretch
from .image import AstroImage


def _display(img: AstroImage) -> np.ndarray:
    """The image as the preview shows it — autostretched when linear, clipped
    otherwise. Matches `ui.preview.to_qimage` so the delta reflects the visible
    change, not raw linear values (which are tiny, ~0.003, making every change
    round to ~0%)."""
    if img.is_linear:
        return autostretch(img).astype(np.float32)
    return np.clip(img.data, 0.0, 1.0).astype(np.float32)


def rms_delta(before: AstroImage, after: AstroImage) -> float | None:
    """Root-mean-square difference between two images, as a percent of full
    scale, measured on their displayed (autostretched) representation so the
    number reflects the visible change. Returns None when the shapes differ
    (e.g. after a crop)."""
    if before.data.shape != after.data.shape:
        return None
    diff = _display(after) - _display(before)
    return float(np.sqrt(np.mean(diff * diff)) * 100.0)
