from __future__ import annotations

import numpy as np

from .image import AstroImage

_KNEE = 0.4   # luminance above which the sky ops fade to nothing


def _shadow_weight(lum: np.ndarray) -> np.ndarray:
    return np.clip(1.0 - lum / _KNEE, 0.0, 1.0) ** 2   # 1 near black, 0 above the knee


def boost_hue(img: AstroImage, hue: float, amount: float = 0.15,
              width: float = 0.12) -> AstroImage:
    """Increase saturation of pixels near `hue` (0..1) with smooth circular
    falloff. Mono is returned unchanged."""
    if not img.is_color:
        return img.copy()
    from skimage.color import hsv2rgb, rgb2hsv
    hsv = rgb2hsv(np.clip(img.data, 0.0, 1.0))
    dist = np.abs(hsv[..., 0] - hue)
    dist = np.minimum(dist, 1.0 - dist)                # circular hue distance
    w = np.exp(-(dist ** 2) / (2.0 * width ** 2))
    hsv[..., 1] = np.clip(hsv[..., 1] * (1.0 + amount * w), 0.0, 1.0)
    return AstroImage(np.clip(hsv2rgb(hsv), 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def darken_sky(img: AstroImage, amount: float = 0.08) -> AstroImage:
    """Shadow-masked darken: pull the dark background down, leave bright signal."""
    data = np.clip(img.data, 0.0, 1.0)
    lum = data.mean(axis=2, keepdims=True) if img.is_color else data
    out = np.clip(data - amount * _shadow_weight(lum), 0.0, 1.0)
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear,
                      metadata=dict(img.metadata))


def lighten_sky(img: AstroImage, amount: float = 0.08) -> AstroImage:
    """Shadow-masked lighten: gently lift the dark background."""
    data = np.clip(img.data, 0.0, 1.0)
    lum = data.mean(axis=2, keepdims=True) if img.is_color else data
    out = np.clip(data + amount * _shadow_weight(lum) * (1.0 - data), 0.0, 1.0)
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear,
                      metadata=dict(img.metadata))
