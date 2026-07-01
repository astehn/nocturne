from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import sep

from .frames import load_sub, luminance


@dataclass
class FrameStats:
    path: str
    star_count: int
    fwhm: float
    background: float
    score: float
    included: bool


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
    star_count, fwhm, background = _measure(luminance(load_sub(path, normalize=False).data))
    score = star_count * (1.0 / (1.0 + fwhm)) * (1.0 / (1.0 + background * 10.0))
    return FrameStats(path, star_count, fwhm, background, float(score), True)


def _mad(values: list[float], med: float) -> float:
    return float(np.median([abs(v - med) for v in values]))


def grade_frames(paths: list[str], on_progress=None) -> list[FrameStats]:
    stats: list[FrameStats] = []
    n = len(paths)
    for i, path in enumerate(paths):
        stats.append(grade_frame(path))
        if on_progress is not None:
            on_progress(i + 1, n, os.path.basename(path))

    counts = [s.star_count for s in stats]
    fwhms = [s.fwhm for s in stats]
    bgs = [s.background for s in stats]
    mc, mf, mb = np.median(counts), np.median(fwhms), np.median(bgs)
    dc, df, db = _mad(counts, mc), _mad(fwhms, mf), _mad(bgs, mb)
    best = max((s.score for s in stats), default=1.0) or 1.0

    for s in stats:
        s.score = s.score / best
        low_stars = dc > 0 and s.star_count < mc - 3 * dc
        bad_fwhm = df > 0 and s.fwhm > mf + 3 * df
        bad_bg = db > 0 and s.background > mb + 3 * db
        s.included = not (low_stars or bad_fwhm or bad_bg)

    stats.sort(key=lambda s: s.score)  # worst -> best
    return stats
