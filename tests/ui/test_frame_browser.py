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
    assert b.headers() == ["Use", "Time", "Stars", "FWHM", "Verdict"]
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


def test_reset_to_suggested_undoes_every_hand_tick(qtbot):
    stats = _session()
    b = _browser(qtbot, stats)
    assert b.reset_btn.text() == fb.RESET_TEXT == "Reset to suggested"
    verdicts = [s.included for s in stats]
    b.set_checked(2, True)
    b.set_checked(0, False)
    b.reset_to_suggested()
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
    qtbot.waitUntil(lambda: b.preview.has_image()
                    and b.preview_controller.wanted == "/x/f4.fit", timeout=2000)
    assert "/x/f4.fit" in loads
    assert b.preview_name.text() == "f4.fit"
    assert "800 stars" in b.preview_facts.text() and "FWHM 2.5" in b.preview_facts.text()


def test_a_regrade_previews_the_new_lists_first_kept_frame(qtbot):
    """Spec 2026-09-28 §2.6: never an empty preview after a grade — and never
    the previous folder's frame either."""
    loads = []
    b = _browser(qtbot, [_frame(i) for i in range(3)], loads)
    b.set_current_row(2)
    qtbot.waitUntil(lambda: "/x/f2.fit" in loads, timeout=2000)
    other = [FrameStats(f"/y/g{i}.fit", 800, 2.5, 0.02, 0.5, True) for i in range(3)]
    other[0].reason, other[0].included = "Soft stars (test)", False   # not KEPT
    b.set_frames(other)
    assert b.current_row() == 1
    assert b.preview_controller.wanted == "/y/g1.fit", "the preview kept the old folder"
    qtbot.waitUntil(lambda: "/y/g1.fit" in loads, timeout=2000)
    assert b.preview_name.text() == "g1.fit"


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
    b.reset_to_suggested()
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


# --- Task 3: the divider, bigger preview, Space, width ----------------------

@pytest.fixture
def styled():
    from nocturne.ui.theme import build_stylesheet
    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    yield
    app.setStyleSheet(before)


@pytest.mark.parametrize("use_style", [False, True])
def test_the_divider_is_wide_enough_to_hit(qtbot, request, use_style):
    """"Very hard to grab" (Andreas, 2026-09-27). Checked under the real
    stylesheet too: a QSplitter::handle rule would override handleWidth."""
    if use_style:
        request.getfixturevalue("styled")
    b = _shown(qtbot, _session())
    assert b.splitter.handle(1).width() >= 10


def test_the_divider_is_drawn_not_just_wide(qtbot):
    b = _shown(qtbot, _session())
    img = b.splitter.handle(1).grab().toImage()
    faint = QColor(fb.theme.TEXT_FAINT).rgb()
    dots = sum(1 for x in range(img.width()) for y in range(img.height())
               if img.pixel(x, y) == faint)
    assert dots >= 20, "the grip is invisible"


def test_the_list_is_only_as_wide_as_its_columns(qtbot):
    b = _shown(qtbot, _session(), width=1920)
    assert b.splitter.sizes()[0] == b.list_natural_width()


def test_bigger_preview_narrows_the_list_to_time_and_verdict(qtbot):
    b = _shown(qtbot, _session())
    before = b.splitter.sizes()
    qtbot.mouseClick(b.bigger_btn, Qt.MouseButton.LeftButton)
    hidden = {c for c in range(len(fb.HEADERS)) if b.view.isColumnHidden(c)}
    assert hidden == set(fb.DETAIL_COLUMNS)
    assert {fb.COL_USE, fb.COL_TIME, fb.COL_VERDICT}.isdisjoint(hidden)
    assert b.splitter.sizes()[0] < before[0] and b.splitter.sizes()[1] > before[1]
    qtbot.mouseClick(b.bigger_btn, Qt.MouseButton.LeftButton)
    assert not any(b.view.isColumnHidden(c) for c in range(len(fb.HEADERS)))
    assert b.splitter.sizes() == before, "the second click did not restore the list"


@pytest.mark.parametrize("col", [fb.COL_USE, fb.COL_TIME, fb.COL_VERDICT])
def test_space_ticks_the_current_frame_once_from_any_column(qtbot, col):
    """Qt's own Space only toggles on the checkbox cell; from Time or Verdict
    it did nothing. On the checkbox cell it must not toggle twice."""
    stats = _session()
    b = _shown(qtbot, stats)
    b.set_current_row(4)
    b.view.setCurrentIndex(b.proxy.index(b.view.currentIndex().row(), col))
    b.view.setFocus()
    _key(b.view, Qt.Key.Key_Space, " ")
    assert stats[4].included is False and 4 in b.user_touched
    _key(b.view, Qt.Key.Key_Space, " ")
    assert stats[4].included is True


