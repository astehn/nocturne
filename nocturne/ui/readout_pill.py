from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


class ReadoutPill(QLabel):
    """Floating readout of the pixel under the cursor. Sits bottom-left on the
    canvas, mirroring the ZoomPill bottom-right. Deliberately dumb — the caller
    formats the string; this only shows it.

    RICH text, because the caller tints the R/G/B segments in their own colours
    (`main_window._tinted`). Kept here rather than set per call so the pill has
    one text mode: a caller that forgot would render the markup as literal
    characters.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("readoutPill")
        self.setTextFormat(Qt.TextFormat.RichText)
        self.hide()

    def show_text(self, text: str) -> None:
        self.setText(text)
        self.adjustSize()
        self.show()
