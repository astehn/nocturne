"""Frames MOVED to rejected/ are drawn faint grey, not amber (agreed with
Andreas 2026-10-01, his VdB 141 night: 347 moved after 05:14). Amber means
"rejected, still in the folder, still your call"; once moved that decision is
made, but the dots stay as the record of the night.
"""
from nocturne.ui import quality_chart as qc
from nocturne.ui.quality_chart import (KEPT_COLOUR, MOVED_COLOUR, NOTE_TIME,
                                       REJECTED_COLOUR)

from tests.ui.test_quality_chart import _close, _night, _pixel, _shown


def _with_moved():
    """_night() plus one more soft frame that has been moved to rejected/."""
    stats = _night()
    stats[4].reason = "soft"
    stats[4].moved = True
    return stats


def test_a_moved_frame_is_grey_and_an_unmoved_reject_stays_amber(qtbot):
    b = _shown(qtbot, _with_moved())
    assert b.chart.point_colour(4) == MOVED_COLOUR
    assert b.chart.point_colour(2) == REJECTED_COLOUR, "not moved: still your call"
    assert b.chart.point_colour(0) == KEPT_COLOUR
    assert MOVED_COLOUR not in (REJECTED_COLOUR, KEPT_COLOUR)
    assert _close(_pixel(b.chart, b.chart.point_pos(4)), MOVED_COLOUR)


def test_moved_frames_stay_on_the_chart_as_history(qtbot):
    b = _shown(qtbot, _with_moved())
    assert 4 in [row for row, _x in b.chart.plotted()]


def test_the_legend_names_moved_only_when_there_are_any(qtbot):
    b = _shown(qtbot, _night())
    assert "moved" not in b.chart.note()
    b = _shown(qtbot, _with_moved())
    assert b.chart.note().startswith(NOTE_TIME) and "● moved" in b.chart.note()
    html = b.chart_panel.caption.text()
    assert f'color:{REJECTED_COLOUR}">●</span>' in html
    assert f'color:{MOVED_COLOUR}">●</span>' in html


def test_moving_them_back_makes_them_amber_again(qtbot):
    stats = _with_moved()
    b = _shown(qtbot, stats)
    stats[4].moved = False
    b.chart.refresh()
    assert b.chart.point_colour(4) == REJECTED_COLOUR
    assert "moved" not in b.chart.note()


def test_the_trend_line_is_unchanged_by_moving(qtbot):
    """Only the colour changes: the smoothed line and the scale read the same
    frames whether or not a reject has been moved."""
    stats = _with_moved()
    b = _shown(qtbot, stats)
    moved_trend, moved_range = b.chart._trend_fwhm(), b.chart._value_range()
    stats[4].moved = False
    b.chart.refresh()
    assert b.chart._trend_fwhm() == moved_trend
    assert b.chart._value_range() == moved_range


def test_folded_the_legend_still_drops_cleanly(qtbot):
    b = _shown(qtbot, _with_moved())
    b.chart_panel.fold_btn.click()
    assert "●" not in b.chart_panel.caption.text()


def test_when_every_reject_is_moved_the_legend_names_only_moved(qtbot):
    """No amber dot left, so no amber legend (review 2026-10-01)."""
    stats = _with_moved()
    stats[2].moved = True
    b = _shown(qtbot, stats)
    note = b.chart.note()
    assert "● moved" in note and "rejected" not in note
