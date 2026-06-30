from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .image import AstroImage

# Aspect ratios expressed as width / height. None == keep original.
_ASPECT = {"Original": None, "1:1": 1.0, "16:9": 16 / 9, "4:5": 4 / 5, "3:2": 3 / 2}
_TRIM = {"None": 0.0, "5%": 0.05, "10%": 0.10, "15%": 0.15}

ASPECTS = list(_ASPECT)
TRIMS = list(_TRIM)


@dataclass
class CropSettings:
    aspect: str = "Original"
    trim: str = "None"
    rotate: int = 0  # clockwise degrees: 0, 90, 180, 270
    flip_h: bool = False
    flip_v: bool = False


def _center_crop_to_ratio(data: np.ndarray, ratio: float) -> np.ndarray:
    h, w = data.shape[:2]
    if w / h > ratio:  # too wide -> trim width
        new_w = max(1, round(h * ratio))
        x0 = (w - new_w) // 2
        return data[:, x0:x0 + new_w]
    new_h = max(1, round(w / ratio))  # too tall -> trim height
    y0 = (h - new_h) // 2
    return data[y0:y0 + new_h, :]


def apply_crop(img: AstroImage, settings: CropSettings) -> AstroImage:
    data = img.data

    k = (settings.rotate // 90) % 4
    if k:
        data = np.rot90(data, -k)  # negative k => clockwise

    if settings.flip_h:
        data = data[:, ::-1]
    if settings.flip_v:
        data = data[::-1, :]

    frac = _TRIM.get(settings.trim, 0.0)
    if frac > 0:
        h, w = data.shape[:2]
        dh, dw = int(h * frac), int(w * frac)
        data = data[dh:h - dh, dw:w - dw]

    ratio = _ASPECT.get(settings.aspect)
    if ratio is not None:
        data = _center_crop_to_ratio(data, ratio)

    return AstroImage(
        np.ascontiguousarray(data.astype(np.float32)),
        is_linear=img.is_linear,
        metadata=dict(img.metadata),
    )
