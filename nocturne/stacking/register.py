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


def warp_to(data: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    tform = SimilarityTransform(matrix=np.asarray(matrix, dtype=np.float64))
    if data.ndim == 2:
        return warp(data, tform.inverse, order=1, preserve_range=True).astype(np.float32)
    channels = [
        warp(data[:, :, c], tform.inverse, order=1, preserve_range=True)
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

    The 0.999 threshold rather than >0 keeps the boundary row honest: bilinear
    interpolation makes edge pixels a blend of real data and the zero fill, so a
    pixel that is only fractionally covered is treated as not covered. Costs one
    extra single-channel warp per frame.
    """
    warped = warp_to(data, matrix)
    ones = np.ones(data.shape[:2], dtype=np.float32)
    valid = warp_to(ones, matrix) >= 0.999
    return warped, valid
