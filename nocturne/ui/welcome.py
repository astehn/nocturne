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

        self.open_btn = QPushButton("Open Image")
        self.open_btn.clicked.connect(lambda: on_open())
        self.stack_btn = QPushButton("Stack…")
        self.stack_btn.setObjectName("primary")
        self.stack_btn.clicked.connect(lambda: on_stack())
        buttons = QHBoxLayout()
        buttons.setAlignment(Qt.AlignmentFlag.AlignCenter)
        buttons.addWidget(self.open_btn)
        buttons.addWidget(self.stack_btn)

        # A new release, announced once (Andreas, 2026-09-26: no pop-up). Its
        # room is reserved from the start: the check lands seconds after launch,
        # and an appearing line would lift the centred buttons under the cursor.
        self.update_note = QLabel("")
        self.update_note.setObjectName("welcomeUpdate")
        self.update_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.update_note.setOpenExternalLinks(True)
        self.update_note.setWordWrap(True)      # a narrow window wraps into the reserved second line
        self.update_note.setFixedHeight(self.update_note.fontMetrics().lineSpacing() * 2)

        root.addWidget(title)
        root.addWidget(tagline)
        root.addSpacing(8)
        root.addWidget(hint)
        root.addSpacing(20)
        root.addLayout(buttons)
        root.addSpacing(16)
        root.addWidget(self.update_note)

    def set_update_note(self, html: str) -> None:
        self.update_note.setText(html)
