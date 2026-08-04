"""Bring every frame to a common sky level before they are combined.

Without this, which frames a pixel happened to average changes its background.
An interior pixel averages every frame, so its sky is the mean of all of them; a
fringe pixel averages only the subset that reached it, whose mean sky differs.
Every coverage boundary then becomes a step in background level and the rotation
envelope gets drawn onto the finished picture as curved bands.

That is not a small effect. Measured across one real M31 session the sky varied
262% between frames — 0.088 to 0.427 — as the target climbed and the moon moved.
It was invisible while the auto-crop kept only near-fully-covered pixels, because
then every kept pixel had nearly the same set of frames behind it. Relaxing the
crop exposed it immediately (2026-08-03).

The correction is affine and per channel:

    out = (x - location_i) * (scale_ref / scale_i) + location_ref

`location` uses the median and `scale` the MAD, because both must survive a sky
full of stars. A mean/standard-deviation pair is dragged by every bright star, so
a star-rich frame would be "corrected" for the very signal it was meant to
contribute. Per CHANNEL because real skies are not grey: on the M31 frames the
channel medians were R 25020, G 21404, B 37546, and a single global correction
would leave that cast in place and still varying frame to frame.

Statistics come from a strided subsample. Full resolution costs 338 ms per frame
— around 13 minutes on a 2361-frame stack — while a stride-8 subsample costs 6 ms
and, measured on a real frame, agrees to 0.004% on the median and 0.18% on the
MAD. 389k samples is an enormous sample for a median; the extra precision buys
nothing and the time is real.
"""
from __future__ import annotations

import numpy as np

# 1/Phi^-1(3/4): scales the MAD to a standard-deviation equivalent for Gaussian
# noise, so `scale` is comparable to a sigma without inheriting its fragility.
_MAD_TO_SIGMA = 1.4826

# Samples to aim for per channel. Chosen so a full Seestar frame subsamples to
# roughly stride 7 — the measured sweet spot — while anything small is measured
# whole. A fixed stride was the first attempt and it was wrong: on a 32x32 frame
# stride 8 leaves 16 samples, and the median of 16 samples scatters far too much
# to correct a sky level with.
_TARGET_SAMPLES = 150_000


def _stride_for(shape) -> int:
    pixels = shape[0] * shape[1]
    return max(1, int(np.sqrt(pixels / _TARGET_SAMPLES)))


def frame_stats(data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Robust (location, scale) per channel, as 1-D arrays.

    Mono input yields length-1 arrays so callers need no special case.
    """
    arr = np.asarray(data, dtype=np.float32)
    step = _stride_for(arr.shape)
    sample = arr[::step, ::step]
    if sample.ndim == 2:
        sample = sample[..., None]
    flat = sample.reshape(-1, sample.shape[2])
    location = np.median(flat, axis=0)
    scale = np.median(np.abs(flat - location), axis=0) * _MAD_TO_SIGMA
    return location.astype(np.float64), scale.astype(np.float64)


def normalize_to(data: np.ndarray, stats, ref_stats) -> np.ndarray:
    """Rescale `data` so its sky matches the reference's, preserving signal.

    A star N sigma above the sky stays N sigma above the sky — the background is
    moved, not the picture.
    """
    loc, scale = stats
    ref_loc, ref_scale = ref_stats
    arr = np.asarray(data, dtype=np.float32)
    mono = arr.ndim == 2
    work = arr[..., None] if mono else arr

    # A frame with no variation has zero scale. Dividing by it yields inf, and a
    # single inf poisons every pixel it touches — fall back to offset-only.
    factor = np.where(scale > 0, ref_scale / np.where(scale > 0, scale, 1.0), 1.0)
    out = (work - loc) * factor + ref_loc
    return (out[..., 0] if mono else out).astype(np.float32)
