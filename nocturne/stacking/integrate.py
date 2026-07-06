from __future__ import annotations

from typing import Callable, Iterable

import numpy as np


def average_integrate(frames: Iterable[np.ndarray]) -> np.ndarray:
    total = None
    count = 0
    for frame in frames:
        arr = np.asarray(frame, dtype=np.float64)
        total = arr.copy() if total is None else total + arr
        count += 1
    if total is None:
        raise ValueError("no frames to integrate")
    return (total / count).astype(np.float32)


def sigma_clip_integrate(make_frames: Callable[[], Iterable[np.ndarray]],
                         kappa: float) -> np.ndarray:
    # Pass 1: streaming per-pixel mean + variance (Welford).
    mean = m2 = None
    count = 0
    for frame in make_frames():
        arr = np.asarray(frame, dtype=np.float64)
        count += 1
        if mean is None:
            mean = np.zeros_like(arr)
            m2 = np.zeros_like(arr)
        delta = arr - mean
        mean += delta / count
        m2 += delta * (arr - mean)
    if mean is None:
        raise ValueError("no frames to integrate")
    std = np.sqrt(m2 / count)

    # Pass 2: accumulate only pixels within kappa*sigma of the pass-1 mean.
    clipped_sum = np.zeros_like(mean)
    clipped_count = np.zeros_like(mean)
    for frame in make_frames():
        arr = np.asarray(frame, dtype=np.float64)
        keep = (std == 0) | (np.abs(arr - mean) <= kappa * std)
        clipped_sum += np.where(keep, arr, 0.0)
        clipped_count += keep
    clipped_count = np.where(clipped_count == 0, 1, clipped_count)
    return (clipped_sum / clipped_count).astype(np.float32)
