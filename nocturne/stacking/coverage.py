"""Where the stacked frames actually overlap, and the largest clean rectangle
inside that.

`coverage_map` used to live here — it re-derived per-pixel coverage by warping a
ones mask per transform, after integration had already had the same information
in its hands and thrown it away. The integrators now return coverage directly
(see integrate.py), so this file only decides where to cut. One computation of
one fact: two of them is how the FOV hint and the target name each ended up with
a second, divergent implementation.
"""
from __future__ import annotations

import numpy as np


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
                         frac: float = 0.5) -> tuple:
    """Largest axis-aligned rectangle where at least `frac` of the frames
    contributed. Returns (top, bottom, left, right), bottom/right exclusive.
    Falls back to the full frame if no pixel meets the threshold.

    `frac` is set by NOISE, not by taste. Shot noise falls as sqrt(N), so a
    pixel built from half the frames is sqrt(2) = 1.41x noisier than the fully
    covered interior — one stop, and about where a grainier border starts to
    read as a defect rather than as an edge. Hence 0.5.

    It used to be 0.9, from when partial coverage also made pixels DARK: the
    integrator divided by the frame count including frames that contributed
    nothing, so the edges carried a brightness ramp that had to be cut away
    (see integrate.py). With that fixed the discarded pixels are correctly
    bright and merely noisier, and 0.9 was measured on a real 60-frame M31
    stack to throw away 24% of the frame to avoid 1.07x noise — a bad trade.
    At 0.5 the same stack keeps 91% with a worst case of 1.52x, and only at
    the extreme boundary.

    Erring wide is also the cheaper mistake now that Trim exists: a user can
    always cut more off a finished image, but nothing can put back what the
    stacker discarded.

    For speed on full-resolution masks the search runs on a subsampled copy and
    the bounds are scaled back (a few pixels of imprecision at the crop edge is
    irrelevant, and it is why the kept rectangle can dip a little under `frac`)."""
    thresh = max(1, int(np.ceil(frac * n_frames)))
    mask = coverage >= thresh
    height, width = coverage.shape
    if not mask.any():
        return (0, height, 0, width)
    step = max(1, min(mask.shape) // 256)
    top, bottom, left, right = _largest_true_rectangle(mask[::step, ::step])
    return (top * step, min(bottom * step, height),
            left * step, min(right * step, width))
