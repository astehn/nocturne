"""The Time column's source. Header first (UTC), the file name second (local).

The pair below is REAL: Andreas' Sh2-108 sub Light_SH2-108_10.0s_LP_20260921-221941.fit
carries DATE-OBS 2026-09-21T20:19:21.392456 (read 2026-09-27). Two hours apart
is CEST: the header is UTC, the name is local. Pinned to a zone so the test
means the same thing on any machine.
"""
import time
from datetime import datetime, timezone

import pytest

from nocturne.stacking.capture_time import (
    from_date_obs, from_filename, full_label, read_capture_time, time_label,
)
from tests.stacking.synthetic import make_star_field, write_color_fits

REAL_NAME = "Light_SH2-108_10.0s_LP_20260921-221941.fit"
REAL_DATE_OBS = "2026-09-21T20:19:21.392456"


@pytest.fixture
def stockholm(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Stockholm")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_the_header_is_read_as_utc_and_shown_in_local_time(stockholm):
    dt = from_date_obs(REAL_DATE_OBS)
    assert dt == datetime(2026, 9, 21, 20, 19, 21, 392456, tzinfo=timezone.utc)
    assert time_label(dt) == "21 · 22:19", "shown in UTC, not the time he remembers"


def test_the_file_name_is_read_as_local_time(stockholm):
    dt = from_filename(f"/x/{REAL_NAME}")
    assert dt.astimezone(timezone.utc) == datetime(2026, 9, 21, 20, 19, 41, tzinfo=timezone.utc)
    assert time_label(dt) == "21 · 22:19"


def test_header_and_name_of_one_real_sub_agree(stockholm):
    """Both sources describe the same moment to within the exposure and the
    write — if either were read in the wrong zone they would be 2 h apart."""
    gap = from_filename(REAL_NAME) - from_date_obs(REAL_DATE_OBS)
    assert abs(gap.total_seconds()) < 60


def test_a_session_past_midnight_keeps_the_calendar_day(stockholm):
    """The label is a timestamp; nights are delivery C's business."""
    dt = from_filename("Light_SH2-108_10.0s_LP_20260927-000934.fit")
    assert time_label(dt) == "27 · 00:09"


@pytest.mark.parametrize("value", ["", None, "yesterday", "2026-13-40T99:00:00"])
def test_a_bad_header_value_is_no_time(value):
    assert from_date_obs(value) is None


@pytest.mark.parametrize("name", ["a.fit", "Light_M31_10.0s.fit",
                                  "Light_M31_20261399-250000.fit"])
def test_a_name_without_a_valid_stamp_is_no_time(name):
    assert from_filename(name) is None


def test_the_header_wins_over_the_name(tmp_path, stockholm):
    p = tmp_path / "Light_X_10.0s_LP_20260101-010101.fit"
    write_color_fits(p, make_star_field(shape=(40, 40)), header={"DATE-OBS": REAL_DATE_OBS})
    assert read_capture_time(str(p)) == from_date_obs(REAL_DATE_OBS)


def test_the_name_is_used_when_the_header_has_no_date(tmp_path, stockholm):
    p = tmp_path / REAL_NAME
    write_color_fits(p, make_star_field(shape=(40, 40)))
    assert read_capture_time(str(p)) == from_filename(REAL_NAME)


def test_an_unreadable_file_still_gets_its_name_stamp(tmp_path, stockholm):
    p = tmp_path / REAL_NAME
    p.write_bytes(b"not a fits file")
    assert read_capture_time(str(p)) == from_filename(REAL_NAME)


def test_no_source_is_no_time_and_a_dash(tmp_path):
    p = tmp_path / "plain.fit"
    write_color_fits(p, make_star_field(shape=(40, 40)))
    assert read_capture_time(str(p)) is None
    assert time_label(None) == "—" and full_label(None) == ""


def test_the_full_label_carries_date_and_seconds(stockholm):
    assert full_label(from_filename(REAL_NAME)) == "21 Sep 2026 22:19:41"
