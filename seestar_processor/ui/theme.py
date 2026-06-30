from __future__ import annotations

ACCENT = "#2dd4bf"  # teal accent

_DARK_QSS = f"""
* {{ color: #e6e6e6; font-size: 13px; }}
QMainWindow, QWidget {{ background-color: #1e1f22; }}
QToolBar {{ background: #26282c; border: none; spacing: 6px; padding: 4px; }}
QToolBar QToolButton {{ padding: 6px 10px; border-radius: 6px; }}
QToolBar QToolButton:hover {{ background: #34373c; }}
QToolBar QToolButton:disabled {{ color: #6b6f76; }}
QLabel#stageTitle {{ font-size: 18px; font-weight: 600; color: #ffffff; padding-bottom: 6px; }}
QListWidget {{ background: #26282c; border: none; outline: 0; padding: 6px; }}
QListWidget::item {{ padding: 10px 12px; border-radius: 6px; margin: 2px 0; }}
QListWidget::item:selected {{ background: {ACCENT}; color: #06201c; font-weight: 600; }}
QListWidget::item:disabled {{ color: #5e636b; }}
QComboBox {{ background: #2f3237; border: 1px solid #3c4046; border-radius: 6px; padding: 6px 8px; }}
QPushButton {{ background: #34373c; border: 1px solid #3c4046; border-radius: 6px; padding: 8px 14px; }}
QPushButton:hover {{ background: #3e4248; }}
QPushButton:disabled {{ color: #6b6f76; background: #2a2c30; }}
QPushButton#primary {{ background: {ACCENT}; color: #06201c; font-weight: 600; border: none; }}
QPushButton#primary:hover {{ background: #34e3cd; }}
QPushButton#primary:disabled {{ background: #2a2c30; color: #6b6f76; }}
QGraphicsView {{ background: #131417; border: 1px solid #2c2f34; }}
"""


def apply_dark_theme(app) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(_DARK_QSS)
