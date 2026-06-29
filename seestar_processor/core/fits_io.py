from __future__ import annotations

import numpy as np
from astropy.io import fits
from colour_demosaicing import demosaicing_CFA_Bayer_bilinear

from .image import AstroImage
from .instrument import SEESTAR_S30_PRO


def _normalize(arr: np.ndarray) -> np.ndarray:
    arr = arr.astype(np.float32)
    peak = float(arr.max())
    if peak > 0:
        arr = arr / peak
    return arr


def load_fits(path: str) -> AstroImage:
    with fits.open(path) as hdul:
        raw = np.asarray(hdul[0].data)
    if raw.ndim == 3:
        # FITS color cubes are typically (channels, H, W); some are already (H, W, 3).
        if raw.shape[0] == 3:
            raw = np.transpose(raw, (1, 2, 0))
        elif raw.shape[2] != 3:
            raise ValueError(
                f"unsupported 3D FITS shape {raw.shape}; expected (3, H, W) or (H, W, 3)"
            )
        data = _normalize(raw)
        return AstroImage(data, is_linear=True)
    # 2D mono-Bayer -> debayer with instrument pattern.
    norm = _normalize(raw)
    rgb = demosaicing_CFA_Bayer_bilinear(norm, SEESTAR_S30_PRO.bayer_pattern)
    return AstroImage(np.clip(rgb, 0.0, 1.0).astype(np.float32), is_linear=True)
