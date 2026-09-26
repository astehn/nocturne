"""Plate Solve in a floating tool window (Andreas, 2026-09-26)."""
import pytest
from PySide6.QtCore import QPoint, QRect

from tests.ui.test_main_window import _make_fits, _window


@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    monkeypatch.setattr(mw, "astap_valid", lambda s: True)
    w = _window(qtbot, tmp_path)
    w.open_fits(_make_fits(tmp_path))
    w.resize(1400, 900); w.show(); qtbot.waitExposed(w)
    return w


def test_its_own_close_box_closes_the_tool(win, qtbot):
    win._open_plate_solve()
    assert win._solve_window.isVisible() and win._solve_act.isChecked()
    win._solve_window.close()
    assert not win._solve_window.isVisible()
    assert not win._solve_act.isChecked(), "the toolbar button still says open"


def test_the_toolbar_button_opens_and_closes_it(win, qtbot):
    win._open_plate_solve()
    assert win._solve_window.isVisible()
    win._open_plate_solve()
    assert not win._solve_window.isVisible() and not win._solve_act.isChecked()


def test_it_first_opens_over_the_picture_not_the_right_column(win, qtbot):
    win.settings.solve_window_geometry = ""
    win._open_plate_solve(); qtbot.wait(20)
    tl = win.image_view.mapToGlobal(QPoint(0, 0))
    picture = QRect(tl, win.image_view.size())
    frame = win._solve_window.geometry()
    assert picture.contains(frame.topLeft()) and frame.right() <= picture.right()
    side_left = win._side.mapToGlobal(QPoint(0, 0)).x()
    assert frame.right() < side_left, "it covers the right column's controls"


def test_it_reopens_where_it_was_put(win, qtbot):
    win._open_plate_solve(); qtbot.wait(20)
    win._solve_window.move(win._solve_window.x() - 120, win._solve_window.y() + 40)
    qtbot.wait(20)
    moved = win._solve_window.pos()
    win._open_plate_solve()                 # close — remembers
    assert win.settings.solve_window_geometry
    win._open_plate_solve(); qtbot.wait(20)  # reopen
    assert win._solve_window.pos() == moved


def test_the_main_window_stays_usable_while_it_is_open(win, qtbot):
    from PySide6.QtWidgets import QApplication
    win._open_plate_solve()
    assert QApplication.activeModalWidget() is None
    assert win._next_btn.isEnabled()


def test_the_next_launch_restores_the_saved_place(qtbot, tmp_path, monkeypatch):
    """Across launches the place comes from Settings."""
    import nocturne.ui.main_window as mw
    monkeypatch.setattr(mw, "astap_valid", lambda s: True)
    first = _window(qtbot, tmp_path)
    first.open_fits(_make_fits(tmp_path)); first.show(); qtbot.waitExposed(first)
    first._open_plate_solve(); qtbot.wait(20)
    first._solve_window.move(100, 120); qtbot.wait(20)
    first._open_plate_solve()
    saved = first.settings.solve_window_geometry
    assert saved
    other = tmp_path / "second-launch"
    other.mkdir()
    second = _window(qtbot, other)
    second.settings.solve_window_geometry = saved
    second.open_fits(_make_fits(other)); second.show(); qtbot.waitExposed(second)
    second._open_plate_solve(); qtbot.wait(20)
    assert second._solve_window.pos() == QPoint(100, 120)
