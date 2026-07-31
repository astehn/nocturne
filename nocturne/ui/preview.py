from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage

from ..core.autostretch import autostretch
from ..core.image import AstroImage, finite_or_zero


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
