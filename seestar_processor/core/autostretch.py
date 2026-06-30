from __future__ import annotations

import numpy as np

from .image import AstroImage

_TARGET_BG = 0.25  # target median for the stretched display
_SIGMA = 2.8


def _mtf(m: float, x: np.ndarray) -> np.ndarray:
    # Midtones transfer function (PixInsight/Siril style). np.where evaluates
    # both branches, so a near-zero denominator can warn even though the result
    # is masked/clipped downstream — silence that spurious warning.
    num = (m - 1.0) * x
    den = (2.0 * m - 1.0) * x - m
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = num / den
    return np.where(x == 0, 0.0, np.where(x == 1, 1.0, ratio))


def _stretch_channel(c: np.ndarray) -> np.ndarray:
    med = float(np.median(c))
    mad = float(np.median(np.abs(c - med))) or 1e-6
    shadow = max(0.0, med - _SIGMA * mad)
    c = np.clip((c - shadow) / max(1e-6, 1.0 - shadow), 0.0, 1.0)
    med2 = float(np.median(c)) or 1e-6
    # midtones balance that maps current median to _TARGET_BG
    m = _mtf_midtones(med2, _TARGET_BG)
    return _mtf(m, c).astype(np.float32)


def _mtf_midtones(current_med: float, target: float) -> float:
    # Solve MTF midtones param so that _mtf(m, current_med) == target.
    if current_med <= 0:
        return 0.5
    return ((target - 1.0) * current_med) / (
        (2.0 * target - 1.0) * current_med - target
    )


def autostretch(img: AstroImage) -> np.ndarray:
    data = img.data
    if data.ndim == 2:
        return np.clip(_stretch_channel(data), 0.0, 1.0)
    out = np.empty_like(data, dtype=np.float32)
    for ch in range(data.shape[2]):
        out[..., ch] = _stretch_channel(data[..., ch])
    return np.clip(out, 0.0, 1.0)
