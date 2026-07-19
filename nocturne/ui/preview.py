from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage

from ..core.autostretch import autostretch, unlinked_stretch
from ..core.image import AstroImage


def to_qimage(img: AstroImage, unlinked: bool = False) -> QImage:
    if img.is_linear:
        data = unlinked_stretch(img.data) if unlinked else autostretch(img)
    else:
        data = np.clip(img.data, 0.0, 1.0)
    if data.ndim == 2:
        data = np.repeat(data[:, :, None], 3, axis=2)
    rgb = (data * 255 + 0.5).astype(np.uint8)
    rgb = np.ascontiguousarray(rgb)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
