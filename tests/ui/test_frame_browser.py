"""The shared frame list + preview (spec 2026-09-27 §2.4-2.5, §7).

Rows in FrameBrowser's API are SOURCE rows — indices into the host's list —
so every assertion here names a frame by its place in `stats`, and the view's
order is read separately with view_rows().
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt, QThreadPool
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from nocturne.stacking.grade import (REASON_MEASURE, REASON_NOT_RAW, FrameStats,
                                     judge)
from nocturne.ui import frame_browser as fb
from nocturne.ui.frame_browser import FrameBrowser

T0 = datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc)


def _frame(i, minute=None, fwhm=2.5, stars=800):
    s = FrameStats(f"/x/f{i}.fit", stars, fwhm, 0.02, 0.5, True, exposure=10.0)
    s.captured = None if minute is None else T0 + timedelta(minutes=minute)
    return s


def _error_frame(i, code):
    """A stacked master (not_raw) or a sub that couldn't be measured
    (measure_failed) — grade_frame() always hands these back with
    included=False and error=True; never a candidate to tick in."""
    reason = REASON_NOT_RAW if code == "not_raw" else REASON_MEASURE
    return FrameStats(f"/x/err_{code}{i}.fit", 0, 0.0, 0.0, 0.0, False,
                      reason_code=code, reason=reason, error=True)


def _session():
    """Six frames graded out of time order; f2 has a tenth of the stars, so
    judge() rejects it as cloud at every strictness."""
    stats = [_frame(0, 30), _frame(1, 10), _frame(2, 20, stars=80),
             _frame(3, 0), _frame(4, 40), _frame(5, 50)]
    judge(stats, "normal")
    assert [bool(s.reason) for s in stats] == [False, False, True, False, False, False]
    return stats


def _browser(qtbot, stats=None, loads=None):
    b = FrameBrowser(QThreadPool.globalInstance())
    qtbot.addWidget(b)
    b.preview_controller.loader = lambda p: ((loads.append(p) if loads is not None else None),
                                             np.zeros((8, 8, 3), np.float32))[1]
    if stats is not None:
        b.set_frames(stats)
    return b


def _key(widget, key, text=""):
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key,
                                             Qt.KeyboardModifier.NoModifier, text))


def _click_header(b, col):
    hdr = b.view.horizontalHeader()
    x = hdr.sectionViewportPosition(col) + hdr.sectionSize(col) // 2
    pos = QPointF(x, hdr.height() / 2)
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        QApplication.sendEvent(hdr.viewport(), QMouseEvent(
            kind, pos, hdr.viewport().mapToGlobal(pos), Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton if kind == QEvent.Type.MouseButtonPress
            else Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))


def _shown(qtbot, stats, width=1280, loads=None):
    b = _browser(qtbot, stats, loads)
    b.resize(width, 500)
    b.show()
    qtbot.waitExposed(b)
    return b


# --- Task 2: columns, sort, filter, select, preview -------------------------

def test_the_list_shows_time_not_the_file_name(qtbot):
    b = _browser(qtbot, _session())
    assert b.headers() == ["Use", "Time", "Stars", "FWHM", "Round", "Bg", "Verdict"]
    text = b.cell_text(3, fb.COL_TIME)
    assert text.endswith(":00") and "·" in text, text
    assert "f3.fit" not in text
    assert "f3.fit" in b.cell_tooltip(3, fb.COL_TIME), "the full name must be one hover away"


def test_the_list_opens_sorted_by_capture_time(qtbot):
    stats = _session() + [_frame(6)]          # no time at all: last
    b = _browser(qtbot, stats)
    assert b.view_rows() == [3, 1, 2, 0, 4, 5, 6]
    assert b.cell_text(6, fb.COL_TIME) == "—"
    assert "f6.fit" in b.cell_tooltip(6, fb.COL_TIME)
    b.set_checked(6, False)                    # a timeless frame is still tickable
    assert stats[6].included is False


def test_clicking_a_header_sorts_by_that_column(qtbot):
    stats = [_frame(i, i, fwhm=f) for i, f in enumerate([2.9, 2.4, 2.7, 2.5])]
    b = _browser(qtbot, stats)
    b.resize(900, 400); b.show(); qtbot.waitExposed(b)
    _click_header(b, fb.COL_FWHM)
    assert b.view_rows() == [1, 3, 2, 0], "not sorted by FWHM after a header click"


def test_show_kept_and_rejected_follow_the_verdict_not_the_tick(qtbot):
    """Filtering on the tick would make a frame you tick back in vanish from
    under the pointer mid-review."""
    stats = _session()
    b = _browser(qtbot, stats)
    labels = {m: btn.text() for m, btn in b._show_buttons.items()}
    assert labels == {"all": "All 6", "kept": "Kept 5", "rejected": "Rejected 1"}
    b.set_show(fb.SHOW_REJECTED)
    assert b.view_rows() == [2]
    b.set_checked(2, True)                     # overrule the grader
    assert b.view_rows() == [2], "ticking a rejected frame hid it"
    b.set_show(fb.SHOW_KEPT)
    assert 2 not in b.view_rows() and len(b.view_rows()) == 5


def test_select_all_and_none_touch_only_the_rows_shown(qtbot):
    stats = _session()
    b = _browser(qtbot, stats)
    b.set_show(fb.SHOW_KEPT)
    # Give the hidden frame a value None WOULD change if it (wrongly) reached
    # it — set directly, not via a tick, so it starts out untouched.
    stats[2].included = True
    hidden_before = stats[2].included
    b.select_none()
    assert [s.included for i, s in enumerate(stats) if i != 2] == [False] * 5
    assert stats[2].included == hidden_before, "a hidden frame was changed"
    assert 2 not in b.user_touched, "select_none touched a row it never showed"
    b.set_show(fb.SHOW_REJECTED)
    b.select_all()
    assert stats[2].included is True
    assert [s.included for i, s in enumerate(stats) if i != 2] == [False] * 5, \
        "Select All under Rejected reached the kept frames"


def test_back_to_the_verdicts_undoes_every_hand_tick(qtbot):
    stats = _session()
    b = _browser(qtbot, stats)
    verdicts = [s.included for s in stats]
    b.set_checked(2, True)
    b.set_checked(0, False)
    b.back_to_verdicts()
    assert [s.included for s in stats] == verdicts
    assert b.user_touched == set()


def test_a_hand_tick_survives_a_rejudge(qtbot):
    stats = _session()
    b = _browser(qtbot, stats)
    b.set_checked(2, True)
    judge(stats, "strict")                     # the host moved Strictness
    b.refresh_verdicts()
    assert stats[2].included is True and b.is_checked(2)
    assert 2 in b.user_touched


def test_a_tick_writes_the_hosts_own_frame(qtbot):
    """`included` on the host's objects is what the stack reads."""
    stats = _session()
    b = _browser(qtbot, stats)
    assert b.frames() is stats
    b.set_checked(4, False)
    assert stats[4].included is False
    assert b.checked_frames() == [s for s in stats if s.included]


