from __future__ import annotations

import numpy as np

from .image import AstroImage

PALETTES = ("HOO", "pseudo_SHO")


def extract_channels(img: AstroImage) -> tuple:
    """Return (ha, oiii) as 2D float32 in [0,1]. Ha = red channel; OIII =
    mean of green and blue. Raises ValueError for a non-colour image."""
    if not img.is_color:
        raise ValueError("palette needs a colour (RGB) master")
    data = np.clip(img.data, 0.0, 1.0)
    ha = data[..., 0].astype(np.float32)
    oiii = ((data[..., 1] + data[..., 2]) / 2.0).astype(np.float32)
    return ha, oiii


def _image_like(channels: tuple, like: AstroImage) -> AstroImage:
    rgb = np.clip(np.stack(channels, axis=2), 0.0, 1.0).astype(np.float32)
    return AstroImage(rgb, is_linear=like.is_linear, metadata=dict(like.metadata))


def hoo(img: AstroImage) -> AstroImage:
    """R=Ha, G=OIII, B=OIII — the honest native duo-band palette."""
    ha, oiii = extract_channels(img)
    return _image_like((ha, oiii, oiii), img)


def pseudo_sho(img: AstroImage) -> AstroImage:
    """Foraxx-inspired gold/teal remap from Ha+OIII only. Not real SHO
    (no SII). Ha -> gold (R+G), OIII -> teal (G+B)."""
    ha, oiii = extract_channels(img)
    r = ha
    g = np.clip(0.5 * ha + 0.5 * oiii, 0.0, 1.0)
    b = oiii
    return _image_like((r, g, b), img)


_PALETTE_FNS = {"HOO": hoo, "pseudo_SHO": pseudo_sho}


def apply_palette(img: AstroImage, name: str) -> AstroImage:
    if name not in _PALETTE_FNS:
        raise ValueError(f"unknown palette: {name}")
    return _PALETTE_FNS[name](img)
