from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .. import APP_NAME
from .about import about_html


class AboutDialog(QDialog):
    def __init__(self, parent=None, html: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumSize(520, 560)

        self.wordmark = QLabel(APP_NAME)
        self.wordmark.setObjectName("aboutWordmark")
        self.wordmark.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.body = QLabel(html if html is not None else about_html())
        self.body.setObjectName("aboutBody")
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setOpenExternalLinks(False)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.addWidget(self.body)
        inner_lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        root = QVBoxLayout(self)
        root.addWidget(self.wordmark)
        root.addWidget(scroll, 1)
        root.addWidget(close_btn)
