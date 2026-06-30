from __future__ import annotations

from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core.histogram import histogram

_COLORS = {"r": "#ff5555", "g": "#55ff55", "b": "#5599ff", "l": "#cccccc"}


class HistogramView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(240)
        # Grow into the spare space in the right column.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._hist = None

    def set_image(self, img) -> None:
        self._hist = histogram(img, bins=256)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#131417"))
        if not self._hist:
            return
        w, h = self.width(), self.height()
        peak = max(int(c.max()) for c in self._hist.values()) or 1
        n = len(next(iter(self._hist.values())))
        for key, counts in self._hist.items():
            p.setPen(QPen(QColor(_COLORS[key])))
            for x in range(n):
                bx = int(x / n * w)
                bh = int(counts[x] / peak * (h - 2))
                p.drawLine(bx, h, bx, h - bh)
