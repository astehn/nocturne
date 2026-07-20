from __future__ import annotations

import numpy as np
from skimage.filters import gaussian

from .image import AstroImage

_T0 = 0.55          # highlight mask ramp start (luminance)
_T1 = 0.92          # highlight mask ramp end
_SIGMA_FRAC = 0.015  # Gaussian radius as a fraction of the short edge


def _smoothstep(x: np.ndarray, a: float, b: float) -> np.ndarray:
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def recover_core(img: AstroImage, amount: float) -> AstroImage:
    """Tame blown-out bright cores: under a feathered highlight mask, pull the
    core's local average brightness down and re-expand the fine structure hiding
    inside it, so a clipped white blob shows detail again.

    Single-scale local HDR on luminance only; hue preserved by rescaling RGB with
    the luminance ratio (as `local_contrast.enhance` does). `amount` 0 = no-op;
    higher = stronger pull-down and detail re-expansion.
    """
    amount = float(np.clip(amount, 0.0, 1.0))
    data = np.clip(img.data, 0.0, 1.0).astype(np.float32)
    if amount == 0.0:
        return AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))

    mono = data.ndim == 2
    lum = data if mono else data.mean(axis=2)
    h, w = lum.shape
    sigma = max(1.0, _SIGMA_FRAC * min(h, w))

    mask = _smoothstep(lum, _T0, _T1)                       # 0 in sky → 1 in core
    blur = gaussian(lum, sigma=sigma, preserve_range=True).astype(np.float32)
    detail = lum - blur                                     # structure in the blob

    compressed = blur ** (1.0 + amount)                     # darken the bright DC
    boosted = compressed + (1.0 + amount) * detail          # re-expand the detail
    weight = amount * mask
    new_lum = np.clip(lum * (1.0 - weight) + boosted * weight, 0.0, 1.0)

    if mono:
        out = new_lum
    else:
        ratio = new_lum / np.maximum(lum, 1e-6)
        out = np.clip(data * ratio[..., None], 0.0, 1.0)

    return AstroImage(out.astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))
