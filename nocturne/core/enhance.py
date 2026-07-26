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


def _smoothstep(x: np.ndarray, a: float, b: float) -> np.ndarray:
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def soft_glow(img: AstroImage, amount: float = 0.2, radius: float = 8.0,
              threshold: float = 0.35) -> AstroImage:
    """Orton-style bloom gated to the brighter signal: blur a copy and screen it
    back over the highlights, leaving the dark background clean. Works on mono too."""
    from scipy.ndimage import gaussian_filter
    data = np.clip(img.data, 0.0, 1.0)
    lum = data.mean(axis=2) if img.is_color else data
    hi = _smoothstep(lum, threshold, 1.0)
    if img.is_color:
        blurred = np.stack([gaussian_filter(data[..., c], radius)
                            for c in range(data.shape[2])], axis=2)
        glow = blurred * (hi[..., None] * amount)
    else:
        blurred = gaussian_filter(data, radius)
        glow = blurred * (hi * amount)
    out = 1.0 - (1.0 - data) * (1.0 - np.clip(glow, 0.0, 1.0))   # screen blend
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def vibrance(img: AstroImage, amount: float = 0.2) -> AstroImage:
    """Saturation boost weighted by (1 - saturation) so under-saturated colour
    lifts more and saturated colour is protected; shadow-protected. Mono unchanged."""
    if not img.is_color:
        return img.copy()
    from skimage.color import hsv2rgb, rgb2hsv
    data = np.clip(img.data, 0.0, 1.0)
    hsv = rgb2hsv(data)
    s = hsv[..., 1]
    lum = data.mean(axis=2)
    shadow_protect = np.clip((lum - 0.12) / 0.18, 0.0, 1.0)     # mirrors saturation.saturate
    hsv[..., 1] = np.clip(s + amount * (1.0 - s) * shadow_protect, 0.0, 1.0)
    return AstroImage(np.clip(hsv2rgb(hsv), 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def star_colour(img: AstroImage, mask: np.ndarray, amount: float = 0.5) -> AstroImage:
    """Boost saturation only where the feathered star `mask` (0..1, HxW) is high.
    Mono unchanged. Pure — the caller supplies the mask (see main_window)."""
    if not img.is_color:
        return img.copy()
    from skimage.color import hsv2rgb, rgb2hsv
    data = np.clip(img.data, 0.0, 1.0)
    hsv = rgb2hsv(data)
    m = np.clip(mask, 0.0, 1.0)
    hsv[..., 1] = np.clip(hsv[..., 1] * (1.0 + amount * m), 0.0, 1.0)
    return AstroImage(np.clip(hsv2rgb(hsv), 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))
