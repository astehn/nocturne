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


def test_close_project_closes_the_tool(win, qtbot):
    win._open_plate_solve()
    win._close_project()
    assert not win._solve_window.isVisible() and not win._solve_act.isChecked()


def test_fullscreen_hides_it_and_brings_it_back(win, qtbot):
    win._open_plate_solve()
    win._hide_chrome_for_fullscreen()
    assert not win._solve_window.isVisible()
    win._restore_chrome_after_fullscreen()
    assert win._solve_window.isVisible()


def test_quitting_with_it_open_keeps_its_place(win, qtbot):
    win._open_plate_solve(); qtbot.wait(20)
    win._solve_window.move(90, 110); qtbot.wait(20)
    win.settings.solve_window_geometry = ""
    win._dirty = False
    win.close()
    assert win.settings.solve_window_geometry, "quitting with it open lost its place"


def test_a_solve_landing_after_the_window_closed_leaves_the_button_off(win, qtbot, monkeypatch):
    from astropy.wcs import WCS
    from nocturne.tools.astap import SolveResult
    from nocturne.core.catalog import CatalogObject
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    win._open_plate_solve()
    win._solve_window.close()
    monkeypatch.setattr(win, "_solve_current", lambda img: (
        SolveResult(True, wc, 100.0, 0.0, 3.6),
        [CatalogObject("NGC 7000", "North America", 100.0, 0.0, 120.0, 12, 12)]))
    win._on_resolve_requested(); qtbot.wait(50)
    assert not win._solve_window.isVisible()
    assert not win._solve_act.isChecked()


def test_solve_is_greyed_out_while_another_step_runs(win, qtbot):
    win._open_plate_solve()
    assert win.solve_panel.resolve_btn.isEnabled()
    win._set_busy(True, "probe")
    assert not win.solve_panel.resolve_btn.isEnabled()
    win._set_busy(False)
    assert win.solve_panel.resolve_btn.isEnabled()


def test_the_result_is_readable_whole(win, qtbot, monkeypatch):
    """His screenshot, 2026-09-26: the window kept the size it opened at, and
    the result card below was clipped. The window follows its content."""
    from astropy.wcs import WCS
    from nocturne.tools.astap import SolveResult
    from nocturne.core.catalog import CatalogObject
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    monkeypatch.setattr(win, "_solve_current", lambda img: (
        SolveResult(True, wc, 100.0, 0.0, 3.6),
        [CatalogObject("vdB 142", "Elephant's Trunk Nebula", 100.0, 0.0, 120.0, 12, 12)]))
    win._open_plate_solve(); qtbot.wait(20)
    # As narrow and short as it may be — his window was narrow, so the wrapped
    # result needed more lines than the window kept room for.
    win._solve_window.resize(win._solve_window.minimumWidth(), 120); qtbot.wait(20)
    win._on_resolve_requested(); qtbot.wait(80)
    card = win.solve_panel.result_label
    assert card.text()
    need = card.heightForWidth(card.width())
    assert card.height() >= need, f"result card clipped: {card.height()} < {need}"
    assert win._solve_window.rect().contains(
        card.mapTo(win._solve_window, card.rect().bottomRight())), "the card runs past the window"
