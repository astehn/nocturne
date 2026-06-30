import os
import sys

from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    settings_path = os.path.join(
        os.path.expanduser("~"), ".seestar_processor", "settings.json"
    )
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    win = MainWindow(settings_path=settings_path)
    win.resize(1200, 720)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
