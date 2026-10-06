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


def prepare(img: AstroImage) -> np.ndarray:
    """The blur of luminance — the part of Recover Core no `amount` changes, and
    6.2 s of a 6.7 s call on a 33 MP drizzled master (2026-10-06). A live
    preview computes it once per base and hands it to `apply_prepared`."""
    data = np.clip(img.data, 0.0, 1.0).astype(np.float32)
    lum = data if data.ndim == 2 else data.mean(axis=2)
    sigma = max(1.0, _SIGMA_FRAC * min(lum.shape))
    return gaussian(lum, sigma=sigma, preserve_range=True).astype(np.float32)


def recover_core(img: AstroImage, amount: float) -> AstroImage:
    """Tame blown-out bright cores: under a feathered highlight mask, pull the
    core's local average brightness down and re-expand the fine structure hiding
    inside it, so a clipped white blob shows detail again.

    Single-scale local HDR on luminance only; hue preserved by rescaling RGB with
    the luminance ratio (as `local_contrast.enhance` does). `amount` 0 = no-op;
    higher = stronger pull-down and detail re-expansion.
    """
    if float(np.clip(amount, 0.0, 1.0)) == 0.0:
        return apply_prepared(img, None, amount)    # no blur needed for a no-op
    return apply_prepared(img, prepare(img), amount)


def apply_prepared(img: AstroImage, blur: np.ndarray | None,
                   amount: float) -> AstroImage:
    """`recover_core` given `prepare(img)` for this same `img` — bit-identical."""
    amount = float(np.clip(amount, 0.0, 1.0))
    data = np.clip(img.data, 0.0, 1.0).astype(np.float32)
    if amount == 0.0:
        return AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))

    mono = data.ndim == 2
    lum = data if mono else data.mean(axis=2)

    mask = _smoothstep(lum, _T0, _T1)                       # 0 in sky → 1 in core
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
