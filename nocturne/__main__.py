import multiprocessing
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME, __version__
from .settings import autoconfigure_tools, resolve_settings_path
from .ui.main_window import MainWindow
from .ui.splash import make_splash, remaining_hold
from .ui.theme import apply_dark_theme

_ASSETS = Path(__file__).resolve().parent / "assets"


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    icon_path = _ASSETS / "nocturne_icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    apply_dark_theme(app)

    # Shown BEFORE any startup work, and timed from here — the point is that the
    # work happens while it is up. Built after apply_dark_theme so the caption
    # inherits the app palette. `--no-splash` exists because the person who
    # relaunches this app most is the one working on it.
    splash = None
    started = time.monotonic()
    if "--no-splash" not in sys.argv:
        splash = make_splash(__version__)
        splash.show()
        app.processEvents()   # without this it is created but never painted

    # Before the window: a first run with the tools already installed should
    # need no trip to Settings at all. Only ever fills EMPTY paths.
    settings_path = resolve_settings_path()
    autoconfigure_tools(settings_path)

    win = MainWindow(settings_path=settings_path)
    win.resize(1280, 760)

    if splash is not None:
        # Spend the REMAINDER of the minimum, not a fixed delay: a slow launch
        # has already earned its visible time and waits for nothing extra.
        #
        # A nested QEventLoop, never time.sleep — sleeping blocks the event
        # loop, so the splash never paints and macOS shows a white rectangle
        # and then a beachball. A click ends the wait early via the same loop.
        hold = remaining_hold(time.monotonic() - started)
        if hold > 0:
            loop = QEventLoop()
            QTimer.singleShot(int(hold * 1000), loop.quit)
            splash.dismissed.connect(loop.quit)
            loop.exec()
        splash.finish(win)

    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    # MUST be the first thing, before Qt or anything else runs.
    #
    # Stacking registers frames in a process pool, and macOS SPAWNS rather than
    # forks — each worker re-imports the entry point. In a PyInstaller bundle
    # that means the app relaunching itself: a window per worker, recursively.
    # freeze_support() makes a spawned child run its task and exit instead.
    #
    # This fails ONLY in the shipped .app. A dev run and the whole test suite
    # are both silent about it, which is why it is pinned by a test that reads
    # this file rather than by anything that could observe the behaviour here.
    multiprocessing.freeze_support()
    main()
