"""The right column's busy indicator is the finishing tools' ring, small.

Andreas, 2026-10-04: SPCC took well over 0.4 s and showed no bar — the old
QProgressBar was simply HIDDEN whenever no percentage came, and with the bar
over the image removed the same day, plate solving, saving, export and SPCC
had nothing on screen that moved. One signal across the app now: the ring
spins with no number, and fills when a real percentage exists.
"""
import pytest

from tests.ui.test_main_window import _make_fits, _window


def _busy(qtbot, tmp_path, label="Calibrating colour…"):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.show(); qtbot.waitExposed(win)
    win._set_busy(True, label)
    win._show_busy_visuals()
    return win


def test_no_percentage_still_shows_something_that_moves(qtbot, tmp_path):
    win = _busy(qtbot, tmp_path)
    ring = win._busy_ring
    assert ring.isVisible() and ring.is_spinning() and ring.fraction() is None
    assert not win._progress.isVisible(), "no number when none is honest"
    win._set_busy(False)


def test_a_percentage_fills_the_ring_and_shows_the_number(qtbot, tmp_path):
    win = _busy(qtbot, tmp_path, "Separating stars…")
    win._set_progress("", 42, 100)
    assert win._busy_ring.fraction() == pytest.approx(0.42)
    assert not win._busy_ring.is_spinning()
    assert win._progress.isVisible() and win._progress.text() == "42%"
    win._set_busy(False)


def test_the_ring_sits_left_of_what_is_running(qtbot, tmp_path):
    win = _busy(qtbot, tmp_path)
    ring, label = win._busy_ring, win._busy_label
    assert ring.mapTo(win, ring.rect().topRight()).x() < label.mapTo(win, label.rect().topLeft()).x()
    rc = ring.mapTo(win, ring.rect().center()).y()
    lc = label.mapTo(win, label.rect().center()).y()
    assert abs(rc - lc) <= 4
    win._set_busy(False)


def test_when_the_work_ends_nothing_is_left_spinning(qtbot, tmp_path):
    win = _busy(qtbot, tmp_path)
    win._set_progress("", 30, 100)
    win._set_busy(False)
    win._hide_busy_visuals()
    assert not win._busy_ring.isVisible() and not win._busy_ring.is_spinning()
    assert win._busy_ring.fraction() is None, "the next op starts from 'no number', not 30%"
    assert not win._progress.isVisible()


def test_the_busy_state_fits_the_status_slot_under_the_real_stylesheet(qtbot, tmp_path):
    """The slot is a fixed 75 px measured for the fullest occupant; the ring row
    (20 px) replaced a 17 px text line and the 19 px bar row is gone, so the busy
    state must still fit without squeezing Cancel."""
    from PySide6.QtWidgets import QApplication
    from nocturne.ui.side_panel import STATUS_SLOT_H
    from nocturne.ui.theme import build_stylesheet
    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        win = _busy(qtbot, tmp_path, "Denoising with GraXpert — this can take a few minutes…")
        win._set_progress("", 42, 100)
        qtbot.wait(20)
        slot = win._side.status_slot
        assert slot.height() == STATUS_SLOT_H
        need = slot.layout().sizeHint().height()
        assert need <= STATUS_SLOT_H, f"busy state needs {need} px of {STATUS_SLOT_H}"
        cancel = win._cancel_btn
        assert cancel.height() >= cancel.sizeHint().height(), "Cancel must not be squeezed"
        win._set_busy(False)
    finally:
        app.setStyleSheet(before)


def test_the_dot_goes_when_the_number_goes(qtbot, tmp_path):
    win = _busy(qtbot, tmp_path)
    win._set_progress("", 42, 100)
    assert win._elapsed_label.text().startswith("· ")
    win._set_progress("", 0, 0)
    assert not win._elapsed_label.text().startswith("·"), "a lone dot with nothing before it"
    win._set_busy(False)


def test_a_long_phase_keeps_its_number_visible(qtbot, tmp_path):
    win = _busy(qtbot, tmp_path)
    win._set_progress("Denoising with GraXpert, tile by tile across the frame", 1234, 5678)
    shown = win._progress.text()
    assert shown.endswith("1234/5678") and shown.startswith("…")
    fm = win._progress.fontMetrics()
    from nocturne.ui.main_window import _PROGRESS_TEXT_W
    assert fm.horizontalAdvance(shown) <= _PROGRESS_TEXT_W
    assert "tile by tile" in win._progress.toolTip()
    win._set_busy(False)
