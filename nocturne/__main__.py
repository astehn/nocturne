import multiprocessing
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME
from .settings import autoconfigure_tools, resolve_settings_path
from .ui.main_window import MainWindow
from .ui.theme import apply_dark_theme

_ASSETS = Path(__file__).resolve().parent / "assets"


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    icon_path = _ASSETS / "nocturne_icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    apply_dark_theme(app)

    # Before the window: a first run with the tools already installed should
    # need no trip to Settings at all. Only ever fills EMPTY paths.
    settings_path = resolve_settings_path()
    autoconfigure_tools(settings_path)

    win = MainWindow(settings_path=settings_path)
    win.resize(1280, 760)
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
