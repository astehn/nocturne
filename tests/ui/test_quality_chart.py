"""FWHM over the session, under the frame list (spec 2026-09-27 decision 4.6,
list-preview mockup). Shared by Stack and Ha/OIII through FrameBrowser.

Mouse and tooltip events are built and sent directly (never qtbot.mouseMove).
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt, QThreadPool
from PySide6.QtGui import QColor, QHelpEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QToolTip

from nocturne.settings import Settings
from nocturne.stacking.capture_time import full_label
from nocturne.stacking.grade import REASON_MEASURE, FrameStats, judge
from nocturne.ui import theme
from nocturne.ui.frame_browser import SHOW_ALL, SHOW_KEPT, FrameBrowser, verdict_text
from nocturne.ui.haoiii_dialog import HaOIIIDialog
from nocturne.ui.quality_chart import (CHART_HEIGHT, KEPT_COLOUR, NOTE_NO_TIME,
                                       NOTE_TIME, REJECTED_COLOUR, RING_RADIUS,
                                       QualityChart)
from nocturne.ui.stack_dialog import StackDialog

T0 = datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc)


def _frame(i, minute, fwhm=2.5, stars=800):
    s = FrameStats(f"/x/f{i}.fit", stars, fwhm, 0.02, 0.5, True, exposure=10.0)
    s.captured = None if minute is None else T0 + timedelta(minutes=minute)
    return s


def _night():
    """Six frames graded out of time order. f2 (3.0 against 2.5) is soft at
    Normal (limit 2.875) and kept at Relaxed (limit 3.125)."""
    stats = [_frame(0, 30), _frame(1, 10), _frame(2, 20, fwhm=3.0),
             _frame(3, 0), _frame(4, 40), _frame(5, 50)]
    judge(stats, "normal")
    assert [bool(s.reason) for s in stats] == [False, False, True, False, False, False]
    return stats


def _shown(qtbot, stats, width=1280, height=500):
    b = FrameBrowser(QThreadPool.globalInstance())
    qtbot.addWidget(b)
    b.preview_controller.loader = lambda p: np.zeros((8, 8, 3), np.float32)
    b.set_frames(stats)
    b.resize(width, height)
    b.show()
    qtbot.waitExposed(b)
    return b


def _press(widget, pos):
    QApplication.sendEvent(widget, QMouseEvent(
        QEvent.Type.MouseButtonPress, pos, widget.mapToGlobal(pos),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))


def _pixel(widget, pos) -> QColor:
    img = widget.grab().toImage()
    return QColor(img.pixel(int(pos.x()), int(pos.y())))


def _close(a: QColor, hex_colour: str, tol=40) -> bool:
    b = QColor(hex_colour)
    return all(abs(x - y) <= tol for x, y in
               ((a.red(), b.red()), (a.green(), b.green()), (a.blue(), b.blue())))


# --- where it lives -----------------------------------------------------------

def test_the_chart_sits_under_the_list(qtbot):
    b = _shown(qtbot, _night())
    lay = b.list_layout
    assert lay.indexOf(b.chart) > lay.indexOf(b.view)
    assert b.chart.height() == CHART_HEIGHT
    view_bottom = b.view.mapTo(b, b.view.rect().bottomLeft()).y()
    assert b.chart.mapTo(b, b.chart.rect().topLeft()).y() > view_bottom


@pytest.mark.parametrize("cls", [StackDialog, HaOIIIDialog])
def test_both_dialogs_carry_the_same_chart(qtbot, cls):
    d = cls(Settings())
    qtbot.addWidget(d)
    assert isinstance(d.browser.chart, QualityChart)
    d._on_graded(_night())
    assert not d.browser.chart.isHidden()


def test_the_list_gives_up_height_the_chart_keeps_its_own(qtbot):
    b = _shown(qtbot, _night(), height=260)
    assert b.chart.height() == CHART_HEIGHT and not b.chart.isHidden()
    assert b.view.height() > 0


# --- what it plots ------------------------------------------------------------

def test_points_run_left_to_right_by_capture_time(qtbot):
    b = _shown(qtbot, _night())
    plotted = b.chart.plotted()
    assert [row for row, _x in plotted] == [3, 1, 2, 0, 4, 5]
    xs = [x for _row, x in plotted]
    assert xs == sorted(xs) and xs[0] == 0.0 and xs[-1] == 1.0
    assert b.chart.is_timed() and b.chart.note() == NOTE_TIME


def test_a_softer_frame_sits_higher(qtbot):
    b = _shown(qtbot, _night())
    assert b.chart.point_pos(2).y() < b.chart.point_pos(0).y()


def test_error_and_starless_frames_are_not_plotted(qtbot):
    stats = _night()
    err = FrameStats("/x/bad.fit", 0, 0.0, 0.0, 0.0, False, reason_code="measure_failed",
                     reason=REASON_MEASURE, error=True)
    err.captured = T0
    blank = _frame(9, 25, stars=0)
    blank.fwhm = 0.0
    b = _shown(qtbot, stats + [err, blank])
    rows = [row for row, _x in b.chart.plotted()]
    assert 6 not in rows and 7 not in rows and len(rows) == 6


@pytest.mark.parametrize("n, hidden", [(0, True), (1, True), (2, False)])
def test_fewer_than_two_points_hides_the_chart(qtbot, n, hidden):
    b = _shown(qtbot, [_frame(i, i) for i in range(n)])
    assert b.chart.isHidden() is hidden


def test_no_capture_time_falls_back_to_file_name_order_with_a_note(qtbot):
    """Review Focus 3. NOT the list's own order: the host's list is the
    grader's, worst to best, which would draw a false trend."""
    stats = _night()
    stats[3].captured = None
    b = _shown(qtbot, stats)
    assert not b.chart.is_timed() and b.chart.note() == NOTE_NO_TIME
    assert [row for row, _x in b.chart.plotted()] == [0, 1, 2, 3, 4, 5]
    assert not b.chart.isHidden()