def test_space_does_not_tick_an_error_frame(qtbot):
    """Space reaches ticking through the same set_checked() path a click
    does, so it must be turned away by the same rule: an error frame (a
    stacked master or an unreadable sub) is never a candidate to tick in."""
    stats = _session() + [_error_frame(0, "not_raw")]
    b = _shown(qtbot, stats)
    b.set_current_row(6)
    b.view.setFocus()
    _key(b.view, Qt.Key.Key_Space, " ")
    assert stats[6].included is False, "Space ticked an error frame in"


# --- frames moved into rejected/ (delivery B, spec decision 7) ----------------

from PySide6.QtWidgets import QLabel  # noqa: E402

from nocturne.ui import theme  # noqa: E402
from nocturne.ui.frame_browser import MOVED_TEXT  # noqa: E402


def _moved(stats, row):
    s = stats[row]
    s.path = f"/x/rejected/{s.path.rsplit('/', 1)[1]}"
    s.moved = True
    s.included = False
    return s


def test_a_frame_is_not_moved_until_the_host_says_so():
    assert _frame(0).moved is False


def test_a_moved_frame_reads_in_rejected_and_is_dimmed(qtbot):
    stats = _session()
    b = _browser(qtbot, stats)
    _moved(stats, 2)
    b.frames_moved()
    assert b.cell_text(2, fb.COL_VERDICT) == MOVED_TEXT
    assert "rejected folder" in b.cell_tooltip(2, fb.COL_VERDICT)
    assert b.cell_colour(2, fb.COL_TIME) == QColor(theme.TEXT_FAINT).name()
    flags = b.model.flags(b.model.index(2, fb.COL_USE))
    assert not flags & Qt.ItemFlag.ItemIsUserCheckable


def test_no_route_ticks_a_moved_frame_back_in(qtbot):
    """Review Focus 5: box, Space, Select All, Reset to suggested."""
    stats = _session()
    stats[0].included = False                 # he unticked a KEPT frame…
    b = _shown(qtbot, stats)
    _moved(stats, 0)                          # …and moved it
    b.frames_moved()
    b.set_checked(0, True)
    assert not b.is_checked(0)
    b.set_current_row(0)
    _key(b.view, Qt.Key.Key_Space, " ")
    assert not b.is_checked(0)
    b.select_all()
    assert not b.is_checked(0)
    b.reset_to_suggested()                    # its grader verdict is OK — still not in
    assert not b.is_checked(0)
    assert stats[0] not in b.checked_frames()


def test_a_strictness_change_does_not_tick_a_moved_frame(qtbot):
    """A frame the GRADER kept (f0), unticked and moved: judge() puts
    included=True back on every usable frame, and only the lock takes it out
    again. (f2 would not do — it is cloud at every strictness, so judge
    itself would leave it out and the test would pass without the lock.)"""
    stats = _session()
    stats[0].included = False
    b = _browser(qtbot, stats)
    _moved(stats, 0)
    b.frames_moved()
    judge(stats, "relaxed")
    assert stats[0].included is True, "fixture: judge no longer re-includes it"
    b.refresh_verdicts()
    assert not b.is_checked(0)
    assert stats[0] not in b.checked_frames()


def test_checked_frames_never_returns_a_moved_one_even_if_included_is_forced(qtbot):
    stats = _session()
    b = _browser(qtbot, stats)
    _moved(stats, 1)
    stats[1].included = True                  # a caller bypassing the model
    assert stats[1] not in b.checked_frames()


def test_a_moved_frame_shows_under_rejected_and_is_counted_there(qtbot):
    stats = _session()
    stats[0].included = False
    b = _shown(qtbot, stats)
    _moved(stats, 0)                          # grader said OK; moved all the same
    b.frames_moved()
    b.set_show(fb.SHOW_REJECTED)
    assert sorted(b.view_rows()) == [0, 2]
    b.set_show(fb.SHOW_KEPT)
    assert 0 not in b.view_rows()
    assert b._show_buttons[fb.SHOW_REJECTED].text() == "Rejected 2"
    assert b.chart.point_colour(0) != b.chart.point_colour(1)


def test_the_preview_follows_a_moved_frame_to_its_new_path(qtbot):
    stats = _session()
    loads = []
    b = _shown(qtbot, stats, loads=loads)
    b.set_current_row(2)
    qtbot.waitUntil(lambda: bool(loads) and loads[-1] == "/x/f2.fit", timeout=2000)
    _moved(stats, 2)
    b.frames_moved()
    qtbot.waitUntil(lambda: loads[-1] == "/x/rejected/f2.fit", timeout=2000)
    assert b.preview_name.text() == "f2.fit"
    assert b.preview_name.toolTip() == "/x/rejected/f2.fit"


