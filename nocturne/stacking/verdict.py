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

from .grade import MIN_MEANINGFUL_EXCESS, FrameStats

# Headline: the share of measurable frames the grader kept.
# PROVISIONAL. The one measurement behind them is his Sh2-108 folder: 190 of
# 254 kept (75%), which the spec's own example calls a good night, so
# GOOD_SHARE must sit at or below 0.75 — 0.70 leaves it a margin. FAIR_SHARE
# is a starting value with no measurement yet. Task 1 of the delivery-B plan
# runs this over his real folders and records the headlines; the values change
# only on his word, and the measured shares go here.
GOOD_SHARE = 0.70
FAIR_SHARE = 0.40
# Trends, first third against last third. FWHM uses grading's own floor for
# "meaningfully softer" (grade.py, measured on M 45 / M 16 / NGC 6992): a
# change smaller than that is one grading itself would not act on.
FWHM_TREND = MIN_MEANINGFUL_EXCESS
# PROVISIONAL, same calibration run: `background` is sep's globalback on RAW
# counts, pedestal included, so a relative change reads smaller than the sky's.
BG_TREND = 0.10
# A reason "starts late and stays" when at least CLUSTER_MIN frames carry it
# and CLUSTER_SHARE_PCT of them come at or after a point past the first third
# of the night. PROVISIONAL, same calibration run.
CLUSTER_MIN = 3
CLUSTER_SHARE_PCT = 80
TREND_MIN_FRAMES = 6       # two a third, at the least
JUDGE_MIN = 5              # judge() keeps every frame below this many (grade.py)
STACK_MIN = 3              # both dialogs refuse fewer ("at least 3 frames")

REASON_WORDS = {"trailed": "trailed", "soft_stars": "soft",
                "clouds": "cloudy", "obstructed": "blocked"}
CLUSTER_WORDS = {"trailed": "trailing", "soft_stars": "soft stars",
                 "clouds": "cloud", "obstructed": "something in the way"}
_REASON_ORDER = ("trailed", "soft_stars", "clouds", "obstructed")
_TOO_FEW = ("Too few kept to stack — Stack needs at least 3; you can tick "
            "frames back in by hand.")


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
    unreadable = sum(1 for s in stats if s.error and s.reason_code != "not_raw")
    masters = sum(1 for s in stats if s.error and s.reason_code == "not_raw")
    if unreadable:
        details.append(f"{unreadable} could not be read.")
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
    return Verdict(_headline(usable, kept, clusters, tz), tuple(details))
