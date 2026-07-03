from __future__ import annotations

import numpy as np
from astropy.io import fits
from skimage.transform import resize

from ..core.fits_io import _bayer_pattern


def load_cfa(path: str) -> tuple:
    """Load a raw 2D CFA sub: (cfa float32, pattern, exptime). Raises ValueError
    for a 3D/already-debayered file."""
    with fits.open(path) as hdul:
        data = np.asarray(hdul[0].data)
        header = hdul[0].header
    if data.ndim != 2:
        raise ValueError("Ha/OIII extraction needs raw (un-debayered) subs")
    exp = float(header.get("EXPTIME", 0.0) or 0.0)
    return data.astype(np.float32), _bayer_pattern(header), exp


def _site_offsets(pattern: str) -> dict:
    """Map each colour to its (row, col) offsets within the 2x2 CFA tile."""
    offsets: dict = {"R": [], "G": [], "B": []}
    for i, ch in enumerate(pattern.upper()):
        offsets[ch].append((i // 2, i % 2))
    return offsets


def _plane(cfa: np.ndarray, sites: list) -> np.ndarray:
    """Mean of the half-res sub-planes at the given (row, col) site offsets."""
    parts = [cfa[r::2, c::2] for r, c in sites]
    return np.mean(parts, axis=0).astype(np.float32)


def extract_cfa_planes(cfa: np.ndarray, pattern: str) -> tuple:
    """(ha, oiii) full-res float32. Ha = red sites; OIII = (green + blue)/2.
    Half-res planes are bilinearly upscaled to the CFA's full (H, W)."""
    if cfa.ndim != 2:
        raise ValueError("extract_cfa_planes needs a 2D CFA frame")
    off = _site_offsets(pattern)
    red = _plane(cfa, off["R"])
    green = _plane(cfa, off["G"])
    blue = _plane(cfa, off["B"])
    oiii_half = (green + blue) / 2.0
    shape = cfa.shape
    ha = resize(red, shape, order=1, preserve_range=True, anti_aliasing=False).astype(np.float32)
    oiii = resize(oiii_half, shape, order=1, preserve_range=True,
                  anti_aliasing=False).astype(np.float32)
    return ha, oiii


def _mad(x: np.ndarray) -> float:
    return float(np.median(np.abs(x - np.median(x))))


def renorm_oiii(ha: np.ndarray, oiii: np.ndarray) -> np.ndarray:
    """Linear-fit OIII to Ha (Siril ExtractHaOIII): match median and MAD."""
    mad_o = _mad(oiii)
    a = (_mad(ha) / mad_o) if mad_o > 1e-9 else 1.0
    out = a * (oiii - np.median(oiii)) + np.median(ha)
    return np.clip(out, 0.0, None).astype(np.float32)
