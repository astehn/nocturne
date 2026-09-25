import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from nocturne.settings import load_settings
from nocturne.ui.main_window import MIN_WINDOW
from tests.ui.test_main_window import _window


def test_geometry_is_saved_on_close_and_restored(qtbot, tmp_path):
    # The offscreen test platform's primary screen is 800x800, narrower than
    # MIN_WINDOW, so any size below the minimum is clamped on the way in —
    # this uses the minimum itself, which round-trips exactly and still
    # proves save-on-close + restore-on-open end to end.
    #
    # The size alone does NOT prove restoreGeometry ran: setMinimumSize
    # already puts a fresh, unshown MainWindow at MIN_WINDOW, so a stubbed
    # restoreGeometry that does nothing and returns True would pass a
    # size-only assertion. Probed directly: a fresh win2 sits at (0, 0); after
    # a real restore of geometry saved at (40, 60) it lands at y == 60 exactly
    # and x == 1 (frame-accounting shifts x, not y — tolerance 40 covers that
    # shift without accepting the untouched x == 0).
    win = _window(qtbot, tmp_path)
    win.show(); qtbot.waitExposed(win)
    win.setGeometry(QRect(40, 60, *MIN_WINDOW))
    win.close()
    assert load_settings(str(tmp_path / "settings.json")).window_geometry
    win2 = _window(qtbot, tmp_path)
    assert win2.restore_geometry_from_settings() is True
    assert (win2.width(), win2.height()) == MIN_WINDOW
    assert win2.y() == 60
    assert abs(win2.x() - 40) <= 40


def test_a_corrupt_saved_geometry_falls_back(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.settings.window_geometry = "not-hex!!"
    assert win.restore_geometry_from_settings() is False


def _on_a_screen(win) -> bool:
    frame = win.frameGeometry()
    return any(s.availableGeometry().intersects(frame) for s in QApplication.screens())


@pytest.mark.parametrize("restore", ["qt", "left_off_screen"])
def test_a_geometry_from_a_missing_monitor_falls_back(qtbot, tmp_path, monkeypatch, restore):
    """Through the app's own `place_window`, in BOTH branches of
    `restore_geometry_from_settings`. Offscreen, Qt's restoreGeometry pulls an
    off-screen geometry back itself (measured: saved at x 5797, restored at
    x -1), so the refusal branch is never reached; the second case makes
    restoreGeometry leave the window where the saved bytes put it — what a
    real multi-monitor Mac can do — so the fallback has to move it."""
    from nocturne.__main__ import place_window
    win = _window(qtbot, tmp_path)
    win.show(); qtbot.waitExposed(win)
    far = QApplication.primaryScreen().availableGeometry().right() + 5000
    win.setGeometry(QRect(far, 60, 1000, 700))
    win.settings.window_geometry = bytes(win.saveGeometry().toHex()).decode()
    if restore == "left_off_screen":
        def stays_off(_raw):
            win.setGeometry(QRect(far, 60, 1000, 700))
            return True
        monkeypatch.setattr(win, "restoreGeometry", stays_off)
    win.move(0, 0)
    decided = {}
    real = win.restore_geometry_from_settings
    monkeypatch.setattr(win, "restore_geometry_from_settings",
                        lambda: decided.setdefault("ok", real()))
    place_window(win, QApplication.instance(), None)
    assert decided["ok"] is (restore == "qt"), "the case did not reach its branch"
    assert _on_a_screen(win), (restore, win.frameGeometry())


def test_the_fallback_moves_a_window_that_restore_left_off_screen(qtbot, tmp_path):
    """The refused-restore branch on its own: whatever restoreGeometry did,
    the fallback alone must bring the window back."""
    win = _window(qtbot, tmp_path)
    win.show(); qtbot.waitExposed(win)
    far = QApplication.primaryScreen().availableGeometry().right() + 5000
    win.move(far, 60)
    assert not _on_a_screen(win)
    win.place_on_primary_screen((1280, 800))
    assert _on_a_screen(win)
    assert (win.width(), win.height()) == (1280, 800)


def test_the_minimum_size_fits_a_1280x720_screen(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert win.minimumWidth() <= 1280 and win.minimumHeight() <= 690


def test_the_minimum_is_the_layouts_own_and_fits_a_720_screen(qtbot, tmp_path):
    """Below the layout's own minimum Qt squeezes widgets past their minimum
    hints (the old 960x600 sat ~41 px under it). Measured with an image
    loaded, where the layout is largest; within 1280x690 so a 1280x720
    screen less its menu bar still fits."""
    from tests.ui.test_main_window import _make_fits
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.show(); qtbot.waitExposed(win)
    hint = win.minimumSizeHint()
    assert hint.width() <= MIN_WINDOW[0] <= 1280
    assert hint.height() <= MIN_WINDOW[1] <= 690
    assert (win.minimumWidth(), win.minimumHeight()) == MIN_WINDOW