def test_selection_changed_fires_for_ticks_not_for_moving(qtbot):
    stats = _session()
    b = _browser(qtbot, stats)
    fired = []
    b.selection_changed.connect(lambda: fired.append(1))
    b.set_current_row(4)
    assert fired == []
    b.set_checked(4, False)
    assert fired == [1]
    b.set_checked(4, False)                    # no change, no signal
    assert fired == [1]


def test_the_preview_follows_the_frame_and_names_it(qtbot):
    loads = []
    stats = _session()
    b = _browser(qtbot, stats, loads)
    b.set_current_row(4)
    qtbot.waitUntil(lambda: b.preview.has_image(), timeout=2000)
    assert loads == ["/x/f4.fit"]
    assert b.preview_name.text() == "f4.fit"
    assert "800 stars" in b.preview_facts.text() and "FWHM 2.5" in b.preview_facts.text()


def test_regrading_keeps_the_place_and_previews_the_new_frame(qtbot):
    loads = []
    b = _browser(qtbot, [_frame(i) for i in range(3)], loads)
    b.set_current_row(1)
    qtbot.waitUntil(lambda: loads == ["/x/f1.fit"], timeout=2000)
    other = [FrameStats(f"/y/g{i}.fit", 800, 2.5, 0.02, 0.5, True) for i in range(3)]
    b.set_frames(other)
    qtbot.waitUntil(lambda: len(loads) == 2, timeout=2000)
    assert loads[-1] == "/y/g1.fit", "the preview kept showing the old folder"


