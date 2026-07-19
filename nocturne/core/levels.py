from __future__ import annotations

import numpy as np

from .image import AstroImage


def apply_levels(img: AstroImage, black: float, gamma: float, white: float) -> AstroImage:
    """Levels adjustment: remap [black, white] to [0, 1] then apply midtone gamma."""
    white = max(white, black + 1e-4)
    x = np.clip((img.data - black) / (white - black), 0.0, 1.0)
    out = np.power(x, 1.0 / max(gamma, 1e-3))
    return AstroImage(
        out.astype(np.float32), is_linear=img.is_linear, metadata=dict(img.metadata)
    )


def auto_levels(data: np.ndarray) -> tuple[float, float, float]:
    """Suggested (black, gamma, white) for a stretched image — gentle, never
    clips real signal hard."""
    lum = data.mean(axis=2) if data.ndim == 3 else data
    black = float(np.clip(np.percentile(lum, 1.0), 0.0, 0.5))
    white = float(np.percentile(lum, 99.9))
    white = max(white, black + 0.05)
    med = float(np.median(lum))
    x = float(np.clip((med - black) / max(white - black, 1e-4), 1e-3, 0.999))
    gamma = float(np.clip(np.log(x) / np.log(0.35), 0.4, 2.5))
    return black, gamma, white


def clipping_masks(data: np.ndarray, black: float, white: float):
    """Boolean (shadow_clipped, highlight_clipped) per pixel."""
    lum = data.mean(axis=2) if data.ndim == 3 else data
    return lum <= black, lum >= white
