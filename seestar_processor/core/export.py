from __future__ import annotations

import numpy as np
import tifffile
from PIL import Image

from .image import AstroImage


def _to_uint(data: np.ndarray, bits: int) -> np.ndarray:
    maxval = (2 ** bits) - 1
    clipped = np.clip(data, 0.0, 1.0)
    dtype = np.uint16 if bits == 16 else np.uint8
    return (clipped * maxval + 0.5).astype(dtype)


def save_tiff(img: AstroImage, path: str) -> None:
    # 16-bit TIFF for both mono and color (preserves dynamic range for further
    # editing). Pillow cannot write 16-bit RGB reliably, so use tifffile.
    tifffile.imwrite(path, _to_uint(img.data, 16))


def save_jpeg(img: AstroImage, path: str, quality: int = 95) -> None:
    arr = _to_uint(img.data, 8)
    mode = "L" if arr.ndim == 2 else "RGB"
    Image.fromarray(arr, mode=mode).save(path, format="JPEG", quality=quality)
