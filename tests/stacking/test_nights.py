"""Nights run noon to noon, local time (spec 2026-09-28 §9.1). Pinned to
Stockholm, his zone, so the tests mean the same thing on any machine."""
import os
from datetime import date, datetime, timedelta, timezone

import pytest

from tests.local_zone import pin_local_zone
from nocturne.stacking.capture_time import attach_local, from_date_obs, from_filename
from nocturne.stacking.grade import FrameStats
from nocturne.stacking.nights import (NO_DATE_LABEL, night_label, night_of,
                                      split_nights)


@pytest.fixture(autouse=True)
def stockholm(monkeypatch):
    pin_local_zone(monkeypatch, "Europe/Stockholm")


def _frame(name, dt):
    s = FrameStats(f"/subs/{name}", 800, 2.5, 1000.0, 0.5, True)
    s.captured = dt
    return s


def test_a_session_past_midnight_is_one_night_named_after_its_evening():
    # His Sh2-108: the 26th into the 27th, by the Seestar's own file stamps.
    evening = from_filename("Light_SH2-108_10.0s_LP_20260926-213000.fit")
    after_midnight = from_filename("Light_SH2-108_10.0s_LP_20260927-004000.fit")
    assert night_of(evening) == night_of(after_midnight) == date(2026, 9, 26)


def test_noon_is_where_one_night_turns_into_the_next():
    before = attach_local(datetime(2026, 9, 27, 11, 59))
    at = attach_local(datetime(2026, 9, 27, 12, 0))
    assert night_of(before) == date(2026, 9, 26)
    assert night_of(at) == date(2026, 9, 27)


def test_the_header_in_utc_lands_in_the_local_night():
    # 2026-09-26 22:30 UTC is 00:30 CEST on the 27th: the 26th's night.
    assert night_of(from_date_obs("2026-09-26T22:30:00")) == date(2026, 9, 26)
    # 10:30 UTC is 12:30 CEST: past LOCAL noon, so the 27th's, though UTC
    # noon is still ahead. A boundary at UTC noon would call it the 26th's.
    assert night_of(from_date_obs("2026-09-27T10:30:00")) == date(2026, 9, 27)


def test_his_sh2_108_folder_is_two_nights_not_three():
    stamps = ["20260921-221930", "20260921-235900", "20260926-213000",
              "20260927-000934", "20260927-013000"]
    stats = [_frame(f"Light_SH2-108_10.0s_LP_{t}.fit",
                    from_filename(f"Light_SH2-108_10.0s_LP_{t}.fit")) for t in stamps]
    nights = split_nights(stats)
    assert [n.label for n in nights] == ["21 Sep", "26 Sep"]
    assert [len(n.frames) for n in nights] == [2, 3]


@pytest.mark.parametrize("stamp", ["20261025-023000", "20261025-013000",
                                   "20261025-033000", "20261024-230000"])
def test_the_night_the_clocks_go_back_stays_one_night(stamp):
    """2026-10-25 03:00 CEST becomes 02:00 CET. 02:30 happens twice and the
    file stamp cannot say which; either way it is the 24th's night."""
    assert night_of(from_filename(f"x_{stamp}.fit")) == date(2026, 10, 24)


def test_the_night_the_clocks_go_back_in_utc_is_one_night_too():
    start = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)     # 20:00 CEST
    times = [start + timedelta(minutes=10 * i) for i in range(72)]  # to 06:00 CET
    assert {night_of(t) for t in times} == {date(2026, 10, 24)}


def test_the_night_the_clocks_go_forward_stays_one_night():
    # 2026-03-29 02:00 CET becomes 03:00 CEST; 02:30 never happens.
    assert night_of(from_filename("x_20260329-023000.fit")) == date(2026, 3, 28)
    assert night_of(from_filename("x_20260329-043000.fit")) == date(2026, 3, 28)


def test_a_frame_with_no_capture_time_is_in_no_night_and_listed_last():
    a = _frame("a.fit", datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc))
    lost = _frame("renamed.fit", None)
    b = _frame("b.fit", datetime(2026, 9, 26, 20, 0, tzinfo=timezone.utc))
    nights = split_nights([lost, b, a])
    assert [n.key for n in nights] == [date(2026, 9, 21), date(2026, 9, 26), None]
    assert nights[-1].label == NO_DATE_LABEL and nights[-1].frames == (lost,)


