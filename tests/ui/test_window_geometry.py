from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from nocturne.settings import load_settings
from tests.ui.test_main_window import _window


def test_geometry_is_saved_on_close_and_restored(qtbot, tmp_path):
    # The offscreen test platform's primary screen is 800x800 and MIN_WINDOW
    # is 960x600 wide, so any width below the minimum is clamped on the way
    # in — this uses the minimum itself, which round-trips exactly and still
    # proves save-on-close + restore-on-open end to end.
    #
    # The size alone does NOT prove restoreGeometry ran: setMinimumSize(960, 600)
    # already puts a fresh, unshown MainWindow at 960x600, so a stubbed
    # restoreGeometry that does nothing and returns True would pass a
    # size-only assertion. Probed directly: a fresh win2 sits at (0, 0); after
    # a real restore of geometry saved at (40, 60, 960, 600) it lands at
    # y == 60 exactly and x == 1 (frame-accounting shifts x, not y — tolerance
    # 40 covers that shift without accepting the untouched x == 0).
    win = _window(qtbot, tmp_path)
    win.show(); qtbot.waitExposed(win)
    win.setGeometry(QRect(40, 60, 960, 600))
    win.close()
    assert load_settings(str(tmp_path / "settings.json")).window_geometry
    win2 = _window(qtbot, tmp_path)
    assert win2.restore_geometry_from_settings() is True
    assert (win2.width(), win2.height()) == (960, 600)
    assert win2.y() == 60
    assert abs(win2.x() - 40) <= 40


def test_a_corrupt_saved_geometry_falls_back(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.settings.window_geometry = "not-hex!!"
    assert win.restore_geometry_from_settings() is False


def test_a_geometry_from_a_missing_monitor_falls_back(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.show(); qtbot.waitExposed(win)
    win.setGeometry(QRect(40, 60, 700, 560))
    raw = bytes(win.saveGeometry().toHex()).decode()
    win.settings.window_geometry = raw
    far = QApplication.primaryScreen().availableGeometry().right() + 5000
    win.move(far, 60)
    win.settings.window_geometry = bytes(win.saveGeometry().toHex()).decode()
    ok = win.restore_geometry_from_settings()
    screen = QApplication.primaryScreen().availableGeometry()
    assert ok is False or screen.intersects(win.frameGeometry())


def test_the_minimum_size_fits_a_1280x720_screen(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert win.minimumWidth() <= 1280 and win.minimumHeight() <= 690
