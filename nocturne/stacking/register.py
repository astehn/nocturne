from __future__ import annotations

import astroalign
import numpy as np
from skimage.transform import SimilarityTransform, warp


class RegistrationError(Exception):
    pass


def find_transform(src_lum: np.ndarray, ref_lum: np.ndarray) -> np.ndarray:
    src = np.ascontiguousarray(src_lum, dtype=np.float32)
    ref = np.ascontiguousarray(ref_lum, dtype=np.float32)
    try:
        transform, _ = astroalign.find_transform(src, ref)
    except Exception as exc:  # astroalign raises several types on no-match
        raise RegistrationError(str(exc)) from exc
    return np.asarray(transform.params, dtype=np.float64)


_ORDER = 3
"""Bicubic, not bilinear.

Registration resamples every frame exactly once, so this interpolator sets a
floor on how sharp any stack can be. Simulated as the pipeline uses it — one
resample per frame at a random sub-pixel phase, averaged over 12 phases — the
cost in stacked-PSF half-light was: order=1 +8.4%, order=3 +2.0%, order=5
-0.03% (M 45, 2026-08-18).

order=5 is effectively lossless but costs 1.10 s/frame/channel against 0.078,
which is +14 min on a 266-frame RGB set — a bad trade for the last 2% while
stacking speed is already the top complaint. order=3 buys 6.4 of the 8.4
points for +0.5 min.
"""


def warp_to(data: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    tform = SimilarityTransform(matrix=np.asarray(matrix, dtype=np.float64))
    if data.ndim == 2:
        return warp(data, tform.inverse, order=_ORDER,
                    preserve_range=True).astype(np.float32)
    channels = [
        warp(data[:, :, c], tform.inverse, order=_ORDER, preserve_range=True)
        for c in range(data.shape[2])
    ]
    return np.stack(channels, axis=2).astype(np.float32)


def warp_with_validity(data: np.ndarray, matrix: np.ndarray):
    """Warp, and say which pixels the frame actually reached.

    `warp` fills everything outside the source with zero, and zero is a
    legitimate pixel value — so the warped array alone cannot distinguish "the
    sky was dark here" from "this frame did not see here". Integration must know
    the difference or partial coverage silently dilutes the average (see
    integrate.py). A warped all-ones mask answers it exactly.

    The 0.999 threshold rather than >0 keeps the boundary row honest:
    interpolation makes edge pixels a blend of real data and the zero fill, so a
    pixel that is only fractionally covered is treated as not covered. Costs one
    extra single-channel warp per frame.

    Bicubic (_ORDER = 3) rings at that boundary where bilinear did not, so the
    mask was re-checked when the order changed: on a shifted all-ones frame the
    valid region is pixel-identical to bilinear's, and the highest mask value
    among rejected pixels is 0.78 — nowhere near 0.999, so the overshoot cannot
    manufacture coverage that the frame did not see.
    """
    warped = warp_to(data, matrix)
    ones = np.ones(data.shape[:2], dtype=np.float32)
    valid = warp_to(ones, matrix) >= 0.999
    return warped, valid
