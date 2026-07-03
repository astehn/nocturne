from __future__ import annotations

# --- semantic colour tokens ---
BG_0 = "#16171a"     # deepest (canvas)
BG_1 = "#1e1f22"     # window
BG_2 = "#26282c"     # panels / toolbar
BG_3 = "#2f3237"     # inputs / raised
BORDER = "#3c4046"
ACCENT = "#2dd4bf"   # teal
ACCENT_HI = "#34e3cd"
SUCCESS = "#3fb950"  # green
WARNING = "#e3b341"  # amber
DANGER = "#f85149"   # red
TEXT = "#e6e6e6"
TEXT_DIM = "#8a9099"
TEXT_FAINT = "#5e636b"


def build_stylesheet() -> str:
    return f"""
* {{ color: {TEXT}; font-size: 14px; }}
QMainWindow, QWidget {{ background-color: {BG_1}; }}
QToolBar {{ background: {BG_2}; border: none; spacing: 4px; padding: 6px; }}
QToolBar::separator {{ background: {BORDER}; width: 1px; margin: 4px 6px; }}
QToolBar QToolButton {{ padding: 6px 10px; border-radius: 8px; color: {TEXT_DIM}; }}
QToolBar QToolButton:hover {{ background: {BG_3}; color: {TEXT}; }}
QToolBar QToolButton:pressed {{ background: {BORDER}; }}
QToolBar QToolButton:checked {{ background: {BG_3}; color: {ACCENT}; }}
QToolBar QToolButton:disabled {{ color: {TEXT_FAINT}; }}

QLabel#stageTitle {{ font-size: 20px; font-weight: 600; color: #ffffff; padding-bottom: 8px; }}

QListWidget {{ background: {BG_2}; border: none; outline: 0; padding: 8px; }}
QListWidget::item {{ padding: 2px; border-radius: 8px; margin: 1px 0; }}
QListWidget::item:selected {{ background: transparent; }}

QComboBox, QLineEdit {{ background: {BG_3}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 6px 10px; }}
QComboBox:focus, QLineEdit:focus {{ border: 1px solid {ACCENT}; }}

QPushButton {{ background: {BG_3}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 8px 14px; }}
QPushButton:hover {{ background: #3e4248; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; background: #2a2c30; }}
QPushButton#primary {{ background: {ACCENT}; color: #06201c; font-weight: 600; border: none; }}
QPushButton#primary:hover {{ background: {ACCENT_HI}; }}
QPushButton#primary:disabled {{ background: #2a2c30; color: {TEXT_FAINT}; }}

QGraphicsView {{ background: {BG_0}; border: 1px solid #2c2f34; }}

QSlider::groove:horizontal {{ height: 6px; background: {BG_3}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::add-page:horizontal {{ background: {BG_3}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 16px; height: 16px;
    margin: -6px 0; border-radius: 8px; }}
QSlider::handle:horizontal:hover {{ background: {ACCENT_HI}; }}

QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px;
    border: 1px solid {BORDER}; background: {BG_3}; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {ACCENT}; border: 1px solid {ACCENT}; }}

QProgressBar {{ background: {BG_3}; border: none; border-radius: 6px; height: 10px;
    text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 6px; }}

QHeaderView::section {{ background: {BG_3}; color: {TEXT_DIM}; border: none;
    padding: 6px 8px; }}
QTableWidget {{ background: {BG_2}; gridline-color: {BORDER};
    border: 1px solid {BORDER}; border-radius: 8px; }}
QTableWidget::item:hover {{ background: {BG_3}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #4a4f56; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


def apply_dark_theme(app) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(build_stylesheet())
