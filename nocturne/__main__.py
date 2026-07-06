import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME
from .settings import resolve_settings_path
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
    win = MainWindow(settings_path=resolve_settings_path())
    win.resize(1280, 760)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