def test_a_gap_between_nights_is_drawn_short(qtbot):
    """His Sh2-108 folder: nights on the 21st, 26th and 27th. On a true time
    axis each night would be a sliver; any gap is drawn as at most 20 min."""
    later = 5 * 24 * 60
    stats = [_frame(0, 0), _frame(1, 5), _frame(2, 10),
             _frame(3, later), _frame(4, later + 5), _frame(5, later + 10)]
    b = _shown(qtbot, stats)
    xs = [x for _row, x in b.chart.plotted()]
    # steps 5, 5, 20 (capped), 5, 5 minutes: 40 in all
    assert xs == pytest.approx([0.0, 0.125, 0.25, 0.75, 0.875, 1.0])


# --- how it looks -----------------------------------------------------------------

def test_rejected_points_are_amber_and_kept_ones_blue(qtbot):
    b = _shown(qtbot, _night())
    assert REJECTED_COLOUR == theme.WARNING and KEPT_COLOUR == theme.ACCENT
    assert b.chart.point_colour(2) == REJECTED_COLOUR
    assert b.chart.point_colour(0) == KEPT_COLOUR
    assert _close(_pixel(b.chart, b.chart.point_pos(2)), theme.WARNING)
    assert _close(_pixel(b.chart, b.chart.point_pos(0)), theme.ACCENT)


def test_the_current_frame_is_ringed(qtbot):
    b = _shown(qtbot, _night())
    p = b.chart.point_pos(4)
    # Straight ABOVE the dot: f4's neighbours share its FWHM, so the line runs
    # horizontally through it — a pixel to the side would be lit by the line
    # with or without a ring.
    top = QPointF(p.x(), p.y() - RING_RADIUS)
    b.chart.set_current(-1)
    assert _pixel(b.chart, top).lightness() < QColor(theme.BG_2).lightness() + 30
    b.set_current_row(4)
    assert b.chart.current_row() == 4
    assert _pixel(b.chart, top).lightness() > QColor(theme.BG_2).lightness() + 80


def test_a_rejudge_recolours_the_points(qtbot):
    stats = _night()
    b = _shown(qtbot, stats)
    judge(stats, "relaxed")
    b.refresh_verdicts()
    assert b.chart.point_colour(2) == KEPT_COLOUR


# --- what it does -------------------------------------------------------------------

def test_clicking_a_point_selects_that_frame(qtbot):
    b = _shown(qtbot, _night())
    _press(b.chart, b.chart.point_pos(5))
    assert b.current_row() == 5


def test_clicking_a_point_the_filter_hides_switches_show_to_all(qtbot):
    b = _shown(qtbot, _night())
    b.set_show(SHOW_KEPT)
    assert 2 not in b.view_rows()
    _press(b.chart, b.chart.point_pos(2))
    assert b.proxy.show_mode() == SHOW_ALL
    assert b._show_buttons[SHOW_ALL].isChecked()
    assert b.current_row() == 2


def test_clicking_between_points_changes_nothing(qtbot):
    b = _shown(qtbot, _night())
    b.set_current_row(1)
    _press(b.chart, QPointF(b.chart.width() - 2, 2))
    assert b.current_row() == 1


def test_hovering_names_the_time_the_fwhm_and_the_verdict(qtbot):
    stats = _night()
    b = _shown(qtbot, stats)
    p = b.chart.point_pos(2)
    want = f"{full_label(stats[2].captured)}\nFWHM 3.00 px · {verdict_text(stats[2])}"
    assert b.chart.tooltip_at(p) == want
    QApplication.sendEvent(b.chart, QHelpEvent(QEvent.Type.ToolTip, p.toPoint(),
                                               b.chart.mapToGlobal(p.toPoint())))
    assert QToolTip.text() == want
    assert b.chart.tooltip_at(QPointF(b.chart.width() - 2, 2)) == ""
