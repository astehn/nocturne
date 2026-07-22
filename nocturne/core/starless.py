"""Free star/starless split — a no-RC-Astro fallback for the star-separation
steps. Detects stars with `sep`, fills the holes with a fast local-median
background, and derives screen-compatible star layers so that
`1-(1-starless)*(1-stars)` reconstructs the original exactly. Rougher than
StarXTerminator (faint stars are missed, big stars leave some residual) — an
availability fallback, not a quality match.
"""
from __future__ import annotations

import numpy as np
import sep
from scipy.ndimage import gaussian_filter, median_filter
from skimage.transform import resize

from .image import AstroImage

_THRESH = 4.0        # sep detection threshold (sigma above background)
_RMIN, _RMAX = 2, 12  # star mask radius clamp (px)
_RFAC = 2.5          # mask radius = _RFAC * sqrt(a*b)
_FEATHER = 2.0       # gaussian feather of the star mask (px)
_BG_STEP = 4         # local-median background downscale factor (speed)
_BG_MED = 5          # median window on the downscaled image


def _local_background(data: np.ndarray) -> np.ndarray:
    """Smooth local background for filling star holes: a median at 1/_BG_STEP
    scale (fast), upscaled. Median rejects the bright star, so the fill doesn't
    inherit the star's glow the way a gaussian would."""
    small = data[::_BG_STEP, ::_BG_STEP]
    if small.ndim == 3:
        med = np.stack([median_filter(small[..., c], size=_BG_MED)
                        for c in range(small.shape[2])], axis=2)
    else:
        med = median_filter(small, size=_BG_MED)
    return resize(med, data.shape, order=1, preserve_range=True,
                  anti_aliasing=False).astype(np.float32)


def _star_mask(lum: np.ndarray, mask_scale: float = 1.0) -> np.ndarray:
    """Feathered 0..1 mask of detected stars (empty if none / sep fails).
    `mask_scale` widens the per-star radius + feather — Green Fringe uses a wider
    mask so it captures the fringe HALO around stars, not just the core."""
    h, w = lum.shape
    mask = np.zeros((h, w), np.float32)
    try:
        bkg = sep.Background(np.ascontiguousarray(lum))
        obj = sep.extract(lum - bkg.back(), _THRESH, err=bkg.globalrms)
    except Exception:
        return mask
    rmax = int(round(_RMAX * mask_scale))
    for o in obj:
        r = int(np.clip(_RFAC * mask_scale * np.sqrt(float(o["a"]) * float(o["b"])),
                        _RMIN, rmax))
        y0, y1 = max(0, int(o["y"]) - r), min(h, int(o["y"]) + r + 1)
        x0, x1 = max(0, int(o["x"]) - r), min(w, int(o["x"]) + r + 1)
        if y1 <= y0 or x1 <= x0:
            continue
        gy, gx = np.mgrid[y0:y1, x0:x1]
        mask[y0:y1, x0:x1] = np.maximum(
            mask[y0:y1, x0:x1],
            ((gy - o["y"]) ** 2 + (gx - o["x"]) ** 2 <= r * r).astype(np.float32))
    if mask.max() <= 0.0:
        return mask
    return np.clip(gaussian_filter(mask, _FEATHER * mask_scale), 0.0, 1.0)


def star_mask(img: AstroImage, mask_scale: float = 1.0) -> np.ndarray:
    """Public feathered 0..1 star-neighbourhood mask. Green Fringe passes
    `mask_scale`>1 to cover the fringe HALO around stars (not just the core) and
    de-greens the image in place inside it — see `remove_green_fringe_masked`."""
    data = np.clip(img.data.astype(np.float32), 0.0, 1.0)
    lum = data if data.ndim == 2 else data.mean(axis=2)
    return _star_mask(np.ascontiguousarray(lum, dtype=np.float32), mask_scale)


def split_stars(img: AstroImage) -> tuple[AstroImage, AstroImage]:
    """Free (starless, stars) split. `stars` is screen-compatible: the steps'
    `1-(1-starless)*(1-stars)` reconstructs the original exactly."""
    data = np.clip(img.data.astype(np.float32), 0.0, 1.0)
    mono = data.ndim == 2
    lum = data if mono else data.mean(axis=2)
    mask = _star_mask(np.ascontiguousarray(lum, dtype=np.float32))

    def _wrap(a):
        return AstroImage(np.clip(a, 0.0, 1.0).astype(np.float32),
                          is_linear=img.is_linear, metadata=dict(img.metadata))

    if mask.max() <= 0.0:                                   # no stars -> identity split
        return _wrap(data.copy()), _wrap(np.zeros_like(data))

    bg = _local_background(data)
    m = mask if mono else mask[..., None]
    starless = (1.0 - m) * data + m * np.minimum(data, bg)  # fill holes, never brighten
    starless = np.clip(starless, 0.0, 1.0).astype(np.float32)
    stars = np.clip(1.0 - (1.0 - data) / np.clip(1.0 - starless, 1e-4, None), 0.0, 1.0)
    return _wrap(starless), _wrap(stars)
