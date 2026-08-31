"""The single definition of "how noisy is this image".

Used at training time to label each pair and at inference time to tell the
model what it is looking at. The two MUST agree: a model told sigma=0.01 in
training and sigma=0.02 for the same image in the app has been lied to.

Two choices that are not obvious from the constants alone:

- The dark-region mask is built from the *smoothed* luminance, not the raw
  one. Masking on raw luminance selects "the darker N%" using a quantity that
  is itself mostly noise wherever the scene is flat, so the selected set is
  the low tail of the very distribution being measured -- a truncation bias
  that reads sigma at roughly a third of its true value on a flat field.
- MAD is computed by pooling the high-pass residual across all channels
  (not on the channel-averaged luminance). Averaging channels first divides
  independent per-channel noise by sqrt(channels) before it is ever measured;
  pooling instead keeps each channel's noise sample intact and just gives the
  estimator more samples.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter

_HP_SIGMA = 2.0        # high-pass scale: removes scene, keeps noise
_DARK_FRACTION = 0.60  # measure on the darker 60%, away from nebula cores


def estimate_sigma(img: np.ndarray) -> float:
    """Robust noise sigma. MAD-based, so stars do not inflate it."""
    img = np.asarray(img, np.float32)
    if img.ndim == 2:
        img = img[:, :, None]
    lum = img.mean(axis=2)
    bg = gaussian_filter(lum, _HP_SIGMA)
    mask = bg <= np.percentile(bg, _DARK_FRACTION * 100.0)
    parts = []
    for c in range(img.shape[2]):
        chan = img[:, :, c]
        hp = chan - gaussian_filter(chan, _HP_SIGMA)
        parts.append(hp[mask])
    v = np.concatenate(parts) if parts else np.empty(0, np.float32)
    if v.size == 0:
        return 0.0
    return float(1.4826 * np.median(np.abs(v - np.median(v))))