def test_the_preview_never_shows_a_frame_the_list_has_hidden(qtbot):
    """Filter the current frame away and Qt moves the cursor to a neighbour;
    the preview and its header must move with it, not stay on the hidden one."""
    loads = []
    stats = _session()
    b = _browser(qtbot, stats, loads)
    b.set_current_row(4)
    qtbot.waitUntil(lambda: b.preview.has_image(), timeout=2000)
    b.set_show(fb.SHOW_REJECTED)
    row = b.current_row()
    shown = stats[row].path if row >= 0 else ""
    assert b.preview_controller.wanted == shown
    assert b.preview_name.text() == (shown.rsplit("/", 1)[-1] if shown else "")
    assert "/x/f4.fit" != b.preview_controller.wanted


def test_a_filter_that_empties_the_list_clears_the_preview(qtbot):
    """No neighbour to move to: the preview must go blank, not keep the frame."""
    stats = [_frame(i, i) for i in range(4)]
    judge(stats, "normal")
    assert not any(s.reason for s in stats)
    b = _browser(qtbot, stats)
    b.set_current_row(1)
    qtbot.waitUntil(lambda: b.preview.has_image(), timeout=2000)
    b.set_show(fb.SHOW_REJECTED)
    assert b.row_count() == 0 and b.current_row() == -1
    assert not b.preview.has_image() and b.preview_controller.wanted == ""
    assert b.preview_name.text() == ""
    assert b.preview_name.toolTip() == "", "the old frame's path lingered in the tooltip"


def test_the_preview_takes_the_leftover_width(qtbot):
    b = _shown(qtbot, _session(), width=1280)
    lst, pv = b.splitter.sizes()
    assert pv > lst, f"list {lst} px, preview {pv} px at 1280"
    b.resize(1920, 500)
    qtbot.waitUntil(lambda: b.splitter.sizes()[1] > pv + 500, timeout=2000)
    assert b.splitter.sizes()[0] == lst, "widening the window grew the list"


def test_arrow_keys_step_through_frames_and_the_preview_follows(qtbot):
    loads = []
    b = _shown(qtbot, _session(), loads=loads)
    b.set_current_row(3)                       # first by time
    b.view.setFocus()
    _key(b.view, Qt.Key.Key_Down)
    assert b.current_row() == 1, "Down did not move to the next frame in time"
    qtbot.waitUntil(lambda: "/x/f1.fit" in loads, timeout=2000)
    _key(b.view, Qt.Key.Key_Up)
    assert b.current_row() == 3


# --- Fix round 1: R1 (select-none teeth), R2 (error rows), minors ----------

def test_error_frames_cannot_be_ticked_in(qtbot):
    """A stacked master or an unreadable sub must never reach the stack —
    stack_dialog's own path filter doesn't screen them out, so this table
    is the only gate."""
    stats = _session() + [_error_frame(0, "not_raw"), _error_frame(1, "measure_failed")]
    b = _browser(qtbot, stats)
    for row in (6, 7):
        flags = b.model.flags(b.model.index(row, fb.COL_USE))
        assert not (flags & Qt.ItemFlag.ItemIsUserCheckable), f"row {row} is checkable"
    b.select_all()
    assert stats[6].included is False and stats[7].included is False, \
        "Select All ticked an error frame in"
    b.set_checked(6, True)              # what a click/Space attempt does
    b.set_checked(7, True)
    assert stats[6].included is False and stats[7].included is False
    b.set_checked(2, True)              # a real tick elsewhere still works
    b.back_to_verdicts()
    assert stats[6].included is False and stats[7].included is False


def test_set_frames_to_empty_emits_current_changed(qtbot):
    b = _browser(qtbot, _session())
    b.set_current_row(0)
    seen = []
    b.current_changed.connect(seen.append)
    b.set_frames([])
    assert -1 in seen, "current_changed(-1) never fired for an empty list"


def test_timeless_frames_sort_last_in_descending_order_too(qtbot):
    stats = _session() + [_frame(6)]          # no time at all
    b = _browser(qtbot, stats)
    b.view.sortByColumn(fb.COL_TIME, Qt.SortOrder.DescendingOrder)
    rows = b.view_rows()
    assert rows[-1] == 6, f"the timeless frame moved to the front: {rows}"
    assert rows[:-1] == [5, 4, 0, 2, 1, 3], "dated frames are not latest-first"
