"""Star balance: sky grey AND the typical star white.

Sky balance (``background_neutralize``) only greys the sky, so a light-polluted
or filtered stack keeps a star cast. This measures the stars with SPCC's
detector (``spcc._measure``: local-annulus flux, so the nebula behind a star
does not count) and applies gains to the signal *above the sky* only. Applied
to the whole frame the gains would recolour the sky, and a later
``background_neutralize`` would undo them (it is a multiplicative re-level).

Exposure is green-anchored, like ``background_neutralize`` and SPCC.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nocturne.core.color import _background_mask, background_neutralize
from nocturne.core.image import AstroImage
from nocturne.core.spcc import _SAT, _measure

STAR_BALANCE_VERSION = 1

# Calibrated 2026-11-13 on three real masters (usable stars after the flux cut
# -> gains R/B): IC 1848 drizzle 7680x4320 4040 -> 0.64/1.11 (2.1 s);
# M17 220x10s 5901 -> 0.75/1.03; NGC 1907 175x20s 10527 -> 0.86/1.37.
# Real masters sit 270x above the floor, so _MIN_STARS stays at SPCC's 15
# (a nebula-filled crop or very short stack is what it catches). Real gains
# span 0.64-1.37; 0.4-2.5 leaves ~1.6x headroom each way, beyond which the
# "cast" is a mis-measurement (a synthetic R x4 cast is rejected).
_MIN_STARS = 15
_GAIN_LO, _GAIN_HI = 0.4, 2.5
# Green-flux band, as in the approved spike: drops faint noisy and brightest blown stars.
_FLUX_PCT = (30.0, 98.0)


@dataclass
class StarBalanceResult:
    gains: tuple[float, float, float]
    n_stars: int


def star_balance_gains(data: np.ndarray) -> StarBalanceResult | None:
    """Gains (R, 1, B) from the median star colour of sky-neutralised linear
    data, or None when too few usable stars or any gain is absurd."""
    d = np.clip(np.asarray(data, np.float32), 0.0, None)
    m = _measure(d)
    if m is None:
        return None
    _x, _y, peakmax, flux = m
    ok = (flux > 0).all(axis=1) & (peakmax < _SAT)
    if not ok.any():
        return None
    g = flux[:, 1]
    lo, hi = np.percentile(g[ok], _FLUX_PCT)
    ok &= (g >= lo) & (g <= hi)
    n = int(ok.sum())
    if n < _MIN_STARS:
        return None
    f = flux[ok].astype(np.float64)
    gains = (1.0 / float(np.median(f[:, 0] / f[:, 1])), 1.0,
             1.0 / float(np.median(f[:, 2] / f[:, 1])))
    if not all(_GAIN_LO < v < _GAIN_HI for v in gains):
        return None
    return StarBalanceResult(gains, n)


def _sky_level(data: np.ndarray) -> np.ndarray:
    """Per-channel sky median over the empty-sky mask, black borders excluded."""
    lum = data.mean(axis=2)
    valid = data.max(axis=2) > 0
    # Percentiles must ignore the border, so build the mask on valid pixels only.
    full = np.zeros(lum.shape, bool)
    full[valid] = _background_mask(lum[valid])
    return np.array([float(np.median(data[..., c][full])) for c in range(3)],
                    np.float32)


def apply_star_balance(img: AstroImage, version: int = STAR_BALANCE_VERSION
                       ) -> tuple[AstroImage, StarBalanceResult | None]:
    if version != STAR_BALANCE_VERSION:
        raise ValueError(f"unknown star balance version {version!r}")
    if not img.is_color:
        return img.copy(), None
    data = background_neutralize(img.data.astype(np.float32).copy())
    res = star_balance_gains(data)
    meta = dict(img.metadata)
    if res is None:
        return AstroImage(data, is_linear=img.is_linear, metadata=meta), None
    valid = data.max(axis=2) > 0
    sky = _sky_level(data)
    gain = np.array(res.gains, np.float32)
    out = sky + (data - sky) * gain
    out = np.clip(out, 0.0, 1.0)
    out[~valid] = 0.0               # a zero border must stay zero
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear, metadata=meta), res
