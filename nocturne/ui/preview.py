from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage

from ..core.autostretch import autostretch
from ..core.image import AstroImage, finite_or_zero


# Long edge of a live preview. Big enough to judge colour and structure,
# small enough that a slider tick recomputes in milliseconds.
PREVIEW_MAX = 640


def downscale(img: AstroImage, max_edge: int = PREVIEW_MAX) -> AstroImage:
    """Shrink for the live preview by AVERAGING each block, not by sampling one
    pixel in every N.

    Striding is cheaper and destroys a star field: measured on 300 synthetic 3x3
    stars decimated 8x, 253 vanished entirely and the 47 survivors were drawn at
    full amplitude, which is the hard single-pixel look. Averaging keeps every
    star and conserves flux exactly, for a few hundred milliseconds once — after
    a star split that already takes seconds.
    """
    from skimage.transform import downscale_local_mean
    h, w = img.data.shape[:2]
    step = max(1, max(h, w) // max_edge)
    if step == 1:
        return img
    blocks = (step, step, 1) if img.data.ndim == 3 else (step, step)
    small = downscale_local_mean(img.data, blocks).astype(np.float32)
    return AstroImage(np.ascontiguousarray(small),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def rgb_to_qimage(rgb: np.ndarray) -> QImage:
    """Wrap a uint8 H×W×3 RGB array in a detached QImage."""
    rgb = np.ascontiguousarray(rgb)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def to_rgb8(img: AstroImage) -> np.ndarray:
    """The uint8 H×W×3 array the canvas displays. Linear images are autostretched
    for display only — the underlying data is untouched, which is why the hover
    readout reports data values and labels them 'linear'.

    Non-finite values are replaced with 0.0 before the uint8 cast (see
    image.finite_or_zero), matching histogram._counts_256 and export._to_uint,
    so the canvas, the histogram and the exported file agree and no
    RuntimeWarning is emitted. This guard is the last line, not the only one:
    it can only paint a NaN pixel black, and until _stretch_params was made
    NaN-aware it faithfully painted a whole autostretch-poisoned channel black
    instead."""
    data = autostretch(img) if img.is_linear else np.clip(img.data, 0.0, 1.0)
    if data.ndim == 2:
        data = np.repeat(data[:, :, None], 3, axis=2)
    return (finite_or_zero(data) * 255 + 0.5).astype(np.uint8)


def to_qimage(img: AstroImage) -> QImage:
    return rgb_to_qimage(to_rgb8(img))
