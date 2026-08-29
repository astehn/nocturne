"""Split a raw Bayer frame into its two gas planes.

Its own module because the registration pool needs it too, and that pool must
not import haoiii — haoiii imports stacker, stacker imports the pool, so the
cycle would close. It must also stay free of Qt and of anything heavy: a spawned
worker re-imports this file in every process.
"""
from __future__ import annotations

import numpy as np
from astropy.io import fits

from ..core.fits_io import _bayer_pattern


def load_cfa(path: str) -> tuple:
    """Load a raw 2D CFA sub: (cfa float32, pattern, exptime). Raises ValueError
    for a 3D/already-debayered file."""
    with fits.open(path) as hdul:
        data = np.asarray(hdul[0].data)
        header = hdul[0].header
    if data.ndim != 2:
        raise ValueError("Ha/OIII extraction needs raw (un-debayered) subs")
    exp = float(header.get("EXPTIME", 0.0) or 0.0)
    return data.astype(np.float32), _bayer_pattern(header), exp


def _site_offsets(pattern: str) -> dict:
    """Map each colour to its (row, col) offsets within the 2x2 CFA tile."""
    offsets: dict = {"R": [], "G": [], "B": []}
    for i, ch in enumerate(pattern.upper()):
        offsets[ch].append((i // 2, i % 2))
    return offsets


def _lerp_axis(a: np.ndarray, off: int, n: int, axis: int) -> np.ndarray:
    """Bilinear resample along one axis onto n samples at source coord (i-off)/2,
    clamping at the edges. Separable because the scale is exactly 2 and the
    offsets are whole pixels, which makes this bit-identical to a 2D
    map_coordinates call (asserted in the tests) and 2.8x faster than one.
    """
    idx = (np.arange(n, dtype=np.float32) - off) / 2.0
    i0 = np.floor(idx).astype(np.intp)
    w = (idx - i0).astype(np.float32)
    lim = a.shape[axis] - 1
    lo = a.take(np.clip(i0, 0, lim), axis=axis)
    hi = a.take(np.clip(i0 + 1, 0, lim), axis=axis)
    return lo * (1.0 - w.reshape((-1, 1) if axis == 0 else (1, -1))) + \
        hi * w.reshape((-1, 1) if axis == 0 else (1, -1))


def _upsample_site(cfa: np.ndarray, r: int, c: int, shape: tuple) -> np.ndarray:
    """Bilinearly interpolate ONE CFA sub-plane onto the full grid, honouring
    where its samples actually sit.

    Sub-plane element [i, j] is full-frame pixel (2i + r, 2j + c), so full-frame
    row R reads sub-plane row (R - r)/2. Decimating and then resizing every
    colour identically — which is what this replaced — throws that offset away:
    red lives at (0,1) in a GRBG tile and blue at (1,0), so Ha and OIII came out
    about a pixel apart from each other (predicted (0.75, 0.75) from the tile,
    measured (0.84, 1.02) on real M16 masters).
    """
    sub = cfa[r::2, c::2]
    return _lerp_axis(_lerp_axis(sub, r, shape[0], 0), c, shape[1], 1).astype(np.float32)


def _plane(cfa: np.ndarray, sites: list, shape: tuple) -> np.ndarray:
    """Full-res mean of the sub-planes at the given (row, col) site offsets.

    Each is interpolated to full res BEFORE averaging. Averaging first, as this
    used to, silently blurs: a GRBG tile's two greens sit at (0,0) and (1,1), so
    adding the raw sub-planes averages pixels a diagonal step apart.
    """
    return np.mean([_upsample_site(cfa, r, c, shape) for r, c in sites],
                   axis=0).astype(np.float32)


# Green and blue both measure the same OIII line, so the OIII plane is a weighted
# average of two estimates of one quantity — and the optimal weight for that is
# the ratio of their SNR SQUARED, not an even split.
#
# Measured on 20-sub masters, green plane vs blue plane, SNR as (nebula - sky)/sky
# noise:  M16 10.81 vs 5.39 (ratio 2.006), IC 1396A 8.28 vs 4.06 (ratio 2.039).
# Squared, that predicts 4.02:1 and 4.16:1. Sweeping the weight found the optimum
# at 4:1 on BOTH targets, so the constant is derived rather than fitted. The
# plateau is broad — 3:1 to 6:1 all sit within 1% of the peak — and the even split
# this replaced cost 26% of OIII SNR (M16 9.40 -> 11.79, IC 1396A 7.18 -> 9.09).
#
# Green beats blue by more than the sqrt(2) its extra CFA site would explain,
# because blue also has lower QE toward 500.7nm.
#
# CAVEAT: both test sets are FILTER='LP', not dualband — the case this tool is
# actually for. A dualband blue sees far less continuum, so the ratio could move.
# Re-measure on dualband subs before trusting the exact value; the breadth of the
# plateau is what makes 4:1 safe in the meantime.
_OIII_GREEN_WEIGHT = 4.0


def extract_cfa_planes(cfa: np.ndarray, pattern: str) -> tuple:
    """(ha, oiii) full-res float32. Ha = red sites; OIII = green and blue
    combined by SNR, each interpolated from where the sensor actually sampled
    it."""
    if cfa.ndim != 2:
        raise ValueError("extract_cfa_planes needs a 2D CFA frame")
    off = _site_offsets(pattern)
    shape = cfa.shape
    ha = _plane(cfa, off["R"], shape)
    w = _OIII_GREEN_WEIGHT
    oiii = (w * _plane(cfa, off["G"], shape) + _plane(cfa, off["B"], shape)) / (w + 1.0)
    return ha, oiii.astype(np.float32)
