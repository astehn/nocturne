"""The Plate Solve window opens ON TOP OF Nocturne, wherever Nocturne now is
(Andreas, 2026-10-01: several monitors; it reopened where it was last left,
an absolute desktop position, often on another screen — and it is small).
It remembers where it sat RELATIVE to the main window; if that spot is not
inside the main window, it opens at its default corner over the picture."""
from PySide6.QtCore import QPoint, QRect

from tests.ui.test_solve_window import win  # noqa: F401  (fixture)


def _inside_main(win):
    return win.frameGeometry().contains(win._solve_window.frameGeometry())


def test_it_follows_the_main_window_to_wherever_it_moved(win, qtbot):
    win._open_plate_solve(); qtbot.wait(20)
    win._solve_window.move(win._solve_window.pos() + QPoint(-120, 40)); qtbot.wait(20)
    offset = win._solve_window.pos() - win.pos()
    win._open_plate_solve()                          # close: remembers
    win.move(win.pos() + QPoint(1900, 300)); qtbot.wait(20)   # "another screen"
    win._open_plate_solve(); qtbot.wait(20)
    assert win._solve_window.pos() - win.pos() == offset
    assert _inside_main(win)


def test_dragged_outside_nocturne_it_comes_back_over_the_picture(win, qtbot):
    win._open_plate_solve(); qtbot.wait(20)
    default = win._solve_window.pos() - win.pos()
    win._solve_window.move(win.pos() + QPoint(win.width() + 400, 0)); qtbot.wait(20)
    win._open_plate_solve()
    win._open_plate_solve(); qtbot.wait(20)
    assert win._solve_window.pos() - win.pos() == default
    assert _inside_main(win)


def test_the_offset_survives_a_relaunch(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    from tests.ui.test_main_window import _make_fits, _window
    monkeypatch.setattr(mw, "astap_valid", lambda s: True)
    first = _window(qtbot, tmp_path)
    first.open_fits(_make_fits(tmp_path)); first.resize(1400, 900)
    first.show(); qtbot.waitExposed(first)
    first._open_plate_solve(); qtbot.wait(20)
    first._solve_window.move(first._solve_window.pos() + QPoint(-200, 60)); qtbot.wait(20)
    offset = first._solve_window.pos() - first.pos()
    first._open_plate_solve()
    other = tmp_path / "second"; other.mkdir()
    second = _window(qtbot, other)
    second.settings.solve_window_geometry = first.settings.solve_window_geometry
    second.settings.solve_window_offset = list(first.settings.solve_window_offset)
    second.open_fits(_make_fits(other)); second.resize(1400, 900)
    second.move(first.pos() + QPoint(2500, 0)); second.show(); qtbot.waitExposed(second)
    second._open_plate_solve(); qtbot.wait(20)
    assert second._solve_window.pos() - second.pos() == offset


def test_settings_from_before_the_offset_open_at_the_default_corner(win, qtbot):
    """An old settings file has the geometry but no offset: no absolute
    position from it may decide the place any more."""
    win._open_plate_solve(); qtbot.wait(20)
    default = win._solve_window.pos() - win.pos()
    win._solve_window.move(QPoint(5000, 5000)); qtbot.wait(20)
    win._open_plate_solve()
    win.settings.solve_window_offset = []
    win._solve_window_placed = False
    win._open_plate_solve(); qtbot.wait(20)
    assert win._solve_window.pos() - win.pos() == default


def test_the_offset_is_written_to_and_read_from_the_settings_file(tmp_path):
    from nocturne.settings import Settings, load_settings, save_settings
    path = str(tmp_path / "settings.json")
    s = Settings()
    s.solve_window_offset = [412, 37]
    save_settings(s, path)
    assert load_settings(path).solve_window_offset == [412, 37]
    old = Settings()
    save_settings(old, path)
    assert load_settings(path).solve_window_offset == []


def test_closing_it_in_fullscreen_keeps_the_windowed_offset(win, qtbot, monkeypatch):
    """An offset measured from a fullscreen window means nothing once the
    window is windowed again (review 2026-10-01)."""
    win._open_plate_solve(); qtbot.wait(20)
    win._open_plate_solve()
    before = list(win.settings.solve_window_offset)
    assert before, "fixture"
    win._open_plate_solve(); qtbot.wait(20)
    win._solve_window.move(win._solve_window.pos() + QPoint(-300, 200))
    monkeypatch.setattr(win, "isFullScreen", lambda: True)
    win._open_plate_solve()
    assert win.settings.solve_window_offset == before
