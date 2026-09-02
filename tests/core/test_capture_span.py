"""How a capture date is written on a plate.

A Seestar run routinely crosses midnight — NGC 281 went 2026-08-26 20:06 to
2026-08-27 03:24, with 924 frames on one date and 590 on the other — so naming
either single date is quietly wrong about most of the night.
"""
from nocturne.core.fits_io import format_capture_span


def test_a_single_night():
    assert format_capture_span("2026-08-26T20:06:02") == "26 Aug 2026"


def test_a_night_that_crosses_midnight():
    """Andreas' actual NGC 281 session."""
    assert format_capture_span("2026-08-26T20:06:02",
                               "2026-08-27T03:24:30") == "26–27 Aug 2026"


def test_a_night_that_crosses_a_month():
    assert format_capture_span("2026-08-31T22:00:00",
                               "2026-09-01T02:00:00") == "31 Aug – 1 Sep 2026"


def test_a_night_that_crosses_a_year():
    assert format_capture_span("2026-12-31T23:00:00",
                               "2027-01-01T02:00:00") == "31 Dec 2026 – 1 Jan 2027"


def test_an_end_on_the_same_date_collapses():
    """Most sessions do not cross midnight; they must not read as a range."""
    assert format_capture_span("2026-08-26T20:06:02",
                               "2026-08-26T23:50:00") == "26 Aug 2026"


def test_no_end_at_all():
    """Every master written before DATE-END existed."""
    assert format_capture_span("2026-08-26T20:06:02", None) == "26 Aug 2026"


def test_it_is_never_iso():
    """Explicitly rejected: "a caption is read by people, and
    2026-08-26 - 2026-08-27 is a machine talking"."""
    out = format_capture_span("2026-08-26T20:06", "2026-08-27T03:24")
    assert "2026-08-26" not in out and "-08-" not in out


def test_junk_does_not_raise():
    for bad in (None, "", "not a date", "2026", 12345):
        assert format_capture_span(bad) == ""
    assert format_capture_span("2026-08-26T20:06", "rubbish") == "26 Aug 2026"
