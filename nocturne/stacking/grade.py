from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import sep

from ..core.fits_io import is_stacked_master
from ..core.tasks import current
from .frames import load_sub, luminance


def _check_cancel() -> None:
    tok = current()
    if tok is not None:
        tok.check()      # raises Cancelled if the user cancelled


STRICTNESS_K = {"relaxed": 4.0, "normal": 3.0, "strict": 2.0}

# 1/Phi^-1(3/4): scales a MAD to the sigma of an equivalent Gaussian, so k keeps
# its usual "how many sigma" meaning without inheriting sigma's fragility.
_MAD_TO_SIGMA = 1.4826

REASON_CLOUDS = "Very few stars — likely clouds or trailing"
REASON_SOFT = "Stars softer than the rest of the session"
REASON_TRAILED = "Stars trailed — wind, a nudge, or a tracking slip"
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
    # Median semi-major/semi-minor axis ratio; 1.0 is perfectly round. Kept
    # separate from fwhm because fwhm CANNOT see it: 2.3548*sqrt(a*b) is the
    # geometric mean of the axes, so a star stretched along one axis and
    # squeezed along the other scores an identical FWHM to a round one.
    elongation: float = 1.0
    exposure: float = 0.0
    target: str = ""
    reason_code: str = ""   # "clouds" | "soft_stars" | "trailed" | "measure_failed" | "not_raw" | ""
    reason: str = ""        # human-readable, non-empty iff rejected
    warning: str = ""       # human-readable, kept-with-warning (bright sky)
    error: bool = False     # measurement failed; excluded from statistics


def _measure(lum: np.ndarray) -> tuple[int, float, float, float]:
    lum = np.ascontiguousarray(lum, dtype=np.float32)
    bkg = sep.Background(lum)
    sub = lum - bkg.back()
    objects = sep.extract(sub, 5.0, err=bkg.globalrms)
    star_count = int(len(objects))
    if star_count:
        fwhm = float(2.3548 * np.median(np.sqrt(objects["a"] * objects["b"])))
        # Every detection, flagged or not: dropping sep's flagged objects was
        # tried and measured on real frames to move the result by at most 0.11%,
        # because they are ~1% of detections and the median absorbs them.
        elongation = float(np.median(objects["a"] / np.maximum(objects["b"], 1e-6)))
    else:
        fwhm = 0.0
        elongation = 1.0
    return star_count, fwhm, float(bkg.globalback), elongation


def _score(star_count: int, fwhm: float, background: float, elongation: float) -> float:
    """How good a frame is, 0..1 after normalising, worst to best.

    Also decides the REFERENCE: the dialog passes frames best-first and
    run_stack registers everything against include[0]. Elongation belongs here
    for that reason and not only in the gate — a trailed frame can survive
    judging and still be a poor thing to align a whole session to.
    """
    return (star_count
            * (1.0 / (1.0 + fwhm))
            * (1.0 / (1.0 + background * 10.0))
            * (1.0 / max(elongation, 1e-6)))


def grade_frame(path: str) -> FrameStats:
    try:
        if is_stacked_master(path):
            return FrameStats(path, 0, 0.0, 0.0, 0.0, False,
                              reason_code="not_raw", reason=REASON_NOT_RAW,
                              error=True)
        img = load_sub(path, normalize=False)
        star_count, fwhm, background, elongation = _measure(luminance(img.data))
        score = _score(star_count, fwhm, background, elongation)
        return FrameStats(path, star_count, fwhm, background, float(score), True,
                          elongation=elongation,
                          exposure=float(img.metadata.get("exposure", 0.0) or 0.0),
                          target=str(img.metadata.get("target") or ""))
    except Exception:
        return FrameStats(path, 0, 0.0, 0.0, 0.0, False,
                          reason_code="measure_failed", reason=REASON_MEASURE,
                          error=True)


