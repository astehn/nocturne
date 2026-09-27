"""The night's verdict (spec 2026-09-27 decision 6; §7: golden strings from
fixed stats, arcsec from a real S30 Pro header).

Every clock time here is asked for in an explicit zone (tz=UTC or +02:00), so
the strings do not depend on the machine running the suite.
"""
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from astropy.io import fits

from nocturne.stacking import verdict as vd
from nocturne.stacking.grade import REASON_MEASURE, REASON_NOT_RAW, FrameStats, judge
from nocturne.stacking.verdict import (Verdict, build_verdict, late_clusters,
                                       pixel_scale, read_pixel_scale, trend_ratios)

UTC = timezone.utc
CEST = timezone(timedelta(hours=2))
T0 = datetime(2026, 9, 21, 22, 0, tzinfo=UTC)
# From Light_SH2-108_10.0s_LP_20260921-221930.fit (read 2026-09-27):
# CREATOR='ZWO Seestar S30 Pro' XPIXSZ=2.90000009536743 XBINNING=1 FOCALLEN=160.0
S30_HEADER = {"FOCALLEN": 160.0, "XPIXSZ": 2.90000009536743, "XBINNING": 1}
S30 = 206.265 * 2.90000009536743 / 160.0          # 3.7385 ″/px
REAL_SUB = "/Volumes/Work/Astro/Sh2-108/Light_SH2-108_10.0s_LP_20260921-221930.fit"
TOO_FEW = "Too few kept to stack — Stack needs at least 3; you can tick frames back in by hand."


def _f(i, fwhm=2.5, bg=1000.0, code="", stars=800, exposure=10.0, timed=True):
    """Frame i, taken 5 minutes after frame i-1 from 22:00 UTC. A `code`
    makes it a grader rejection with that reason_code."""
    s = FrameStats(f"/x/Light_{i:03d}.fit", stars, fwhm, bg, 0.5, not code,
                   exposure=exposure)
    if code:
        s.reason_code, s.reason = code, f"{code} (test)"
    s.captured = T0 + timedelta(minutes=5 * i) if timed else None
    return s


def _error(i, code="measure_failed"):
    return FrameStats(f"/x/bad_{i}.fit", 0, 0.0, 0.0, 0.0, False, reason_code=code,
                      reason=REASON_NOT_RAW if code == "not_raw" else REASON_MEASURE,
                      error=True)


def _spec_night(timed=True):
    """The spec's example in miniature: 24 frames from 22:00, two soft early,
    four trailed from 23:20 on, the sky 20% brighter in the last third, and
    one file that could not be read."""
    stats = []
    for i in range(24):
        code = ("soft_stars" if i in (1, 12)
                else "trailed" if i in (16, 18, 20, 22) else "")
        stats.append(_f(i, fwhm=3.1 if code == "soft_stars" else 2.5,
                        bg=1200.0 if i >= 16 else 1000.0, code=code, timed=timed))
    return stats + [_error(0)]


# --- the golden strings ------------------------------------------------------

def test_the_spec_shaped_night_reads_as_one_paragraph():
    v = build_verdict(_spec_night(), pixel_scale=S30, tz=UTC)
    assert v == Verdict(
        "Good night, but trailing after 23:20.",
        ("18 of 24 frames kept (3 of 4 minutes).",
         "Rejected: 4 trailed · 2 soft.",
         "1 could not be read.",
         "Stars about 9″ across (FWHM 2.5 px).",
         "Background brightened towards the end (moon or twilight?)."))
    assert v.text().startswith("Good night, but trailing after 23:20. 18 of 24 frames")


def test_the_clock_is_the_zone_asked_for():
    v = build_verdict(_spec_night(), pixel_scale=S30, tz=CEST)
    assert v.headline == "Good night, but trailing after 01:20."


def test_without_optics_the_star_size_is_in_pixels():
    v = build_verdict(_spec_night(), pixel_scale=None, tz=UTC)
    assert "Stars: FWHM 2.5 px." in v.details
    assert not any("″" in d for d in v.details)


def test_the_word_seeing_never_appears():
    """FWHM 2.5 px on the S30 Pro is ~9″ — sampling and optics, not the
    atmosphere. Calling it seeing would mislead (decision 2)."""
    for stats in (_spec_night(), _spec_night(timed=False), [_f(0)], [_error(1)]):
        for scale in (None, S30):
            v = build_verdict(stats, pixel_scale=scale, tz=UTC)
            assert "seeing" not in v.text().lower()


# --- error frames: counted apart, never in the statistics --------------------

def test_error_frames_are_counted_apart_and_never_in_the_numbers():
    base = build_verdict(_spec_night()[:-1], pixel_scale=S30, tz=UTC)
    more = _spec_night()[:-1] + [_error(1), _error(2), _error(3, "not_raw")]
    v = build_verdict(more, pixel_scale=S30, tz=UTC)
    assert v.headline == base.headline
    assert v.details[0] == base.details[0] == "18 of 24 frames kept (3 of 4 minutes)."
    assert "3 could not be read." not in v.details
    assert "2 could not be read." in v.details
    assert "1 is an already stacked master, left out." in v.details


