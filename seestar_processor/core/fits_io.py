from __future__ import annotations

import os

import numpy as np
import tifffile
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


_VALID_CFA = ("RGGB", "BGGR", "GRBG", "GBRG")


def _bayer_pattern(header) -> str:
    """CFA pattern from the file's own BAYERPAT header (authoritative), falling
    back to the instrument default only when it is missing/invalid. A wrong
    pattern demosaics one phase off -> green maze + false colour."""
    pattern = str(header.get("BAYERPAT", "") or "").strip().upper()
    return pattern if pattern in _VALID_CFA else SEESTAR_S30_PRO.bayer_pattern


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
    # 2D mono-Bayer -> debayer. The CFA pattern MUST come from the file's own
    # header (Seestar subs are 'GRBG', not 'RGGB'); a wrong pattern demosaics one
    # phase off and produces a green maze + false colour.
    base = _normalize(raw) if normalize else raw.astype(np.float32)
    rgb = demosaicing_CFA_Bayer_bilinear(base, _bayer_pattern(header))
    if normalize:
        rgb = np.clip(rgb, 0.0, 1.0)
    h, w = rgb.shape[:2]
    return AstroImage(rgb.astype(np.float32), is_linear=True,
                      metadata=_parse_metadata(header, h, w))


def load_master(path: str) -> AstroImage:
    """Load a processed master back to a linear AstroImage. Supports the formats
    the app writes: FITS (via load_fits) and 16-bit TIFF (via tifffile)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".fits", ".fit", ".fts"):
        # A colour master is a 3-channel cube (NAXIS=3). A 2D FITS is a mono or
        # raw-CFA frame, which load_fits would debayer into fake colour — reject
        # it instead so the palette tool gives an honest error, not garbage.
        with fits.open(path) as hdul:
            if int(hdul[0].header.get("NAXIS", 0)) != 3:
                raise ValueError("palette needs a colour (RGB) master, not a mono image")
        return load_fits(path)
    if ext in (".tif", ".tiff"):
        arr = np.asarray(tifffile.imread(path)).astype(np.float32)
        peak = float(arr.max())
        if peak > 0:
            arr = arr / peak
        h, w = arr.shape[:2]
        return AstroImage(np.clip(arr, 0.0, 1.0), is_linear=True,
                          metadata={"width": w, "height": h})
    raise ValueError(f"unsupported input format: {ext}")
