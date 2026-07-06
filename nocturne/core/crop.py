from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .image import AstroImage

# Aspect ratios as width / height. None == keep as-is.
_ASPECT = {"Original": None, "1:1": 1.0, "16:9": 16 / 9, "4:5": 4 / 5, "3:2": 3 / 2}
ASPECTS = list(_ASPECT)


@dataclass
class CropParams:
    bounds: tuple[int, int, int, int] | None = None  # (top, bottom, left, right), input coords
    aspect: str = "Original"
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


def apply_crop_params(img: AstroImage, params: CropParams | None) -> AstroImage:
    params = params or CropParams()
    data = img.data
    if params.bounds is not None:
        t, b, l, r = params.bounds
        data = data[t:b, l:r]
    k = (params.rotate // 90) % 4
    if k:
        data = np.rot90(data, -k)  # clockwise
    if params.flip_h:
        data = data[:, ::-1]
    if params.flip_v:
        data = data[::-1, :]
    ratio = _ASPECT.get(params.aspect)
    if ratio is not None:
        data = _center_crop_to_ratio(data, ratio)
    return AstroImage(
        np.ascontiguousarray(data.astype(np.float32)),
        is_linear=img.is_linear,
        metadata=dict(img.metadata),
    )


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