def test_only_error_frames():
    v = build_verdict([_error(0), _error(1), _error(2, "not_raw")], tz=UTC)
    assert v == Verdict("No frame could be measured.",
                        ("2 could not be read.",
                         "1 is an already stacked master, left out."))


def test_an_empty_list_has_no_verdict():
    assert build_verdict([]) is None


# --- 0, 1 and a handful of frames (Review Focus 4) ---------------------------

def test_nothing_kept_is_a_poor_night_and_says_it_cannot_stack():
    stats = [_f(i, code="clouds") for i in range(6)]
    v = build_verdict(stats, pixel_scale=S30, tz=UTC)
    assert v == Verdict("Poor night.",
                        ("0 of 6 frames kept (0 of 1 minute).",
                         "Rejected: 6 cloudy.",
                         TOO_FEW,
                         "Stars about 9″ across (FWHM 2.5 px)."))


def test_one_frame_is_too_few_to_judge():
    v = build_verdict([_f(0)], pixel_scale=S30, tz=UTC)
    assert v == Verdict("Too few frames to judge the night.",
                        ("1 of 1 frame kept (1 of 1 minute).",
                         TOO_FEW,
                         "Stars about 9″ across (FWHM 2.5 px)."))


def test_below_five_frames_the_headline_agrees_with_judge():
    """judge() keeps everything below 5 usable frames; the headline must not
    call such a night good or poor."""
    stats = [_f(i, fwhm=2.5 + 0.4 * i) for i in range(4)]
    judge(stats, "normal")
    assert all(not s.reason for s in stats), "judge no longer keeps all below 5"
    v = build_verdict(stats, tz=UTC)
    assert v.headline == "Too few frames to judge the night."
    assert TOO_FEW not in v.details
    assert vd.JUDGE_MIN == 5


@pytest.mark.parametrize("rejected, headline", [
    (3, "Good night."),       # 7 of 10 = 0.70: GOOD_SHARE is inclusive
    (5, "Mixed night."),      # 0.50
    (6, "Mixed night."),      # 0.40: FAIR_SHARE is inclusive
    (7, "Poor night."),       # 0.30
])
def test_the_headline_follows_the_share_kept(rejected, headline):
    # rejections at the START, so no "after HH:MM" clause joins the headline
    stats = [_f(i, code="clouds" if i < rejected else "") for i in range(10)]
    assert build_verdict(stats, tz=UTC).headline == headline


# --- the rejected line --------------------------------------------------------

def test_reasons_are_ordered_by_count_then_a_fixed_order():
    codes = ["obstructed"] * 2 + ["clouds"] * 2 + ["soft_stars"] * 3 + ["mystery"]
    stats = [_f(i, code=c) for i, c in enumerate(codes)] + [_f(20 + i) for i in range(30)]
    v = build_verdict(stats, tz=UTC)
    assert "Rejected: 3 soft · 2 cloudy · 2 blocked · 1 other." in v.details


def test_minutes_are_left_out_when_no_exposure_is_known():
    stats = [_f(i, exposure=0.0) for i in range(6)]
    assert build_verdict(stats, tz=UTC).details[0] == "6 of 6 frames kept."


# --- trends: first third against last third, above a threshold only ----------

def _trend(fwhms=None, bgs=None, n=9):
    fwhms = fwhms or [2.5] * n
    bgs = bgs or [1000.0] * n
    return [_f(i, fwhm=fwhms[i], bg=bgs[i]) for i in range(n)]


def test_softening_stars_are_reported():
    v = build_verdict(_trend(fwhms=[2.5] * 3 + [2.7] * 3 + [2.9] * 3), tz=UTC)
    assert "Stars grew softer towards the end (FWHM 2.5 → 2.9 px)." in v.details


def test_sharpening_stars_are_reported():
    v = build_verdict(_trend(fwhms=[2.9] * 3 + [2.7] * 3 + [2.5] * 3), tz=UTC)
    assert "Stars grew sharper towards the end (FWHM 2.9 → 2.5 px)." in v.details


def test_a_change_below_the_threshold_says_nothing():
    # +12%, under MIN_MEANINGFUL_EXCESS (15%)
    v = build_verdict(_trend(fwhms=[2.5] * 3 + [2.6] * 3 + [2.8] * 3,
                             bgs=[1000.0] * 3 + [1030.0] * 3 + [1050.0] * 3), tz=UTC)
    assert not any("towards the end" in d for d in v.details)


def test_a_darkening_sky_is_reported():
    v = build_verdict(_trend(bgs=[1200.0] * 3 + [1100.0] * 3 + [1000.0] * 3), tz=UTC)
    assert "Background darkened towards the end." in v.details


