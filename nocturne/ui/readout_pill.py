from __future__ import annotations

from PySide6.QtWidgets import QLabel


class ReadoutPill(QLabel):
    """Floating readout of the pixel under the cursor. Sits bottom-left on the
    canvas, mirroring the ZoomPill bottom-right. Deliberately dumb — the caller
    formats the string; this only shows it."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("readoutPill")
        self.hide()

    def show_text(self, text: str) -> None:
        self.setText(text)
        self.adjustSize()
        self.show()
