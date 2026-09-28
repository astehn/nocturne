"""Nights ticked in and out of the shared frame list (spec 2026-09-28 §9.2):
out of the list, every count, the chart and the stack — and back with his
own ticks inside, as he left them."""
from datetime import datetime, timedelta, timezone

import numpy as np
from PySide6.QtCore import QThreadPool

from nocturne.stacking.grade import REASON_NOT_RAW, FrameStats, judge
from nocturne.stacking.nights import night_key
from nocturne.ui.frame_browser import SHOW_ALL, SHOW_KEPT, SHOW_REJECTED, FrameBrowser

EVE_21 = datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc)
EVE_26 = datetime(2026, 9, 26, 20, 0, tzinfo=timezone.utc)


def _night(start, tag, n=6):
    """n frames 10 minutes apart; the third has a tenth of the stars, so
    judge() rejects it as cloud."""
    out = []
    for i in range(n):
        s = FrameStats(f"/x/{tag}{i}.fit", 80 if i == 2 else 800, 2.5, 0.02, 0.5,
                       True, exposure=10.0)
        s.captured = start + timedelta(minutes=10 * i)
        out.append(s)
    return out


def _two_nights():
    stats = _night(EVE_21, "a") + _night(EVE_26, "b")
    judge(stats, "normal")
    assert [bool(s.reason) for s in stats].count(True) == 2
    return stats


def _master():
    m = FrameStats("/x/master.fits", 0, 0.0, 0.0, 0.0, False, reason_code="not_raw",
                   reason=REASON_NOT_RAW, error=True)
    m.captured = EVE_21 + timedelta(minutes=5)      # stacked during the 21st's night
    return m


def _browser(qtbot, stats):
    b = FrameBrowser(QThreadPool.globalInstance())
    qtbot.addWidget(b)
    b.preview_controller.loader = lambda p: np.zeros((8, 8, 3), np.float32)
    b.set_frames(stats)
    return b


def _counts(b):
    return {m: int(btn.text().split()[-1]) for m, btn in b._show_buttons.items()}


def _included(stats):
    return [bool(s.included) for s in stats]


A = night_key(_night(EVE_21, "a")[0])
B = night_key(_night(EVE_26, "b")[0])


def test_an_unticked_night_leaves_the_list_the_counts_and_the_stack(qtbot):
    stats = _two_nights()
    b = _browser(qtbot, stats)
    before = _included(stats)
    b.set_night_on(A, False)
    assert sorted(b.view_rows()) == list(range(6, 12))
    assert _counts(b) == {SHOW_ALL: 6, SHOW_KEPT: 5, SHOW_REJECTED: 1}
    assert all(s.path.startswith("/x/b") for s in b.checked_frames())
    assert _included(stats) == before, "unticking a night wrote to its frames"


def test_ticked_back_it_returns_with_his_own_ticks(qtbot):
    stats = _two_nights()
    b = _browser(qtbot, stats)
    b.set_checked(0, False)              # a kept frame of the 21st, unticked by hand
    b.set_checked(2, True)               # the 21st's cloud frame, ticked back in
    before, touched = _included(stats), b.user_touched
    b.set_night_on(A, False)
    b.set_night_on(A, True)
    assert _included(stats) == before and b.user_touched == touched
    assert sorted(b.view_rows()) == list(range(12))
    assert _counts(b) == {SHOW_ALL: 12, SHOW_KEPT: 10, SHOW_REJECTED: 2}


def test_select_all_and_none_never_reach_an_unticked_night(qtbot):
    stats = _two_nights()
    b = _browser(qtbot, stats)
    b.set_checked(0, False)
    b.set_night_on(A, False)
    before = _included(stats)[:6]
    b.select_all()
    b.select_none()
    assert _included(stats)[:6] == before


def test_reset_to_suggested_waits_for_an_unticked_night(qtbot):
    stats = _two_nights()
    b = _browser(qtbot, stats)
    b.set_checked(0, False)              # the 21st
    b.set_checked(6, False)              # the 26th
    b.set_night_on(A, False)
    before = _included(stats)[:6]
    b.reset_to_suggested()
    assert _included(stats)[:6] == before and 0 in b.user_touched
    assert stats[6].included and 6 not in b.user_touched
    b.set_night_on(A, True)
    b.reset_to_suggested()
    assert stats[0].included and not b.user_touched


def test_a_strictness_change_keeps_the_ticks_inside_an_unticked_night(qtbot):
    stats = _two_nights()
    b = _browser(qtbot, stats)
    b.set_checked(0, False)
    b.set_checked(2, True)
    b.set_night_on(A, False)
    before = _included(stats)[:6]
    judge(stats, "strict")
    b.refresh_verdicts()
    assert _included(stats)[:6] == before


def test_the_chart_leaves_an_unticked_night_out(qtbot):
    stats = _two_nights()
    b = _browser(qtbot, stats)
    assert b.chart.point_count() == 12
    b.set_night_on(B, False)
    assert b.chart.point_count() == 6
    assert {row for row, _x in b.chart.plotted()} == set(range(6))


def test_the_preview_moves_off_a_night_that_goes(qtbot):
    """Qt moves the cursor to a neighbour still listed; the preview header
    and the chart's ring follow it there."""
    stats = _two_nights()
    b = _browser(qtbot, stats)
    b.set_current_row(11)
    b.set_night_on(B, False)
    assert b.current_row() == 5 and b.chart.current_row() == 5
    assert b.preview_name.text() == "a5.fit"


def test_a_night_ticked_back_after_all_were_off_is_previewed(qtbot):
    stats = _two_nights()
    b = _browser(qtbot, stats)
    b.set_night_on(A, False)
    b.set_night_on(B, False)
    b.set_night_on(B, True)
    assert b.current_row() == 6 and b.preview_name.text() == "b0.fit"


def test_every_night_unticked_leaves_nothing_to_stack_or_show(qtbot):
    stats = _two_nights()
    b = _browser(qtbot, stats)
    b.set_night_on(A, False)
    b.set_night_on(B, False)
    assert b.row_count() == 0 and b.checked_frames() == []
    assert _counts(b) == {SHOW_ALL: 0, SHOW_KEPT: 0, SHOW_REJECTED: 0}
    assert b.current_row() == -1 and b.preview_name.text() == ""
    assert b.chart_panel.isHidden()


def test_a_master_stays_listed_whichever_nights_are_off(qtbot):
    stats = _two_nights() + [_master()]
    b = _browser(qtbot, stats)
    b.set_night_on(A, False)
    assert 12 in b.view_rows()
    assert _counts(b)[SHOW_ALL] == 6


def test_a_new_grade_ticks_every_night_again(qtbot):
    stats = _two_nights()
    b = _browser(qtbot, stats)
    b.set_night_on(A, False)
    b.set_frames(_two_nights())
    assert b.nights_off() == set() and b.row_count() == 12


def test_a_night_toggle_tells_the_host(qtbot):
    b = _browser(qtbot, _two_nights())
    with qtbot.waitSignals([b.nights_changed, b.selection_changed], timeout=500):
        b.set_night_on(A, False)
    with qtbot.assertNotEmitted(b.nights_changed):
        b.set_night_on(A, False)             # already off: nothing to say
