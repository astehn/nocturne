"""Combine registered frames into one master, counting only real samples.

A frame that does not cover a pixel must not vote on it. That sounds obvious and
was got wrong in a way that took a side-by-side against Siril to see: `warp`
fills out-of-frame area with ZERO, and the average divided by the FRAME COUNT,
so an edge pixel covered by 10 of 80 frames came out at 12% of its true value —
measured on real M31 subs 2026-08-03. The result was a smooth dark ramp inward
from every edge, which no amount of cropping removes.

`sigma_clip_integrate` appeared immune, because it already divided by a per-pixel
`clipped_count`. It was not, and the reason is worth keeping: the zeros were in
its PASS-1 statistics. They pulled the mean down and inflated sigma, widening the
clip threshold until the zeros passed their own rejection test. At a half-covered
pixel with a true value of 0.100 the mean came out 0.054, sigma 0.0498 and the
threshold +/-0.125, so all 277 frames were "kept" and the answer was 54% of true.
A guard that disables itself is worse than no guard.

So validity is carried explicitly. Frames may be yielded either as a bare array
(fully covering, the common case) or as an `(array, valid)` pair where `valid` is
a 2D boolean mask. NOT a NaN sentinel: real astro data genuinely contains NaN —
alt-az no-data corners arrive that way and `fits_io._normalize` documents it — so
using NaN for "outside the frame" would conflate two different facts and silently
swallow real bad pixels.

Both integrators return `(master, coverage)`, where coverage is the per-pixel
count of frames that actually contributed. That is the ONE place coverage is
computed: it used to be derived twice, once implicitly as the zeros here and
again by warping a mask per transform in `coverage.coverage_map`, and two
computations of one fact is exactly the trap this codebase keeps falling into.
"""
from __future__ import annotations

from typing import Callable, Iterable

import numpy as np


def _split(frame):
    """A frame is either `arr` (covers everything) or `(arr, valid_2d_bool)`."""
    if isinstance(frame, tuple):
        arr, valid = frame
        return np.asarray(arr, dtype=np.float64), np.asarray(valid, dtype=bool)
    return np.asarray(frame, dtype=np.float64), None


def _weights(arr: np.ndarray, valid: np.ndarray | None) -> np.ndarray:
    """Per-sample 0/1 weights shaped like `arr` (masks are 2D, data may be 3D)."""
    if valid is None:
        return np.ones_like(arr)
    return np.broadcast_to(valid[..., None] if arr.ndim == 3 else valid,
                           arr.shape).astype(np.float64)


def _coverage(count: np.ndarray) -> np.ndarray:
    """Per-pixel frame count from per-sample weights — 2D even for colour."""
    return (count[..., 0] if count.ndim == 3 else count).astype(np.int32)


def average_integrate(frames: Iterable) -> tuple[np.ndarray, np.ndarray]:
    total = None
    count = None
    for frame in frames:
        arr, valid = _split(frame)
        w = _weights(arr, valid)
        if total is None:
            total = np.zeros_like(arr)
            count = np.zeros_like(arr)
        total += arr * w
        count += w
    if total is None:
        raise ValueError("no frames to integrate")
    return ((total / np.maximum(count, 1.0)).astype(np.float32), _coverage(count))


def sigma_clip_integrate(make_frames: Callable[[], Iterable],
                         kappa: float) -> tuple[np.ndarray, np.ndarray]:
    # Pass 1: streaming per-pixel mean + variance (weighted Welford). Samples a
    # frame did not cover carry zero weight, so they never enter the statistics
    # that set the rejection threshold — the whole point.
    mean = m2 = wsum = None
    for frame in make_frames():
        arr, valid = _split(frame)
        w = _weights(arr, valid)
        if mean is None:
            mean = np.zeros_like(arr)
            m2 = np.zeros_like(arr)
            wsum = np.zeros_like(arr)
        wsum += w
        delta = arr - mean
        # Where w is 0 this adds nothing, so mean and m2 are left untouched.
        mean += np.divide(delta * w, wsum, out=np.zeros_like(arr), where=wsum > 0)
        m2 += w * delta * (arr - mean)
    if mean is None:
        raise ValueError("no frames to integrate")
    std = np.sqrt(np.divide(m2, wsum, out=np.zeros_like(m2), where=wsum > 0))

    # Pass 2: accumulate covered samples within kappa*sigma of the pass-1 mean.
    clipped_sum = np.zeros_like(mean)
    clipped_count = np.zeros_like(mean)
    for frame in make_frames():
        arr, valid = _split(frame)
        w = _weights(arr, valid)
        keep = ((std == 0) | (np.abs(arr - mean) <= kappa * std)) & (w > 0)
        clipped_sum += np.where(keep, arr, 0.0)
        clipped_count += keep
    # Divide by what survived clipping, but REPORT geometric coverage: a pixel
    # where one satellite frame was clipped is still fully covered, and it is
    # coverage that tells the auto-crop where the real frame edge is. Returning
    # the post-clip count would make ordinary outlier rejection look like a
    # coverage hole and creep the crop inward.
    return ((clipped_sum / np.maximum(clipped_count, 1.0)).astype(np.float32),
            _coverage(wsum))
