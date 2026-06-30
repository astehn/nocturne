from __future__ import annotations

import numpy as np

from .image import AstroImage


def detect_content_bounds(img: AstroImage, threshold: float = 0.002) -> tuple[int, int, int, int]:
    """Find (top, bottom, left, right) of the non-black content rectangle left
    after stacking/dithering (rows/cols whose mean exceeds `threshold`)."""
    data = img.data
    gray = data.mean(axis=2) if data.ndim == 3 else data
    rows = np.where(gray.mean(axis=1) > threshold)[0]
    cols = np.where(gray.mean(axis=0) > threshold)[0]
    if rows.size == 0 or cols.size == 0:
        return 0, gray.shape[0], 0, gray.shape[1]
    return int(rows[0]), int(rows[-1] + 1), int(cols[0]), int(cols[-1] + 1)


def auto_crop(img: AstroImage, margin: float = 0.0) -> AstroImage:
    """Crop to the detected content rectangle, then trim an extra `margin`
    fraction off each side."""
    top, bottom, left, right = detect_content_bounds(img)
    data = img.data[top:bottom, left:right]
    if margin > 0:
        h, w = data.shape[:2]
        dh, dw = int(h * margin), int(w * margin)
        data = data[dh:h - dh, dw:w - dw]
    return AstroImage(
        np.ascontiguousarray(data.astype(np.float32)),
        is_linear=img.is_linear,
        metadata=dict(img.metadata),
    )