def test_moved_back_it_can_be_ticked_again(qtbot):
    stats = _session()
    b = _browser(qtbot, stats)
    _moved(stats, 2)
    b.frames_moved()
    stats[2].path, stats[2].moved = "/x/f2.fit", False
    b.frames_moved()
    assert b.cell_text(2, fb.COL_VERDICT) != MOVED_TEXT
    b.set_checked(2, True)
    assert b.is_checked(2)


def test_a_host_can_put_its_own_strip_above_the_list(qtbot):
    b = _shown(qtbot, _session())
    strip = QLabel("verdict")
    b.add_above_list(strip)
    assert b.list_layout.indexOf(strip) == 0
    qtbot.waitUntil(lambda: strip.mapTo(b, strip.rect().topLeft()).y()
                    < b.view.mapTo(b, b.view.rect().topLeft()).y(), timeout=2000)


# --- a calmer list (spec 2026-09-28 §2.6) -------------------------------------

def test_round_and_bg_moved_into_every_cells_tooltip(qtbot):
    stats = _session()
    stats[4].elongation, stats[4].background = 1.37, 0.0215
    b = _browser(qtbot, stats)
    want = "Stars 800 · FWHM 2.50 px · Round 1.37 · Bg 0.021"
    for col in (fb.COL_TIME, fb.COL_STARS, fb.COL_FWHM, fb.COL_VERDICT):
        assert want in b.cell_tooltip(4, col), (col, b.cell_tooltip(4, col))
    assert "f4.fit" in b.cell_tooltip(4, fb.COL_TIME)
    assert b.cell_tooltip(4, fb.COL_VERDICT).startswith("OK\n")
    assert b.cell_tooltip(4, fb.COL_USE) == ""


def test_a_grade_previews_the_first_kept_frame_in_time_order(qtbot):
    """_session's first frame by time is f3 (minute 0); make it a reject, and
    the first KEPT one is f1 (minute 10)."""
    stats = _session()
    stats[3].fwhm = 9.0
    judge(stats, "normal")
    assert stats[3].reason and not stats[1].reason, "fixture: f3 must be the reject"
    loads = []
    b = _browser(qtbot, stats, loads)
    assert b.view_rows()[0] == 3
    assert b.current_row() == 1
    qtbot.waitUntil(lambda: b.preview.has_image(), timeout=2000)
    assert b.preview_controller.wanted == "/x/f1.fit"
    assert b.chart.current_row() == 1


def test_every_frame_rejected_previews_the_first_one(qtbot):
    """Review Focus 4: nothing kept — show the first frame, which is the next
    thing he will want to look at, and keep the counts and the chart honest."""
    stats = [_frame(i, i) for i in range(3)]
    for s in stats:
        s.reason, s.included = "Soft stars (test)", False
    b = _browser(qtbot, stats, [])
    assert b.current_row() == b.view_rows()[0] == 0
    labels = {m: btn.text() for m, btn in b._show_buttons.items()}
    assert labels == {"all": "All 3", "kept": "Kept 0", "rejected": "Rejected 3"}
    from nocturne.ui.quality_chart import REJECTED_COLOUR
    assert all(b.chart.point_colour(i) == REJECTED_COLOUR for i in range(3))


def test_an_empty_or_error_only_list_previews_nothing(qtbot):
    b = _browser(qtbot, [_error_frame(0, "not_raw"), _error_frame(1, "measure_failed")], [])
    assert b.current_row() == -1 and b.preview_controller.wanted == ""
    b.set_frames([])
    assert b.current_row() == -1


# --- fix round 1: R3 (a re-grade must not preview through a stale filter) ----

def test_a_regrade_resets_show_to_all_before_choosing_the_preview(qtbot):
    """Ruling R3: _first_to_preview reads through the CURRENT filter, so a
    re-grade taken while Show=Rejected previewed the first REJECTED frame
    instead of the first kept one. A fresh grade must reset Show to All
    first."""
    stats = _session()
    b = _browser(qtbot, stats)
    b.set_show(fb.SHOW_REJECTED)
    other = [_frame(i, i) for i in range(3)]
    other[0].reason, other[0].included = "Soft stars (test)", False   # not KEPT
    b.set_frames(other)
    assert b.proxy.show_mode() == fb.SHOW_ALL
    assert b._show_buttons[fb.SHOW_ALL].isChecked()
    assert b.current_row() == 1
    assert b.preview_controller.wanted == "/x/f1.fit"


def test_a_rejudge_does_not_move_show_or_the_cursor(qtbot):
    """Strictness moving is a rejudge, not a fresh grade — refresh_verdicts
    must leave Show and the current row exactly where the user left them."""
    stats = _session()
    b = _browser(qtbot, stats)
    b.set_show(fb.SHOW_KEPT)
    b.set_current_row(4)
    show_before, row_before = b.proxy.show_mode(), b.current_row()
    judge(stats, "strict")
    b.refresh_verdicts()
    assert b.proxy.show_mode() == show_before
    assert b.current_row() == row_before