def upper_gate(values: list[float], k: float) -> float:
    """One-tailed gate: median + k * a ROBUST sigma, estimated from the MAD.

    The goal has not changed — one catastrophic frame must not widen the gate
    for everyone else — but the means has. This used to compute median + k*SD
    and then iterate, clipping values above the gate and recomputing until
    stable. Clipping shrinks the SD every pass, so on a skewed distribution the
    gate walks steadily downward, and it can end up BELOW the median: a gate
    beneath the median rejects most TYPICAL frames, which is never what an
    outlier test can mean.

    Measured on 60 real M31 frames at k=2.0 (strict): the elongation gate
    collapsed to 1.132 against a median of 1.158 and condemned 37 of 60 frames,
    and the background gate to 6684 against a median around 15000, flagging 41
    of 60. FWHM escaped only because its distribution is tighter — 6.8% relative
    spread against elongation's 12.8% — so the bug was invisible until roundness
    was added.

    The MAD is not inflated by the tail in the first place, so no iteration is
    needed and the gate cannot fall below the median. On the same frames it
    leaves FWHM almost unchanged (rejecting 1/4/7 at k=4/3/2 against the old
    1/5/9) while making elongation and background behave sensibly.
    """
    vals = np.asarray(values, dtype=float)
    median = float(np.median(vals))
    mad = float(np.median(np.abs(vals - median))) * _MAD_TO_SIGMA
    return median + k * mad


def order_best_first(stats: list["FrameStats"]) -> list:
    """Frame paths in the order a stacker wants them: registration reference
    first, then descending quality.

    Both stackers align everything to paths[0], so whatever leads this list is
    the reference — and that is a different question from overall quality, which
    is why pick_reference exists. Shared because it was not: Stack promoted the
    sharpest frame and Ha/OIII sorted by score alone, so the same subs with the
    same settings came out framed differently (measured 2026-08-29: (3680, 1976)
    against (3696, 1984), identical once they agreed on a reference). The rest
    stay in score order, which is what the user reviewed.
    """
    chosen = sorted(stats, key=lambda s: s.score, reverse=True)
    ref = pick_reference(chosen)
    if ref is not None:
        chosen = [ref] + [s for s in chosen if s is not ref]
    return [s.path for s in chosen]


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
    # Same session-relative rule as the others: a uniformly trailed session has
    # no outlier and keeps everything, which is the right answer when the
    # alternative is handing the user nothing.
    shapes = [s.elongation for s in usable if s.star_count > 0]
    round_gate = upper_gate(shapes, k) if shapes else None

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
        elif round_gate is not None and s.elongation > round_gate:
            s.included = False
            s.reason_code = "trailed"
            s.reason = (f"{REASON_TRAILED} (stars {s.elongation:.2f}x longer than "
                        f"wide, limit {round_gate:.2f})")
        elif s.background > bg_gate:
            s.warning = WARN_SKY


# Enough stars for astroalign to solve a transform against, with margin. The
# thinnest real frame measured across four sessions had 282; this is a floor
# against a genuinely empty frame, not a quality bar.
_REF_MIN_STARS = 50


def pick_reference(stats: list["FrameStats"]):
    """The frame every other frame is registered to, or None if there is none.

    NOT the same question as which frames are worth keeping, and deliberately
    not answered by `_score`. That score multiplies a RAW UNBOUNDED star count
    by bounded quality terms, so when transparency varies the count swamps
    sharpness. Measured across four of Andreas's real sessions, its correlation
    with FWHM degrades as star count spreads and inverts on the difficult one:

        star-count spread   1.27x   1.71x   2.62x   2.99x
        r(score, FWHM)     -0.969  -0.917  -0.863  +0.698

    At 2.99x it chose a reference of FWHM 2.95 when a 2.14 frame was available,
    and `run_stack` aligns the whole session to `paths[0]`.

    What a reference actually wants is the best GEOMETRY — sharp and round —
    plus merely enough stars to solve a transform. So star count is a threshold
    here and not a weight, and the ranking is fwhm x elongation: elongation is
    included for the same reason it is in `_score`, because FWHM is blind to
    trailing by construction (the geometric mean of the axes is unchanged when
    a star is stretched one way and squeezed the other).
    """
    included = [s for s in stats if s.included and not s.error and s.star_count > 0]
    if not included:
        return None
    pool = [s for s in included if s.star_count >= _REF_MIN_STARS] or included
    return min(pool, key=lambda s: s.fwhm * max(s.elongation, 1e-6))


def grade_frames(paths: list[str], on_progress=None,
                 strictness: str = "normal") -> list[FrameStats]:
    stats: list[FrameStats] = []
    n = len(paths)
    for i, path in enumerate(paths):
        _check_cancel()
        stats.append(grade_frame(path))
        if on_progress is not None:
            on_progress(i + 1, n, os.path.basename(path))

    best = max((s.score for s in stats), default=1.0) or 1.0
    for s in stats:
        s.score = s.score / best
    judge(stats, strictness)
    stats.sort(key=lambda s: s.score)  # worst -> best
    return stats
