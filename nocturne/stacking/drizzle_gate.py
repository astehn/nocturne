"""Drizzle suitability gate — a pure recommendation, no drizzle engine involved.

Decides whether drizzling a given set of graded/registered frames is likely
to help, based on three independent signals:

  1. Undersampling: drizzle only recovers detail the optics/sensor already
     resolve but the pixel grid throws away. If stars are already soft
     (large FWHM), the data is not undersampled and drizzle has nothing to
     reconstruct.
  2. Dither: drizzle needs sub-pixel offsets between frames to build up
     resolution beyond the native pixel grid. Frames that land on (nearly)
     the same sub-pixel position add noise without adding information.
  3. Frame count: drizzle trades SNR for resolution by spreading each
     frame's flux over a finer grid. Too few frames leaves the stack noisy.

The thresholds below are *soft* starting points, not physical constants.
They are expected to be recalibrated once we have real Seestar S30-Pro
validation data (see docs/audit and the drizzle validation notes).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

# --- Calibrated (provisionally) on synthetic data; revisit with real
# --- S30-Pro validation data before shipping this to users. ---

# Median FWHM (px) of included frames below which the data is considered
# undersampled enough that drizzle can recover extra resolution.
#
# Was 2.0, which warned people off their own data. The S30 Pro sits at about
# 2.5 px FWHM (~3.7"/px), so every typical stack was told "not undersampled" —
# and 2.5 px data does benefit: measured 2026-08-31 on 100 IC 1396A frames,
# drizzle gave FWHM 3.50 on the 2x grid against 4.47 for a plain upsample, 22%
# tighter, with 64% more stars detected. A gate that refuses the camera the app
# is built for is not a gate, it is a bug.
FWHM_MAX = 3.0

# Minimum standard deviation of the fractional (sub-pixel) part of the
# frame-to-frame translation, in each axis, for the dither to be considered
# "well-scattered" rather than accidental/negligible.
MIN_DITHER_SPREAD = 0.15

# Kept-frame count thresholds: below MIN_FRAMES drizzle is discouraged
# (too little data to spread across a finer grid without going noisy);
# at/above GOOD_FRAMES there's enough depth for drizzle to pay off cleanly.
MIN_FRAMES = 20
GOOD_FRAMES = 40

# Below this many kept frames, drizzle is discouraged outright rather than
# just "marginal" — provisional, real-data-calibrated (see module docstring).
VERY_FEW_FRAMES = 10


@dataclass
class DrizzleAdvice:
    level: Literal["recommended", "marginal", "not_recommended"]
    reason: str
    # What decided, and the numbers it measured — what plain_advice words
    # for the person the dialog is for. "no_frames" | "soft" | "few" |
    # "undithered" | "ok".
    code: str = ""
    fwhm: float = 0.0
    frames: int = 0


# The Stack dialog's words (spec 2026-09-28 §5): yes or no, and one plain
# reason. Andreas, of "Undersampled stars (FWHM 2.3px) and enough frames
# (316) — recommended based on…": not written for the audience. The numbers
# go in the tooltip (PlainAdvice.numbers).
SUITS_SUMMARY = "Drizzle suits this stack"
# M6 (final fix wave, 2026-09-28): a "yes" needs no reason of its own — the
# cost it used to repeat here (10x longer, four times the size) is already
# said once, right above, by drizzle_hint's own explanation. Only a "no"
# needs its own sentence, because each is a DIFFERENT reason.
PLAIN_OK = "Suitable for Drizzle."
PLAIN_NO_FRAMES = "Not suitable for Drizzle: no frames are ticked."
PLAIN_SOFT = "Not suitable for Drizzle: your stars are too soft for it to add detail."
PLAIN_FEW = "Not suitable for Drizzle: too few frames ({n}; it needs at least {need})."
PLAIN_UNDITHERED = ("Not suitable for Drizzle: the frames barely moved between "
                    "exposures, so there is nothing to fill the finer grid.")


@dataclass(frozen=True)
class PlainAdvice:
    suits: bool
    text: str        # the sentence under the tick box
    numbers: str     # what was measured, for its tooltip


def _fractional_dither_spread(transforms: list[np.ndarray]) -> float:
    """Std of the fractional parts of the x/y translation components,
    pooled across both axes, as a single scalar dither-scatter measure."""
    if not transforms:
        return 0.0
    tx = np.array([float(m[0, 2]) for m in transforms])
    ty = np.array([float(m[1, 2]) for m in transforms])
    fx = tx - np.floor(tx)
    fy = ty - np.floor(ty)
    return float(np.std(np.concatenate([fx, fy])))


def drizzle_advice(
    stats: list, transforms: list[np.ndarray] | None = None
) -> DrizzleAdvice:
    """Pure function: no I/O, no drizzle engine. Combines FWHM, dither
    scatter and kept-frame count into a simple recommendation.

    ``transforms`` is optional. Grading happens before frame registration,
    so at grade time no transforms exist yet; pass ``None`` (or an empty
    list) in that case and the dither check is skipped entirely — the
    recommendation then rests on FWHM and frame count only, and the
    ``reason`` text is worded so it never claims anything about dither it
    hasn't checked.

    Contract: when ``transforms`` IS provided, it must correspond exactly
    to the *included* frames in ``stats`` — same subset, same order. The
    dither metric pools translations index-for-index with the included
    stats, so a mismatched subset/order silently produces a meaningless
    spread value.
    """
    included = [s for s in stats if s.included]
    n = len(included)

    if n == 0:
        return DrizzleAdvice("not_recommended", "No included frames to evaluate",
                             code="no_frames")

    median_fwhm = float(np.median([s.fwhm for s in included]))
    undersampled = median_fwhm < FWHM_MAX

    # NOTE: dither is only assessed when transforms are supplied (i.e. after
    # registration). At grade time transforms is None/empty and this check
    # is skipped rather than silently treated as "well dithered".
    dither_assessed = bool(transforms)
    dither_spread = _fractional_dither_spread(transforms) if dither_assessed else 0.0
    well_dithered = dither_assessed and dither_spread >= MIN_DITHER_SPREAD

    measured = {"fwhm": median_fwhm, "frames": n}

    if not undersampled:
        return DrizzleAdvice(
            "not_recommended",
            f"Stars are soft (median FWHM {median_fwhm:.1f}px, "
            f"limit {FWHM_MAX:.1f}px) — the data isn't undersampled, "
            "so drizzle has no extra resolution to recover",
            code="soft", **measured,
        )

    if n < MIN_FRAMES:
        return DrizzleAdvice(
            "not_recommended" if n < VERY_FEW_FRAMES else "marginal",
            f"Only {n} usable frames (need at least {MIN_FRAMES}) — "
            "too few to spread across a finer grid without going noisy",
            code="few", **measured,
        )

    if not dither_assessed:
        if n >= GOOD_FRAMES:
            return DrizzleAdvice(
                "recommended",
                f"Undersampled stars (FWHM {median_fwhm:.1f}px) and enough "
                f"frames ({n}) — recommended based on sharpness and frame "
                "count",
                code="ok", **measured,
            )
        return DrizzleAdvice(
            "marginal",
            f"Undersampled stars (FWHM {median_fwhm:.1f}px), but only {n} "
            f"frames (recommended threshold is {GOOD_FRAMES}) — dither not "
            "yet assessed, gains likely modest",
            code="ok", **measured,
        )

    if not well_dithered:
        return DrizzleAdvice(
            "marginal",
            f"Frames are undersampled and there are enough of them ({n}), "
            f"but dithering is weak (spread {dither_spread:.2f}, "
            f"minimum {MIN_DITHER_SPREAD:.2f}) — drizzle may add little",
            code="undithered", **measured,
        )

    if n >= GOOD_FRAMES:
        return DrizzleAdvice(
            "recommended",
            f"Undersampled stars (FWHM {median_fwhm:.1f}px), well-dithered "
            f"({n} frames, spread {dither_spread:.2f}) — drizzle should help",
            code="ok", **measured,
        )

    return DrizzleAdvice(
        "marginal",
        f"Undersampled and well-dithered, but only {n} frames "
        f"(recommended threshold is {GOOD_FRAMES}) — drizzle should help "
        "a little, gains will be modest",
        code="ok", **measured,
    )


def plain_advice(advice: DrizzleAdvice) -> PlainAdvice:
    """Yes or no, and one plain reason (spec 2026-09-28 §5).

    Yes/no is a line through the gate's three levels: "marginal" with enough
    frames (20-39, or dithered but short of 40) is a yes — the gate itself
    says drizzle "should help"; "marginal" for 10-19 frames is a no, as the
    spec's own example has it ("19; it needs at least 20")."""
    if advice.code == "no_frames":
        return PlainAdvice(False, PLAIN_NO_FRAMES, "No frames are ticked.")
    numbers = (f"Median star size FWHM {advice.fwhm:.1f} px — Drizzle helps below "
               f"{FWHM_MAX:.1f} px. {advice.frames} frames ticked — it needs at least "
               f"{MIN_FRAMES}, and {GOOD_FRAMES} or more is where it pays off.")
    if advice.code == "soft":
        return PlainAdvice(False, PLAIN_SOFT, numbers)
    if advice.code == "few":
        return PlainAdvice(False, PLAIN_FEW.format(n=advice.frames, need=MIN_FRAMES),
                           numbers)
    if advice.code == "undithered":
        return PlainAdvice(False, PLAIN_UNDITHERED, numbers)
    return PlainAdvice(True, PLAIN_OK, numbers)
