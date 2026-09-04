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
                         frac: float = 0.9) -> tuple:
    """Largest axis-aligned rectangle where at least `frac` of the frames
    contributed. Returns (top, bottom, left, right), bottom/right exclusive.
    Falls back to the full frame if no pixel meets the threshold.

    `frac` is high because frames are NOT normalized to a common sky level,
    not because of noise.

    It was briefly 0.5, on the reasoning that shot noise falls as sqrt(N) so
    half-covered pixels are only sqrt(2) noisier — true, and it kept 91% of the
    frame instead of 76%. On real M31 data that produced visible curved BANDS
    along the fringe, and the cause is not noise at all. Sky background varies
    262% across that session (0.088 to 0.427 between frames). An interior pixel
    averages every frame, so its sky is the mean of all of them; a fringe pixel
    averages only the subset that reached it, whose mean sky is different. Each
    coverage boundary therefore becomes a step in background level, and the
    rotation envelope gets drawn on the picture.

    Keeping only where nearly every frame contributed makes the subsets nearly
    identical, which hides the problem. The real fix is per-frame normalization
    before combining (Siril: "additive + scaling"), and once that lands this can
    drop to the noise-driven value.

    For speed on full-resolution masks the search runs on a subsampled copy and
    the bounds are scaled back (a few pixels of imprecision at the crop edge is
    irrelevant, and it is why the kept rectangle can dip a little under `frac`)."""
    # NOT ceil()ed. For an integer coverage map — every method except drizzle —
    # rounding up selects exactly the same pixels, because there are no integers
    # between 0.9*n and ceil(0.9*n): verified for n = 3, 8, 12, 20, 100, 1233.
    #
    # For drizzle it was fatal. Its coverage is a continuous weight rescaled so
    # the MEDIAN maps to the frame count, so at n=8 the interior sits at ~8.00
    # while ceil(7.2) demanded >= 8 exactly — which by construction roughly half
    # the interior fails, scattered like noise rather than as an envelope. The
    # largest hole-free rectangle then collapsed: measured 2026-09-04 on real
    # NGC 281 subs, 96 x 1712 out of 4320 x 7680, where the same mask at the
    # unrounded threshold gives 4110 x 7572. On a mosaic panel it went to
    # 736 x 112 and the panel could no longer be plate-solved at all.
    thresh = max(1.0, frac * n_frames)
    mask = coverage >= thresh
    height, width = coverage.shape
    if not mask.any():
        return (0, height, 0, width)
    step = max(1, min(mask.shape) // 256)
    top, bottom, left, right = _largest_true_rectangle(mask[::step, ::step])
    return (top * step, min(bottom * step, height),
            left * step, min(right * step, width))
