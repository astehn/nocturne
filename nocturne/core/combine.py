"""Combine two stacked gas planes into a linear two-gas master.

The extractor writes Ha and OIII un-equalised so the real ratio between them
survives; this is where the user decides what to do with it. The two ends of the
balance are not new maths — they are the plane as measured and the same plane
put through the extractor's own fit.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import shift as _ndshift
from skimage.registration import phase_cross_correlation

from .image import AstroImage


def _mad(x: np.ndarray) -> float:
    return float(np.median(np.abs(x - np.median(x))))


def oiii_fit(ha: np.ndarray, oiii: np.ndarray) -> tuple:
    """(scale, oiii median, ha median) for the linear match. Measured apart from
    where it is applied, so a master the user chose not to trim can still be fitted
    on its fully-covered core — median and MAD are the whole fit, and the ragged
    fringe is built from fewer frames, so letting it in drags the pedestal off."""
    mad_o = _mad(oiii)
    a = (_mad(ha) / mad_o) if mad_o > 1e-9 else 1.0
    return a, float(np.median(oiii)), float(np.median(ha))


def apply_oiii_fit(oiii: np.ndarray, fit: tuple) -> np.ndarray:
    a, med_o, med_ha = fit
    return np.clip(a * (oiii - med_o) + med_ha, 0.0, None).astype(np.float32)


def renorm_oiii(ha: np.ndarray, oiii: np.ndarray) -> np.ndarray:
    """Linear-fit OIII to Ha (Siril ExtractHaOIII): match median and MAD."""
    return apply_oiii_fit(oiii, oiii_fit(ha, oiii))


# Above the (0.08, 0.26) px residual measured between a correct Ha/OIII pair on
# real M16 masters, and below the ~1 px error the extractor itself carried before
# 7ce1c17 — which was visible as colour fringing on stars.
OFFSET_TOLERANCE_PX = 0.5


def measure_offset(ha: np.ndarray, oiii: np.ndarray) -> tuple:
    """(dy, dx) to apply to OIII to put it on Ha. Sub-pixel."""
    shift_yx, _, _ = phase_cross_correlation(
        np.asarray(ha, np.float64), np.asarray(oiii, np.float64),
        upsample_factor=20, normalization=None)
    return float(shift_yx[0]), float(shift_yx[1])


def align_to(oiii: np.ndarray, shift: tuple) -> np.ndarray:
    """OIII resampled onto Ha's grid by the offset measure_offset found."""
    return _ndshift(np.asarray(oiii, np.float32), shift,
                    order=1, mode="nearest").astype(np.float32)


def combine_gases(ha: np.ndarray, oiii: np.ndarray, balance: float = 1.0,
                  metadata: dict | None = None) -> AstroImage:
    """Linear master: Ha in red, OIII in green and blue.

    `balance` runs from 0 (OIII exactly as measured, true ratio intact) to 1
    (OIII matched to Ha's median and spread, which is what the extractor's own
    colour master contains). Defaults to 1 so an unfamiliar user gets the
    balanced result and reaches for the ratio on purpose.

    Both channels are divided by ONE peak. Scaling them separately would land
    each at 1.0 and silently discard the ratio.
    """
    if ha.shape != oiii.shape:
        raise ValueError(f"Ha is {ha.shape} but OIII is {oiii.shape}")
    t = float(np.clip(balance, 0.0, 1.0))
    matched = apply_oiii_fit(oiii, oiii_fit(ha, oiii))
    out = (1.0 - t) * oiii + t * matched
    rgb = np.stack([ha, out, out], axis=2).astype(np.float32)
    peak = float(rgb.max()) or 1.0
    h, w = rgb.shape[:2]
    meta = dict(metadata or {})
    meta.update({"width": w, "height": h})
    return AstroImage(np.clip(rgb / peak, 0.0, 1.0).astype(np.float32),
                      is_linear=True, metadata=meta)
