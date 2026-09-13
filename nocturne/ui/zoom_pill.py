from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class ZoomPill(QWidget):
    """Floating zoom control: 100% − ⤢ + ."""

    def __init__(self, on_out, on_fit, on_in, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("zoomPill")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(2)
        # Always shown, never only-while-zoomed: an element that appears and
        # disappears draws the eye at exactly the moment you are busy looking at
        # the picture. At fit it simply reads whatever fit happens to be.
        self.level = QLabel("100%")
        self.level.setObjectName("zoomLevel")
        self.level.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Fixed width so the pill does not breathe between 98% and 100% — the
        # readout sits on the canvas, and a control that changes size as you
        # zoom is its own distraction. Wide enough for the 3200% ceiling.
        self.level.setFixedWidth(46)
        lay.addWidget(self.level)
        self.out_btn = QPushButton("−")   # minus
        self.fit_btn = QPushButton("⤢")   # fit / expand glyph
        self.in_btn = QPushButton("+")
        for b, cb in ((self.out_btn, on_out), (self.fit_btn, on_fit),
                      (self.in_btn, on_in)):
            b.setFixedSize(28, 24)
            b.setFlat(True)
            b.clicked.connect(cb)
            lay.addWidget(b)

    def set_zoom(self, scale: float) -> None:
        """Show the display scale as a percentage.

        Rounded to whole percent below 10x and to the nearest 10 above it: past
        that the trailing digits change on every wheel click and carry nothing
        — nobody reads 1187% differently from 1190%.
        """
        pct = max(0.0, float(scale)) * 100.0
        text = f"{pct:.0f}%" if pct < 1000 else f"{round(pct / 10) * 10:.0f}%"
        if text != self.level.text():
            self.level.setText(text)
