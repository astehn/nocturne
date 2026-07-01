from __future__ import annotations

import glob
import os

import numpy as np

from ..core.fits_io import load_fits
from ..core.image import AstroImage


def discover_subs(folder: str) -> list[str]:
    files: list[str] = []
    for pattern in ("*.fit", "*.fits", "*.fts"):
        files.extend(glob.glob(os.path.join(folder, pattern)))
    return sorted(files)


def load_sub(path: str) -> AstroImage:
    return load_fits(path)


def luminance(data: np.ndarray) -> np.ndarray:
    if data.ndim == 2:
        return np.ascontiguousarray(data, dtype=np.float32)
    return np.ascontiguousarray(data.mean(axis=2), dtype=np.float32)
