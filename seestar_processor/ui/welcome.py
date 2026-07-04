from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .. import APP_NAME, APP_TAGLINE


class WelcomeScreen(QWidget):
    def __init__(self, on_open, on_stack, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("welcome")
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel(APP_NAME)
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline = QLabel(APP_TAGLINE)
        tagline.setObjectName("welcomeTag")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("Open a file or Stack a folder to begin")
        hint.setObjectName("welcomeHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.open_btn = QPushButton("Open FITS")
        self.open_btn.clicked.connect(lambda: on_open())
        self.stack_btn = QPushButton("Stack…")
        self.stack_btn.setObjectName("primary")
        self.stack_btn.clicked.connect(lambda: on_stack())
        buttons = QHBoxLayout()
        buttons.setAlignment(Qt.AlignmentFlag.AlignCenter)
        buttons.addWidget(self.open_btn)
        buttons.addWidget(self.stack_btn)

        root.addWidget(title)
        root.addWidget(tagline)
        root.addSpacing(8)
        root.addWidget(hint)
        root.addSpacing(20)
        root.addLayout(buttons)
