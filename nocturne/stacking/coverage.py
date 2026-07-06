from __future__ import annotations

import numpy as np

from .register import warp_to


def coverage_map(transforms: list, shape: tuple) -> np.ndarray:
    """Per-pixel count of how many frames actually covered each pixel of the
    reference frame. Warps an all-ones mask by each frame's transform (out-of-
    frame areas warp to 0) and sums. Needs only the transforms — no disk I/O."""
    cov = np.zeros(shape, dtype=np.int32)
    ones = np.ones(shape, dtype=np.float32)
    for matrix in transforms:
        warped = warp_to(ones, matrix)
        cov += (warped > 0.5)
    return cov


def _largest_true_rectangle(mask: np.ndarray) -> tuple:
    """Largest all-True axis-aligned rectangle in a 2D boolean mask, as
    (top, bottom, left, right) with bottom/right exclusive. O(H*W) via the
    largest-rectangle-in-histogram method, row by row."""
    h, w = mask.shape
    heights = np.zeros(w, dtype=np.int64)
    best_area = 0
    best = (0, h, 0, w)
    for row in range(h):
        heights = np.where(mask[row], heights + 1, 0)
        stack: list = []  # (start_col, height), increasing heights
        for c in range(w + 1):
            cur = int(heights[c]) if c < w else 0
            start = c
            while stack and stack[-1][1] > cur:
                idx, hh = stack.pop()
                area = hh * (c - idx)
                if area > best_area:
                    best_area = area
                    best = (row - hh + 1, row + 1, idx, c)
                start = idx
            stack.append((start, cur))
    return best


def full_coverage_bounds(coverage: np.ndarray, n_frames: int,
                         frac: float = 0.9) -> tuple:
    """Largest axis-aligned rectangle where at least `frac` of the frames
    contributed. Returns (top, bottom, left, right), bottom/right exclusive.
    Falls back to the full frame if no pixel meets the threshold.

    For speed on full-resolution masks the search runs on a subsampled copy and
    the bounds are scaled back (a few pixels of imprecision at the crop edge is
    irrelevant)."""
    thresh = max(1, int(np.ceil(frac * n_frames)))
    mask = coverage >= thresh
    height, width = coverage.shape
    if not mask.any():
        return (0, height, 0, width)
    step = max(1, min(mask.shape) // 256)
    top, bottom, left, right = _largest_true_rectangle(mask[::step, ::step])
    return (top * step, min(bottom * step, height),
            left * step, min(right * step, width))
