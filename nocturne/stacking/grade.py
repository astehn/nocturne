from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import sep

from ..core.fits_io import is_stacked_master
from .frames import load_sub, luminance


STRICTNESS_K = {"relaxed": 4.0, "normal": 3.0, "strict": 2.0}

REASON_CLOUDS = "Very few stars — likely clouds or trailing"
REASON_SOFT = "Stars softer than the rest of the session"
WARN_SKY = "Brighter sky (twilight, moon or light pollution) — kept"
REASON_MEASURE = "Couldn't measure this frame — excluded"
REASON_NOT_RAW = "Already-stacked image (not a raw sub) — excluded"


@dataclass
class FrameStats:
    path: str
    star_count: int
    fwhm: float
    background: float
    score: float
    included: bool
    exposure: float = 0.0
    target: str = ""
    reason_code: str = ""   # "clouds" | "soft_stars" | "measure_failed" | "not_raw" | ""
    reason: str = ""        # human-readable, non-empty iff rejected
    warning: str = ""       # human-readable, kept-with-warning (bright sky)
    error: bool = False     # measurement failed; excluded from statistics


def _measure(lum: np.ndarray) -> tuple[int, float, float]:
    lum = np.ascontiguousarray(lum, dtype=np.float32)
    bkg = sep.Background(lum)
    sub = lum - bkg.back()
    objects = sep.extract(sub, 5.0, err=bkg.globalrms)
    star_count = int(len(objects))
    if star_count:
        fwhm = float(2.3548 * np.median(np.sqrt(objects["a"] * objects["b"])))
    else:
        fwhm = 0.0
    return star_count, fwhm, float(bkg.globalback)


def grade_frame(path: str) -> FrameStats:
    try:
        if is_stacked_master(path):
            return FrameStats(path, 0, 0.0, 0.0, 0.0, False,
                              reason_code="not_raw", reason=REASON_NOT_RAW,
                              error=True)
        img = load_sub(path, normalize=False)
        star_count, fwhm, background = _measure(luminance(img.data))
        score = star_count * (1.0 / (1.0 + fwhm)) * (1.0 / (1.0 + background * 10.0))
        return FrameStats(path, star_count, fwhm, background, float(score), True,
                          exposure=float(img.metadata.get("exposure", 0.0) or 0.0),
                          target=str(img.metadata.get("target") or ""))
    except Exception:
        return FrameStats(path, 0, 0.0, 0.0, 0.0, False,
                          reason_code="measure_failed", reason=REASON_MEASURE,
                          error=True)


def upper_gate(values: list[float], k: float) -> float:
    """Siril-style one-tailed gate: median + k*SD, iteratively recomputed
    after clipping values above the gate, until stable. Clipped frames no
    longer pollute the statistics, so one catastrophic frame can't widen
    the gate for everyone else."""
    vals = np.asarray(values, dtype=float)
    while True:
        gate = float(np.median(vals) + k * vals.std())
        keep = vals <= gate
        if keep.all() or keep.sum() < 3:
            return gate
        vals = vals[keep]


def judge(stats: list[FrameStats], strictness: str = "normal") -> None:
    """Apply verdicts in place. Cheap — re-run freely when strictness changes."""
    k = STRICTNESS_K[strictness]
    usable = [s for s in stats if not s.error]
    for s in usable:
        s.included, s.reason_code, s.reason, s.warning = True, "", "", ""
    if len(usable) < 5:
        return  # too few frames to grade reliably — keep everything

    star_median = float(np.median([s.star_count for s in usable]))
    star_floor = 0.5 * star_median
    starred = [s.fwhm for s in usable if s.star_count > 0]
    fwhm_gate = upper_gate(starred, k) if starred else None
    bg_gate = upper_gate([s.background for s in usable], k)

    for s in usable:
        if s.star_count < star_floor:
            s.included = False
            s.reason_code = "clouds"
            s.reason = (f"{REASON_CLOUDS} "
                        f"({s.star_count} stars vs session median {star_median:.0f})")
        elif fwhm_gate is not None and s.fwhm > fwhm_gate:
            s.included = False
            s.reason_code = "soft_stars"
            s.reason = f"{REASON_SOFT} (FWHM {s.fwhm:.1f} vs limit {fwhm_gate:.1f})"
        elif s.background > bg_gate:
            s.warning = WARN_SKY


def grade_frames(paths: list[str], on_progress=None,
                 strictness: str = "normal") -> list[FrameStats]:
    stats: list[FrameStats] = []
    n = len(paths)
    for i, path in enumerate(paths):
        stats.append(grade_frame(path))
        if on_progress is not None:
            on_progress(i + 1, n, os.path.basename(path))

    best = max((s.score for s in stats), default=1.0) or 1.0
    for s in stats:
        s.score = s.score / best
    judge(stats, strictness)
    stats.sort(key=lambda s: s.score)  # worst -> best
    return stats
