"""FWHM over the session, under the frame list (spec 2026-09-27 decision 4.6,
list-preview mockup). Shared by Stack and Ha/OIII through FrameBrowser.

Mouse and tooltip events are built and sent directly (never qtbot.mouseMove).
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QThreadPool
from PySide6.QtGui import QColor, QHelpEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QToolTip

from nocturne.settings import Settings
from nocturne.stacking.capture_time import full_label
from nocturne.stacking.grade import REASON_MEASURE, FrameStats, judge
from nocturne.ui import theme
from nocturne.ui.frame_browser import (COL_FWHM, SHOW_ALL, SHOW_KEPT,
                                       FrameBrowser, verdict_text)
from nocturne.ui.haoiii_dialog import HaOIIIDialog
from nocturne.ui import quality_chart as qc
from nocturne.ui.quality_chart import (CHART_HEIGHT, CHART_ROOM_MIN, HIDE_TEXT,
                                       KEPT_COLOUR, NOTE_NO_TIME, NOTE_TIME,
                                       REJECTED_COLOUR, RING_RADIUS, SHOW_TEXT,
                                       ChartPanel, QualityChart)
from nocturne.ui.stack_dialog import StackDialog
from nocturne.ui.theme import build_stylesheet

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

def test_the_chart_spans_the_browser_above_the_show_bar(qtbot):
    """Spec 2026-09-28 §2.4: out of the list's column, across the full width,
    above Show/Select — about 70 px of plot under its caption line."""
    b = _shown(qtbot, _night())
    assert isinstance(b.chart_panel, ChartPanel) and b.chart_panel.chart is b.chart
    assert b.layout().indexOf(b.chart_panel) == 0
    assert not b.splitter.isAncestorOf(b.chart)
    assert CHART_HEIGHT == 70 and b.chart.height() == CHART_HEIGHT
    assert b.chart.width() >= b.width() - 1
    view_top = b.view.mapTo(b, b.view.rect().topLeft()).y()
    assert b.chart.mapTo(b, b.chart.rect().bottomLeft()).y() < view_top


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


def test_the_caption_bullet_is_amber_not_grey(qtbot):
    """Fix round 1 (Ruling R5): the note reads "...— ● rejected" — the ●
    must be REJECTED_COLOUR, not the caption's own TEXT_DIM grey, or the
    legend describes the wrong colour for the dots the chart actually
    paints. The caption is ChartPanel's label now (spec 2026-09-28 §2.4);
    rendered under the real stylesheet, as the app would show it."""
    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        b = _shown(qtbot, _night())
        cap = b.chart_panel.caption
        assert cap.text() == qc.note_html(NOTE_TIME)
        assert f'color:{REJECTED_COLOUR}">●</span>' in cap.text()
        img = cap.grab().toImage()
        found = any(_close(QColor(img.pixel(x, y)), theme.WARNING, tol=60)
                    for y in range(img.height()) for x in range(img.width()))
        assert found
    finally:
        app.setStyleSheet(before)


def test_folding_the_chart_drops_the_dangling_rejected_legend(qtbot):
    """M7 (final fix wave, 2026-09-28): folded, the dots are not drawn at
    all — "— ● rejected" then describes nothing on screen. Unfolding must
    bring it straight back."""
    b = _shown(qtbot, _night())
    panel = b.chart_panel
    assert "●" in panel.caption.text() and "rejected" in panel.caption.text()
    panel.fold_btn.click()
    assert panel.is_folded()
    assert "●" not in panel.caption.text() and "rejected" not in panel.caption.text()
    assert "FWHM" in panel.caption.text(), "folded away the whole caption, not just the legend"
    panel.fold_btn.click()
    assert not panel.is_folded()
    assert "●" in panel.caption.text() and "rejected" in panel.caption.text()


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


def test_a_click_after_sort_and_filter_still_finds_the_source_row(qtbot):
    """A chart click carries a SOURCE row (spec 2026-09-28 §2.4): sorting the
    list by FWHM descending, on top of filtering to Kept, must not throw it
    off. f2 (source row 2) is _night()'s one rejected frame — hidden under
    Kept — so the click must also bring Show back to All to land on it, and
    the preview must follow to that same frame."""
    stats = _night()
    b = _shown(qtbot, stats)
    b.view.sortByColumn(COL_FWHM, Qt.SortOrder.DescendingOrder)
    b.set_show(SHOW_KEPT)
    assert 2 not in b.view_rows()
    _press(b.chart, b.chart.point_pos(2))
    assert b.proxy.show_mode() == SHOW_ALL
    assert b._show_buttons[SHOW_ALL].isChecked()
    assert b.current_row() == 2
    assert b.preview_controller.wanted == stats[2].path


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


# --- the fold, the axes, and a big night (spec 2026-09-28 §2.4, §8) ---------

def test_the_fold_hides_the_plot_and_keeps_the_caption_line(qtbot):
    b = _shown(qtbot, _night())
    panel = b.chart_panel
    assert panel.fold_btn.text() == HIDE_TEXT == "▾ Hide chart"
    seen = []
    panel.folded_changed.connect(seen.append)
    panel.fold_btn.click()
    assert panel.is_folded() and panel.user_set() and seen == [True]
    assert not b.chart.isVisible() and panel.caption.isVisible()
    assert panel.fold_btn.text() == SHOW_TEXT == "▸ Show chart"
    panel.fold_btn.click()
    assert not panel.is_folded() and b.chart.isVisible() and seen == [True, False]


def test_the_dialogs_own_fold_is_not_his(qtbot):
    b = _shown(qtbot, _night())
    seen = []
    b.chart_panel.folded_changed.connect(seen.append)
    b.chart_panel.set_folded(True)
    assert b.chart_panel.is_folded() and not b.chart_panel.user_set() and seen == []


def test_a_folded_chart_with_no_points_stays_hidden(qtbot):
    b = _shown(qtbot, [_frame(0, 0)])
    b.chart_panel.set_folded(True)
    assert b.chart_panel.isHidden() and b.chart.isHidden()


@pytest.mark.parametrize("cls", [StackDialog, HaOIIIDialog])
def test_his_fold_is_saved_and_the_next_dialog_opens_folded(qtbot, cls):
    settings = Settings()
    saves = []
    d = cls(settings, on_settings_changed=lambda: saves.append(settings.quality_chart_folded))
    qtbot.addWidget(d)
    d._available_height = lambda: 4000
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(_night())
    d.browser.chart_panel.fold_btn.click()
    assert settings.quality_chart_folded is True and saves[-1] is True
    other = (HaOIIIDialog if cls is StackDialog else StackDialog)(settings)
    qtbot.addWidget(other)
    assert other.browser.chart_panel.is_folded(), "the other dialog forgot the fold"


def test_the_chart_fold_reaches_the_apps_settings_file(qtbot, tmp_path):
    from nocturne.settings import load_settings
    from tests.ui.test_main_window import _window
    win = _window(qtbot, tmp_path)
    d = StackDialog(win.settings, win, on_settings_changed=win._save_settings)
    qtbot.addWidget(d)
    d._on_graded(_night())
    d.browser.chart_panel.fold_btn.click()
    assert load_settings(win._settings_path).quality_chart_folded is True


@pytest.mark.parametrize("cls", [StackDialog, HaOIIIDialog])
def test_the_chart_starts_folded_at_740_and_open_on_a_tall_screen(qtbot, cls):
    """Spec §8: folded at 740 px of available height — for that window only,
    the saved choice untouched."""
    assert CHART_ROOM_MIN > 740
    for room, folded in ((740, True), (4000, False)):
        settings = Settings()
        d = cls(settings)
        qtbot.addWidget(d)
        d._available_height = lambda r=room: r
        d.resize(1280, 700)
        d.show()
        qtbot.waitExposed(d)
        d._on_graded(_night())
        qtbot.wait(20)
        assert d.browser.chart_panel.is_folded() is folded, (cls.__name__, room)
        assert d.browser.chart_panel.isVisible()
        assert settings.quality_chart_folded is False, "the screen rewrote the preference"


def test_show_chart_at_740_stays_open_and_on_screen(qtbot):
    d = StackDialog(Settings())
    qtbot.addWidget(d)
    d._available_height = lambda: 740
    d.resize(1280, 700)
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(_night())
    panel = d.browser.chart_panel
    assert panel.is_folded()
    panel.fold_btn.click()
    qtbot.wait(50)
    d._keep_on_screen()
    assert not panel.is_folded(), "folded again behind his back"
    assert d.height() <= 740


def test_on_a_short_screen_the_chart_folds_before_the_verdict(qtbot, monkeypatch):
    """The fold order (spec §2.4): help → options → chart → verdict details.
    CHART_ROOM_MIN off, so only the chain decides."""
    from nocturne.ui import stack_dialog
    monkeypatch.setattr(stack_dialog, "CHART_ROOM_MIN", 0)

    def need(fold_chart):
        d = StackDialog(Settings())
        qtbot.addWidget(d)
        d._available_height = lambda: 4000
        d.resize(1280, 700)
        d.show()
        qtbot.waitExposed(d)
        d._on_graded(_night())
        d.browser.chart_panel.set_folded(fold_chart)
        n = d._settled_minimum_height()
        d.close()
        return n

    open_need, folded_need = need(False), need(True)
    assert open_need > folded_need + 40, "the chart costs no height?"
    for room, chart, compact in ((open_need - 1, True, False),
                                 (folded_need - 1, True, True)):
        d = StackDialog(Settings())
        qtbot.addWidget(d)
        d._available_height = lambda r=room: r
        d.resize(1280, 700)
        d.show()
        qtbot.waitExposed(d)
        d._on_graded(_night())
        qtbot.wait(20)
        assert d.browser.chart_panel.is_folded() is chart, room
        assert d.verdict_strip.is_compact() is compact, room


def _clock(s):
    return f"{s.captured.astimezone():%H:%M}"


def test_the_axes_name_clock_times_and_two_fwhm_values(qtbot):
    stats = _night()
    b = _shown(qtbot, stats)
    times = b.chart.time_labels()
    assert len(times) >= 2
    first_by_time = min(stats, key=lambda s: s.captured)
    last_by_time = max(stats, key=lambda s: s.captured)
    assert times[0][1] == _clock(first_by_time) and times[-1][1] == _clock(last_by_time)
    assert [t for _r, t in b.chart.fwhm_labels()] == ["3.0", "2.5"]


def test_axis_labels_meet_the_apps_readability_floor(qtbot):
    """Fix round 1 (Ruling R5): TEXT_FAINT at 9 px measured a 2.44:1 contrast
    on BG_2 — dimmer and smaller than any other secondary text in the app.
    Pinned to TEXT_DIM at >= 11 px, the app's own floor for secondary text
    (QLabel#optionGroupTitle and friends, theme.py), so a quiet regression
    back to the old values cannot pass unnoticed."""
    assert qc.AXIS_COLOUR == theme.TEXT_DIM
    assert qc._AXIS_PX >= 11
    b = _shown(qtbot, _night())
    assert b.chart._axis_font().pixelSize() == qc._AXIS_PX
    img = b.chart.grab().toImage()
    rect, _text = b.chart.fwhm_labels()[0]
    found = any(_close(QColor(img.pixel(x, y)), theme.TEXT_DIM, tol=40)
                for y in range(max(0, int(rect.top())), int(rect.bottom()) + 1)
                for x in range(max(0, int(rect.left())), int(rect.right()) + 1))
    assert found, "no pixel in the FWHM label's own rect painted TEXT_DIM"


def test_without_capture_times_there_is_no_time_axis(qtbot):
    stats = _night()
    stats[3].captured = None
    b = _shown(qtbot, stats)
    assert b.chart.time_labels() == []
    assert len(b.chart.fwhm_labels()) == 2


def _big_night(n=2500):
    """His IC 1396A session is 2,535 frames; ten seconds apart, a soft one in
    seven, so a quarter of the points are amber."""
    stats = []
    for i in range(n):
        s = FrameStats(f"/x/L_{i:05d}.fit", 800, 2.4 + 0.3 * (i % 7 == 0) + 0.001 * (i % 13),
                       0.02, 0.5, True, exposure=10.0)
        s.captured = T0 + timedelta(seconds=10 * i)
        stats.append(s)
    judge(stats, "normal")
    return stats


@pytest.mark.parametrize("n", [3, 2500])
@pytest.mark.parametrize("width", [800, 1280, 1920])
def test_labels_never_collide_or_leave_the_chart(qtbot, width, n):
    """2,500 frames (his biggest session), and 3 — where six evenly spaced
    targets snap onto the same few frames and would stack on each other."""
    b = _shown(qtbot, _big_night(n), width=width)
    labels = b.chart.time_labels() + b.chart.fwhm_labels()
    rects = [r for r, _t in labels]
    assert len(b.chart.time_labels()) >= 2
    for i, r in enumerate(rects):
        assert r.left() >= 0 and r.right() <= b.chart.width(), (width, r)
        assert r.top() >= 0 and r.bottom() <= b.chart.height(), (width, r)
        for other in rects[i + 1:]:
            assert not r.intersects(other), (width, r, other)


def test_the_current_frame_ring_does_not_cover_its_own_fwhm_label(qtbot):
    """M1: the first kept frame sits at the plot's own left edge, and Task
    2's auto-preview rings the current frame after every grade -- so if that
    first frame is also the softest or sharpest (drawing a label), the ring
    drawn on top of it must not strike through the label."""
    stats = [_frame(0, 0, fwhm=3.5), _frame(1, 10), _frame(2, 20), _frame(3, 30)]
    b = _shown(qtbot, stats)
    b.set_current_row(0)
    chart = b.chart
    pos = chart.point_pos(0)
    assert pos is not None
    assert pos.x() == pytest.approx(chart._plot_rect().left()), "fixture drifted off the left edge"
    ring = QRectF(pos.x() - RING_RADIUS, pos.y() - RING_RADIUS,
                 2 * RING_RADIUS, 2 * RING_RADIUS)
    labels = chart.fwhm_labels()
    assert labels, "fixture lost its FWHM label"
    for rect, text in labels:
        assert not rect.intersects(ring), (rect, text, ring)


def test_2500_frames_paint_quickly(qtbot):
    """Paint cost at his biggest session: the whole strip, every dot, well
    under a frame's worth of interaction."""
    import time
    b = _shown(qtbot, _big_night(), width=1920)
    b.chart.grab()                              # warm up fonts and caches
    t0 = time.perf_counter()
    for _ in range(5):
        b.chart.grab()
    per_paint = (time.perf_counter() - t0) / 5
    # Measured 6 ms offscreen (2026-09-28, M-series); eight times that is
    # still a fraction of a frame at the pointer's pace.
    assert per_paint < 0.05, f"{per_paint * 1000:.0f} ms a paint"