def test_one_night_keeps_the_order_it_was_given():
    t = datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc)
    stats = [_frame(f"{i}.fit", t + timedelta(minutes=(7 * i) % 30)) for i in range(5)]
    (night,) = split_nights(stats)
    assert list(night.frames) == stats


def test_the_year_is_named_only_when_the_folder_spans_two():
    assert night_label(date(2026, 9, 21)) == "21 Sep"
    a = _frame("a.fit", datetime(2025, 9, 21, 20, 0, tzinfo=timezone.utc))
    b = _frame("b.fit", datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc))
    assert [n.label for n in split_nights([a, b])] == ["21 Sep 2025", "21 Sep 2026"]


def test_nothing_is_no_nights():
    assert split_nights([]) == []


def test_one_frame_is_one_night_of_one():
    a = _frame("a.fit", datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc))
    (night,) = split_nights([a])
    assert night.key == date(2026, 9, 21) and night.frames == (a,)


def test_a_session_crossing_new_year_is_one_night_named_after_the_31st():
    # 2026-12-31 23:30 into 2027-01-01 00:40: past midnight AND past New
    # Year's, still one night, named after the evening it started.
    evening = _frame("a.fit", datetime(2026, 12, 31, 22, 30, tzinfo=timezone.utc))
    after = _frame("b.fit", datetime(2027, 1, 1, 0, 40, tzinfo=timezone.utc))
    (night,) = split_nights([evening, after])
    assert night.key == date(2026, 12, 31) and night.label == "31 Dec"


def test_a_dec_31_night_and_a_jan_1_night_both_carry_their_year():
    # Two distinct nights either side of New Year's — consecutive calendar
    # dates, different years: with_year's "spans more than one year" must
    # fire here, not only across a much wider gap.
    dec31 = _frame("a.fit", datetime(2026, 12, 31, 20, 0, tzinfo=timezone.utc))
    jan1 = _frame("b.fit", datetime(2027, 1, 1, 20, 0, tzinfo=timezone.utc))
    assert [n.label for n in split_nights([dec31, jan1])] == ["31 Dec 2026", "1 Jan 2027"]


SH2_108 = "/Volumes/Work/Astro/Sh2-108"
REAL = [f"{SH2_108}/Light_SH2-108_10.0s_LP_{t}.fit"
        for t in ("20260921-221930", "20260926-232829", "20260927-002109")]


@pytest.mark.skipif(not all(os.path.exists(p) for p in REAL),
                    reason="his capture drive is not mounted")
def test_his_real_headers_put_past_midnight_in_the_evenings_night():
    """Spec §7, "a real folder header check": DATE-OBS (UTC) of three of his
    subs, read-only — the 21st, and the 26th either side of midnight."""
    from nocturne.stacking.capture_time import read_capture_time
    before = [os.stat(p).st_mtime_ns for p in REAL]
    assert [night_of(read_capture_time(p)) for p in REAL] == [
        date(2026, 9, 21), date(2026, 9, 26), date(2026, 9, 26)]
    assert [os.stat(p).st_mtime_ns for p in REAL] == before


# --- A remote site (2026-10-17) ---------------------------------------------
#
# Noon-to-noon in THIS computer's zone splits a night shot far away: a Texas
# session processed in a central European zone turns over at 05:00 Texas
# time, mid-session.
# Every Seestar sub carries SITELONG, so the night turns at the SITE's solar
# noon instead — date(UTC + SITELONG/15 h - 12 h) — named after the site's
# evening. No usable SITELONG: exactly as before.

from zoneinfo import ZoneInfo

from nocturne.stacking.nights import night_key

TEXAS = -104.0           # Starfront, west Texas
CDT = ZoneInfo("America/Chicago")


def _at_site(name, dt, site_long):
    s = _frame(name, dt)
    s.site_long = site_long
    return s


def _texas_session(evening: date, n=67):
    """19:00 to 06:00 Texas clock time, a frame every 10 minutes."""
    start = datetime(evening.year, evening.month, evening.day, 19, 0, tzinfo=CDT)
    return [_at_site(f"{evening}_{i}.fit", start + timedelta(minutes=10 * i), TEXAS)
            for i in range(n)]