def test_trend_ratios_need_six_timed_frames():
    assert trend_ratios([_f(i) for i in range(5)]) == {}
    r = trend_ratios(_trend(bgs=[1000.0] * 3 + [1100.0] * 3 + [1200.0] * 3))
    assert r["background"] == (1000.0, 1200.0) and r["fwhm"] == (2.5, 2.5)


# --- a reason that starts late and stays --------------------------------------

def test_a_reason_spread_through_the_night_is_not_late():
    stats = [_f(i, code="trailed" if i in (2, 9, 15, 21) else "") for i in range(24)]
    assert late_clusters(stats) == []
    assert build_verdict(stats, tz=UTC).headline == "Good night."


def test_the_bigger_late_cluster_leads_and_the_other_follows():
    stats = []
    for i in range(30):
        code = ("trailed" if i in (20, 22, 24, 26)
                else "soft_stars" if i in (21, 23, 25) else "")
        stats.append(_f(i, fwhm=3.1 if code == "soft_stars" else 2.5, code=code))
    v = build_verdict(stats, pixel_scale=S30, tz=UTC)
    assert v == Verdict("Good night, but trailing after 23:40.",
                        ("23 of 30 frames kept (4 of 5 minutes).",
                         "Rejected: 4 trailed · 3 soft.",
                         "Stars about 9″ across (FWHM 2.5 px).",
                         "Soft stars after 23:45."))
    assert [c for c, _w, _n in late_clusters(stats)] == ["trailed", "soft_stars"]


# --- no capture times (Review Focus 3) ----------------------------------------

def test_without_capture_times_there_are_no_trends_and_no_late_clause():
    v = build_verdict(_spec_night(timed=False), pixel_scale=S30, tz=UTC)
    assert v.headline == "Good night."
    assert not any("towards the end" in d or " after " in d for d in v.details)
    assert "18 of 24 frames kept (3 of 4 minutes)." in v.details
    assert late_clusters(_spec_night(timed=False)) == []


# --- a subset, for delivery C -------------------------------------------------

def test_any_subset_can_be_judged_on_its_own():
    first_hour = _spec_night()[:12]
    v = build_verdict(first_hour, pixel_scale=S30, tz=UTC)
    assert v.details[0] == "11 of 12 frames kept (2 of 2 minutes)."


# --- the pixel scale ----------------------------------------------------------

def test_the_s30_pro_header_gives_3_74_arcsec_per_pixel():
    assert pixel_scale(S30_HEADER) == pytest.approx(3.7385, abs=1e-3)
    assert pixel_scale({**S30_HEADER, "XBINNING": 2}) == pytest.approx(7.477, abs=1e-3)
    assert pixel_scale({"FOCALLEN": 160.0, "XPIXSZ": 2.9}) == pytest.approx(3.7385, abs=1e-3)


@pytest.mark.parametrize("header", [
    {}, {"FOCALLEN": 160.0}, {"XPIXSZ": 2.9}, {"FOCALLEN": 0, "XPIXSZ": 2.9},
    {"FOCALLEN": "long", "XPIXSZ": 2.9}, {"FOCALLEN": 0.001, "XPIXSZ": 2.9},
    {"FOCALLEN": 160.0, "XPIXSZ": -2.9},
])
def test_missing_or_absurd_optics_give_no_scale(header):
    assert pixel_scale(header) is None


def _fits(path, **cards):
    hdu = fits.PrimaryHDU(np.zeros((4, 4), np.uint16))
    for k, v in cards.items():
        hdu.header[k] = v
    hdu.writeto(path)
    return str(path)


def test_the_first_readable_sub_decides(tmp_path):
    junk = tmp_path / "junk.fit"
    junk.write_text("not a FITS file")
    first = _fits(tmp_path / "a.fit", FOCALLEN=160.0, XPIXSZ=2.9)
    second = _fits(tmp_path / "b.fit", FOCALLEN=250.0, XPIXSZ=2.9)
    paths = [str(tmp_path / "missing.fit"), str(junk), first, second]
    assert read_pixel_scale(paths) == pytest.approx(3.7385, abs=1e-3)
    bare = _fits(tmp_path / "c.fit")
    assert read_pixel_scale([bare, first]) is None, "the FIRST readable header decides"
    assert read_pixel_scale([]) is None


@pytest.mark.skipif(not os.path.exists(REAL_SUB), reason="his capture drive is not mounted")
def test_a_real_s30_pro_sub_reads_3_74(tmp_path):
    """READ-ONLY: one header read from his real Sh2-108 sub (spec §7)."""
    before = os.stat(REAL_SUB).st_mtime_ns
    assert read_pixel_scale([REAL_SUB]) == pytest.approx(3.7385, abs=1e-3)
    assert os.stat(REAL_SUB).st_mtime_ns == before
