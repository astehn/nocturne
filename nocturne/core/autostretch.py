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


def _stretch_params(c: np.ndarray, target: float = _TARGET_BG) -> tuple[float, float]:
    """Derive (shadow clip, midtones m) from one channel's statistics so its
    median maps to `target`."""
    med = float(np.median(c))
    mad = float(np.median(np.abs(c - med))) or 1e-6
    shadow = max(0.0, med - _SIGMA * mad)
    clipped = np.clip((c - shadow) / max(1e-6, 1.0 - shadow), 0.0, 1.0)
    med2 = float(np.median(clipped)) or 1e-6
    return shadow, _mtf_midtones(med2, target)


def linked_stretch(data: np.ndarray, target: float) -> np.ndarray:
    """Adaptive midtones stretch. For color, one transfer is derived from
    luminance and applied to every channel (preserves colour balance)."""
    if data.ndim == 2:
        shadow, m = _stretch_params(data, target)
        return np.clip(_apply_params(data, shadow, m), 0.0, 1.0)
    lum = data.mean(axis=2)
    shadow, m = _stretch_params(lum, target)
    out = np.empty_like(data, dtype=np.float32)
    for ch in range(data.shape[2]):
        out[..., ch] = _apply_params(data[..., ch], shadow, m)
    return np.clip(out, 0.0, 1.0)


def unlinked_stretch(data: np.ndarray, target: float = _TARGET_BG) -> np.ndarray:
    """Per-channel display stretch: each channel independently stretched so its
    own median hits `target`. Neutralizes a uniform sky-colour cast (twilight,
    moon, light pollution) — the Siril-style preview stretch. Display-only;
    the editor keeps the colour-faithful linked_stretch."""
    if data.ndim == 2:
        return linked_stretch(data, target)
    out = np.empty_like(data, dtype=np.float32)
    for ch in range(data.shape[2]):
        shadow, m = _stretch_params(data[..., ch], target)
        out[..., ch] = _apply_params(data[..., ch], shadow, m)
    return np.clip(out, 0.0, 1.0)


def _apply_params(c: np.ndarray, shadow: float, m: float) -> np.ndarray:
    clipped = np.clip((c - shadow) / max(1e-6, 1.0 - shadow), 0.0, 1.0)
    return _mtf(m, clipped).astype(np.float32)


def _mtf_midtones(current_med: float, target: float) -> float:
    # Solve MTF midtones param so that _mtf(m, current_med) == target.
    if current_med <= 0:
        return 0.5
    return ((target - 1.0) * current_med) / (
        (2.0 * target - 1.0) * current_med - target
    )


def autostretch(img: AstroImage) -> np.ndarray:
    # Display-only: lift the background to a fixed target for a clear preview.
    return linked_stretch(img.data, _TARGET_BG)
