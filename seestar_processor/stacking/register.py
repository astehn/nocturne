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
