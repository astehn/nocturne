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


def _parse_metadata(header, height: int, width: int) -> dict:
    meta: dict = {"width": width, "height": height}
    mapping = {
        "exposure": ("EXPTIME",),
        "gain": ("GAIN",),
        "target": ("OBJECT",),
        "frames": ("STACKCNT", "NFRAMES", "NCOMBINE"),
        "bitpix": ("BITPIX",),
    }
    for key, candidates in mapping.items():
        for card in candidates:
            if card in header:
                meta[key] = header[card]
                break
    return meta


def format_metadata(meta: dict) -> str:
    parts = []
    if meta.get("target"):
        parts.append(str(meta["target"]))
    if meta.get("exposure") is not None:
        parts.append(f"{meta['exposure']:g}s")
    if meta.get("frames") is not None:
        parts.append(f"{meta['frames']} frames")
    if meta.get("gain") is not None:
        parts.append(f"gain {meta['gain']:g}")
    if meta.get("width") and meta.get("height"):
        parts.append(f"{meta['width']}x{meta['height']}")
    return "  •  ".join(parts) if parts else "No metadata"


def load_fits(path: str, normalize: bool = True) -> AstroImage:
    with fits.open(path) as hdul:
        raw = np.asarray(hdul[0].data)
        header = hdul[0].header
    if raw.ndim == 3:
        # FITS color cubes are typically (channels, H, W); some are already (H, W, 3).
        if raw.shape[0] == 3:
            raw = np.transpose(raw, (1, 2, 0))
        elif raw.shape[2] != 3:
            raise ValueError(
                f"unsupported 3D FITS shape {raw.shape}; expected (3, H, W) or (H, W, 3)"
            )
        data = _normalize(raw) if normalize else raw.astype(np.float32)
        if normalize:
            data = np.clip(data, 0.0, 1.0)
        h, w = data.shape[:2]
        return AstroImage(data.astype(np.float32), is_linear=True,
                          metadata=_parse_metadata(header, h, w))
    # 2D mono-Bayer -> debayer with instrument pattern.
    base = _normalize(raw) if normalize else raw.astype(np.float32)
    rgb = demosaicing_CFA_Bayer_bilinear(base, SEESTAR_S30_PRO.bayer_pattern)
    if normalize:
        rgb = np.clip(rgb, 0.0, 1.0)
    h, w = rgb.shape[:2]
    return AstroImage(rgb.astype(np.float32), is_linear=True,
                      metadata=_parse_metadata(header, h, w))
