"""Combine two stacked gas planes into a linear two-gas master.

The extractor writes Ha and OIII un-equalised so the real ratio between them
survives; this is where the user decides what to do with it. The two ends of the
balance are not new maths — they are the plane as measured and the same plane
put through the extractor's own fit.
"""
from __future__ import annotations

import numpy as np

from ..stacking.haoiii import apply_oiii_fit, oiii_fit
from .image import AstroImage


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
