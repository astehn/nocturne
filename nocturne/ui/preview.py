from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage

from ..core.autostretch import autostretch
from ..core.image import AstroImage


def rgb_to_qimage(rgb: np.ndarray) -> QImage:
    """Wrap a uint8 H×W×3 RGB array in a detached QImage."""
    rgb = np.ascontiguousarray(rgb)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def to_qimage(img: AstroImage) -> QImage:
    data = autostretch(img) if img.is_linear else np.clip(img.data, 0.0, 1.0)
    if data.ndim == 2:
        data = np.repeat(data[:, :, None], 3, axis=2)
    rgb = (data * 255 + 0.5).astype(np.uint8)
    return rgb_to_qimage(rgb)