def test_three_texas_nights_processed_in_europe_are_three_nights():
    evenings = [date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 15)]
    stats = [s for e in evenings for s in _texas_session(e)]
    nights = split_nights(stats)
    assert [n.key for n in nights] == evenings
    assert [n.label for n in nights] == ["12 Oct", "13 Oct", "15 Oct"]
    assert [len(n.frames) for n in nights] == [67, 67, 67]


def test_without_the_site_the_same_frames_split_as_they_used_to():
    """The defect, kept visible: in the pinned European zone the Texas nights turn
    over at 05:00 Texas time and three nights become more."""
    stats = [s for e in (date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 15))
             for s in _texas_session(e)]
    for s in stats:
        s.site_long = None
    assert len(split_nights(stats)) > 3


def test_the_night_turns_at_the_sites_solar_noon():
    # Solar noon at 104 W is 18:56 UTC (104/15 h = 6 h 56 min behind UTC).
    noon_utc = datetime(2026, 10, 13, 18, 56, tzinfo=timezone.utc)
    assert night_of(noon_utc, TEXAS) == date(2026, 10, 13)
    assert night_of(noon_utc - timedelta(seconds=1), TEXAS) == date(2026, 10, 12)


@pytest.mark.parametrize("site_long", [
    179.9,             # just west of the date line: the evening is UTC morning
    -179.9,            # just east of it: UTC morning of the NEXT day
    0.5,               # Greenwich
    TEXAS,
])
def test_a_session_either_side_of_the_date_line_is_one_night(site_long):
    # 20:00 to 05:00 solar time at the site, named after the site's evening.
    offset = timedelta(hours=site_long / 15)
    evening = datetime(2026, 10, 13, 20, 0, tzinfo=timezone.utc) - offset
    times = [evening + timedelta(minutes=15 * i) for i in range(37)]
    assert {night_of(t, site_long) for t in times} == {date(2026, 10, 13)}


def test_a_longitude_written_0_to_360_is_the_same_place():
    t = datetime(2026, 10, 13, 3, 0, tzinfo=timezone.utc)
    assert night_of(t, 360 + TEXAS) == night_of(t, TEXAS) == date(2026, 10, 12)


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), "west", "",
                                 400.0, -181.0, 0.0, True])
def test_no_usable_longitude_is_exactly_the_old_behaviour(bad):
    # 0.0 counts as missing: a sub saved without a location fix carries 0, and
    # this computer's zone is the better guess then.
    times = [datetime(2026, 10, 13, h, 30, tzinfo=timezone.utc) for h in range(24)]
    assert [night_of(t, bad) for t in times] == [night_of(t) for t in times]


def test_night_key_reads_the_frames_site():
    t = datetime(2026, 10, 13, 10, 30, tzinfo=timezone.utc)   # 12:30 pinned zone, 03:34 Texas
    assert night_key(_at_site("a.fit", t, TEXAS)) == date(2026, 10, 12)
    assert night_key(_frame("b.fit", t)) == date(2026, 10, 13)


def test_his_real_sessions_group_exactly_as_before():
    """DATE-OBS and SITELONG sampled from real S30 Pro capture folders (two
    sites in the owner's data), processed in the pinned zone: every frame's
    night — not just the grouping, the key and so the label too — is
    unchanged by reading the site."""
    import json
    path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "night_headers.json")
    with open(path, encoding="utf-8") as fh:
        folders = json.load(fh)["folders"]
    multi = 0
    for name, rows in folders.items():
        with_site = [_at_site(f"{i}.fit", from_date_obs(t), lon) for i, (t, lon) in enumerate(rows)]
        before = [night_of(s.captured) for s in with_site]
        assert all(s.site_long for s in with_site), name   # the site really is in play
        assert [night_key(s) for s in with_site] == before, name
        assert ([(n.key, n.label, len(n.frames)) for n in split_nights(with_site)]
                == [(n.key, n.label, len(n.frames))
                    for n in split_nights([_frame(f"{i}.fit", s.captured)
                                           for i, s in enumerate(with_site)])]), name
        multi += len(set(before)) > 1
    assert multi >= 3        # three of the folders span several nights
