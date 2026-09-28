"""A night in a few plain sentences, from numbers grading already measured.

grade.py measures every frame and judge() decides each one, but nothing said
what the session as a whole was like (roadmap 2026-09-19 item 3; spec
2026-09-27 decision 6). Pure: FrameStats in, text out. Delivery C calls
build_verdict once per night with that night's frames, so nothing here assumes
the list is a whole folder.

Star SIZE, never "seeing": the S30 Pro samples 3.74″ a pixel, so a 2.5 px FWHM
is about 9″ — set by the pixels and the optics, not the atmosphere.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo
from statistics import median
from typing import Iterable, Sequence

from .grade import (JUDGE_MIN, MIN_MEANINGFUL_EXCESS, STACK_MIN, FrameStats,  # noqa: F401
                    is_master)
# JUDGE_MIN and STACK_MIN are re-exported from here (`verdict.JUDGE_MIN` etc.)
# for existing callers and tests; grade.py is the one place either is written.

# Headline: the share of measurable frames the grader kept.
#
# Measured 2026-09-27, re-run 2026-09-27 split by real night: the
# first pass pooled every sub in a folder into one grade, but Sh2-108,
# IC 1396A_sub and MilkyWay_sub each span more than one real night, so that
# run's "trailing after 00:15" and "softer towards the end" were NIGHT
# BOUNDARIES bleeding into one grade, not a real within-night pattern — that
# pooled table is retracted, not merely superseded. This is per real capture
# night (noon-to-noon local time; 60 frames a night, evenly spaced; MULTI
# marks a folder that split into more than one night):
#   folder                    night        kept  headline                                fwhm    bg
#   IC 1396A_sub   MULTI      2026-08-11    91%  Good night, but trailing after 21:55.    -1%     0%
#   IC 1396A_sub   "          2026-08-24    78%  Good night, but trailing after 00:13.    -6%    -1%
#   IC 1396A_sub   "          2026-08-25    77%  Good night, but trailing after 00:17.    +9%    -2%
#   M 17_sub                  2026-08-07    93%  Good night.                              -4%    -1%
#   M 27_sub                  2026-08-09    92%  Good night.                              +1%     0%
#   M 31_mosaic_sub           2026-08-09    73%  Good night.                              -1%     0%
#   M 31_sub                  2026-08-09   100%  Good night.                              +3%     0%
#   M 33_sub                  2026-08-09    90%  Good night, but clouds after 04:18.      +7%    +1%
#   M 45_sub                  2026-08-09    97%  Good night.                              -2%     0%
#   M 8_sub        MULTI      2026-08-07    88%  Good night.                              +1%     0%
#   M 8_sub        "          2026-08-08    88%  Good night.                              +3%    -2%
#   M16_sub                   2026-08-09    87%  Good night.                              -3%    -1%
#   MilkyWay_sub   MULTI      2026-08-07   100%  Good night.                              +1%     0%
#   MilkyWay_sub   "          2026-08-09    88%  Good night.                              +1%     0%
#   MilkyWay_sub   "          2026-08-11     —   Too few frames to judge the night.        —      —
#   MilkyWay_sub   "          2026-08-24    97%  Good night.                              +0%    -2%
#   MilkyWay_timelapse_sub    2026-08-07   100%  Good night.                              -0%    +0%
#   NGC 6888_sub              2026-08-11    85%  Good night, but trailing after 22:48.    +5%     0%
#   NGC 6992_sub              2026-08-09    95%  Good night.                              +2%     0%
#   NGC 6995_sub              2026-08-12    89%  Good night, but trailing after 00:22.    -2%     0%
#   NGC281_sub                2026-08-26    77%  Good night, but trailing after 00:40.    +4%    -2%
#   Sh2-108        MULTI      2026-09-21    90%  Good night.                              +6%    +0%
#   Sh2-108        "          2026-09-26    88%  Good night.                              +1%    +1%
# Full output (including the 08-11 MilkyWay night's own numbers: 59 of 60
# sampled subs could not be measured — sep's pixel buffer overflow on a very
# bright frame, the same real-world case named above) is in task-1-report.md.
#
# Every one of these 22 real nights reads "Good night" (or "too few to
# judge" — never "Mixed" or "Poor"), including the spec's own example night,
# Sh2-108 2026-09-21 (38 of 42 kept, 90%). The lowest real share is
# M 31_mosaic_sub at 73%, still comfortably above GOOD_SHARE; nothing here
# contradicts 0.70, so it is UNCHANGED. FAIR_SHARE (0.40) still has no real
# night anywhere near it — the earlier run's one candidate, MilkyWay_sub's
# pooled 57%, is exactly the pooling artifact this re-run exists to catch:
# split by night, MilkyWay_sub reads 100%, 88%, too-few, and 97%. FAIR_SHARE
# stays UNCHANGED because nothing contradicts it either — it simply remains
# unvalidated, and needs his eye rather than more of this data.
GOOD_SHARE = 0.70
FAIR_SHARE = 0.40
# Trends, first third against last third. FWHM uses grading's own floor for
# "meaningfully softer" (grade.py, measured on M 45 / M 16 / NGC 6992): a
# change smaller than that is one grading itself would not act on.
FWHM_TREND = MIN_MEANINGFUL_EXCESS
# Re-measured per night (table above): the pooled run's one
# "positive" example for both trends — IC 1396A_sub "softer towards the end"
# and MilkyWay_sub's background "+25%" — do NOT appear once the same subs are
# split by real night; both were comparing across a night boundary, not
# within one. Split correctly, EVERY real night's background thirds ratio
# stays under 3% (worst: MilkyWay_sub 2026-08-24 at -2.5%) and every FWHM
# ratio stays under 10% (worst: IC 1396A_sub 2026-08-25 at +9.4%) — neither
# trend has fired once on real per-night data. That leaves BG_TREND and
# FWHM_TREND UNCHANGED (nothing contradicts them) but genuinely untested by a
# real positive case; they are conservative defaults, not measured floors.
BG_TREND = 0.10
# A reason "starts late and stays" when at least CLUSTER_MIN frames carry it
# and CLUSTER_SHARE_PCT of them come at or after a point past the first third
# of the night. Re-measured per night: 7 of the 22 real nights
# produced a late cluster (all three IC 1396A_sub nights, M 33_sub,
# NGC 6888_sub, NGC 6995_sub, NGC281_sub) and every one reads right against
# its own rejection counts and times — a stronger, more numerous set of real
# examples than the pooled run's 5-of-16, since IC 1396A_sub alone now
# contributes three genuine single-night clusters instead of one misleading
# composite. UNCHANGED.
CLUSTER_MIN = 3
CLUSTER_SHARE_PCT = 80
TREND_MIN_FRAMES = 6       # two a third, at the least

REASON_WORDS = {"trailed": "trailed", "soft_stars": "soft",
                "clouds": "cloudy", "obstructed": "blocked"}
CLUSTER_WORDS = {"trailed": "trailing", "soft_stars": "soft stars",
                 "clouds": "clouds", "obstructed": "something in the way"}
_REASON_ORDER = ("trailed", "soft_stars", "clouds", "obstructed")
_TOO_FEW = ("Too few kept to stack — Stack needs at least 3; you can tick "
            "frames back in by hand.")
# A folder of nothing but stacked masters: "No frame could be measured" would
# be false — every one of them was read, and recognised.
ONLY_MASTERS_HEADLINE = "Only stacked masters here."


@dataclass(frozen=True)
class Verdict:
    headline: str
    details: tuple[str, ...] = ()

    def text(self) -> str:
        return " ".join((self.headline, *self.details))


# --- the pixel scale -----------------------------------------------------------

def pixel_scale(header) -> float | None:
    """Arc-seconds per pixel from FOCALLEN (mm), XPIXSZ (µm) and XBINNING.

    Seestars write XBINNING = 1. MaxIm-style writers fold binning into XPIXSZ
    already; a result outside 0.05–100 ″/px is taken as nonsense, not shown.
    """
    try:
        focal = float(header.get("FOCALLEN") or 0)
        pixel = float(header.get("XPIXSZ") or 0)
        binning = float(header.get("XBINNING") or 1)
    except (TypeError, ValueError):
        return None
    if focal <= 0 or pixel <= 0 or binning <= 0:
        return None
    scale = 206.265 * pixel * binning / focal
    return scale if 0.05 <= scale <= 100.0 else None


def read_pixel_scale(paths: Iterable[str]) -> float | None:
    """The first sub whose header can be read decides — header only, ~0.24 ms."""
    from astropy.io import fits
    for path in paths:
        try:
            header = fits.getheader(path, 0)
        except Exception:        # noqa: BLE001 — unreadable: try the next sub
            continue
        return pixel_scale(header)
    return None


# --- pieces --------------------------------------------------------------------

def _minutes(seconds: float) -> int:
    return 0 if seconds <= 0 else max(1, round(seconds / 60))


def _timed(frames) -> list:
    return sorted((s for s in frames if s.captured is not None), key=lambda s: s.captured)


def _clock(dt: datetime, tz: tzinfo | None) -> str:
    return f"{dt.astimezone(tz):%H:%M}"


def trend_ratios(stats) -> dict[str, tuple[float, float]]:
    """Median FWHM and background of the first and the last third of the
    usable frames, by capture time. Empty when fewer than TREND_MIN_FRAMES
    carry a time."""
    timed = _timed([s for s in stats if not s.error])
    if len(timed) < TREND_MIN_FRAMES:
        return {}
    third = len(timed) // 3
    first, last = timed[:third], timed[-third:]
    out: dict[str, tuple[float, float]] = {}
    f1 = [s.fwhm for s in first if s.star_count > 0 and s.fwhm > 0]
    f2 = [s.fwhm for s in last if s.star_count > 0 and s.fwhm > 0]
    if f1 and f2:
        out["fwhm"] = (float(median(f1)), float(median(f2)))
    b1 = float(median([s.background for s in first]))
    b2 = float(median([s.background for s in last]))
    if b1 > 0 and b2 > 0:
        out["background"] = (b1, b2)
    return out


def late_clusters(stats) -> list[tuple[str, datetime, int]]:
    """Rejection reasons that start part-way through and stay:
    (reason_code, when it starts, how many), the largest first."""
    timed = _timed([s for s in stats if not s.error])
    n = len(timed)
    found = []
    for code in _REASON_ORDER:
        idx = [i for i, s in enumerate(timed) if s.reason and s.reason_code == code]
        if len(idx) < CLUSTER_MIN:
            continue
        # The point from which CLUSTER_SHARE_PCT of them follow. Integer
        # arithmetic: 5 * (1 - 0.8) is 0.9999… in floating point.
        k = len(idx) * (100 - CLUSTER_SHARE_PCT) // 100
        if 3 * idx[k] >= n:
            found.append((code, timed[idx[k]].captured, len(idx)))
    found.sort(key=lambda c: -c[2])          # stable: ties keep _REASON_ORDER
    return found


def _kept_line(usable, kept) -> str:
    n = len(usable)
    text = f"{len(kept)} of {n} {'frame' if n == 1 else 'frames'} kept"
    all_s = sum(s.exposure for s in usable)
    if all_s > 0:
        total = _minutes(all_s)
        text += (f" ({_minutes(sum(s.exposure for s in kept))} of {total} "
                 f"{'minute' if total == 1 else 'minutes'})")
    return text + "."


def _rejected_line(usable) -> str:
    counts: dict[str, int] = {}
    for s in usable:
        if s.reason:
            key = s.reason_code if s.reason_code in REASON_WORDS else "other"
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return ""
    order = list(_REASON_ORDER) + ["other"]
    parts = sorted(counts.items(), key=lambda kv: (-kv[1], order.index(kv[0])))
    return ("Rejected: "
            + " · ".join(f"{n} {REASON_WORDS.get(k, 'other')}" for k, n in parts) + ".")


def _star_size_line(frames, scale) -> str:
    fwhms = [s.fwhm for s in frames if s.star_count > 0 and s.fwhm > 0]
    if not fwhms:
        return ""
    f = float(median(fwhms))
    if scale and scale > 0:
        return f"Stars about {f * scale:.0f}″ across (FWHM {f:.1f} px)."
    return f"Stars: FWHM {f:.1f} px."


def _trend_lines(stats) -> list[str]:
    r = trend_ratios(stats)
    lines = []
    if "fwhm" in r:
        a, b = r["fwhm"]
        if b >= a * (1 + FWHM_TREND):
            lines.append(f"Stars grew softer towards the end (FWHM {a:.1f} → {b:.1f} px).")
        elif a >= b * (1 + FWHM_TREND):
            lines.append(f"Stars grew sharper towards the end (FWHM {a:.1f} → {b:.1f} px).")
    if "background" in r:
        a, b = r["background"]
        if b >= a * (1 + BG_TREND):
            lines.append("Background brightened towards the end (moon or twilight?).")
        elif a >= b * (1 + BG_TREND):
            lines.append("Background darkened towards the end.")
    return lines


def _headline(usable, kept, clusters, tz) -> str:
    if not usable:
        return "No frame could be measured."
    if len(usable) < JUDGE_MIN:
        return "Too few frames to judge the night."
    share = len(kept) / len(usable)
    base = ("Good night" if share >= GOOD_SHARE
            else "Mixed night" if share >= FAIR_SHARE else "Poor night")
    if clusters:
        code, when, _n = clusters[0]
        return f"{base}, but {CLUSTER_WORDS[code]} after {_clock(when, tz)}."
    return base + "."


# --- the verdict ---------------------------------------------------------------

def build_verdict(stats: Sequence[FrameStats], pixel_scale: float | None = None,
                  tz: tzinfo | None = None) -> Verdict | None:
    """The verdict on `stats` — any subset of a grade. Counts the GRADER's
    decisions (`reason`), not the user's ticks: it describes the night.
    Error frames are counted apart and never enter a number."""
    if not stats:
        return None
    usable = [s for s in stats if not s.error]
    kept = [s for s in usable if not s.reason]
    clusters = late_clusters(usable) if len(usable) >= JUDGE_MIN else []
    details: list[str] = []
    if usable:
        details.append(_kept_line(usable, kept))
        rejected = _rejected_line(usable)
        if rejected:
            details.append(rejected)
        if len(kept) < STACK_MIN:
            details.append(_TOO_FEW)
    # Not literally unreadable: the MilkyWay cases traced back to sep's pixel
    # buffer overflowing on very bright frames, which load fine — "measured"
    # is the honest word, matching grade.REASON_MEASURE.
    unmeasured = sum(1 for s in stats if s.error and not is_master(s))
    masters = sum(1 for s in stats if is_master(s))
    if unmeasured:
        details.append(f"{unmeasured} could not be measured.")
    if masters:
        details.append(f"{masters} "
                       + ("is an already stacked master" if masters == 1
                          else "are already stacked masters") + ", left out.")
    if usable:
        size = _star_size_line(kept or usable, pixel_scale)
        if size:
            details.append(size)
        details.extend(_trend_lines(usable))
        for code, when, _n in clusters[1:]:
            words = CLUSTER_WORDS[code]
            details.append(f"{words[0].upper()}{words[1:]} after {_clock(when, tz)}.")
    headline = (ONLY_MASTERS_HEADLINE if masters and not usable and not unmeasured
                else _headline(usable, kept, clusters, tz))
    return Verdict(headline, tuple(details))
