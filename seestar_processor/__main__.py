import os
import sys

from PySide6.QtWidgets import QApplication

from . import APP_NAME
from .ui.main_window import MainWindow
from .ui.theme import apply_dark_theme


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    apply_dark_theme(app)
    settings_path = os.path.join(
        os.path.expanduser("~"), ".seestar_processor", "settings.json"
    )
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    win = MainWindow(settings_path=settings_path)
    win.resize(1280, 760)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
