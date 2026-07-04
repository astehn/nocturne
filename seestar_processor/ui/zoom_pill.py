from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget


class ZoomPill(QWidget):
    """Floating zoom control: – / fit / + ."""

    def __init__(self, on_out, on_fit, on_in, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("zoomPill")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(2)
        self.out_btn = QPushButton("−")   # minus
        self.fit_btn = QPushButton("⤢")   # fit / expand glyph
        self.in_btn = QPushButton("+")
        for b, cb in ((self.out_btn, on_out), (self.fit_btn, on_fit),
                      (self.in_btn, on_in)):
            b.setFixedSize(28, 24)
            b.setFlat(True)
            b.clicked.connect(cb)
            lay.addWidget(b)
