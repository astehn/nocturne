from __future__ import annotations

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core.histogram import histogram
from .theme import BG_0, BORDER

_COLORS = {"r": "#ff5555", "g": "#55ff55", "b": "#5599ff", "l": "#cccccc"}


def _polygon_points(counts, w: int, h: int, peak: int):
    """Closed area-polygon points for a channel: a filled curve from the
    baseline up to each bin height and back, spanning the full width."""
    n = len(counts)
    if n == 0 or peak <= 0:
        return [(0.0, float(h)), (float(w), float(h))]
    pts = [(0.0, float(h))]
    for x in range(n):
        bx = x / (n - 1) * w if n > 1 else 0.0
        by = h - (counts[x] / peak) * (h - 2)
        pts.append((bx, by))
    pts.append((float(w), float(h)))
    return pts


class HistogramView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._hist = None

    def set_image(self, img) -> None:
        self._hist = histogram(img, bins=256)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(BG_0))
        w, h = self.width(), self.height()
        # faint horizontal grid
        grid = QColor(BORDER)
        grid.setAlpha(90)
        p.setPen(QPen(grid, 1))
        for i in range(1, 4):
            y = int(h * i / 4)
            p.drawLine(0, y, w, y)
        if not self._hist:
            return
        peak = max(int(c.max()) for c in self._hist.values()) or 1
        for key, counts in self._hist.items():
            col = QColor(_COLORS[key])
            fill = QColor(col)
            fill.setAlpha(70)
            poly = QPolygonF([QPointF(x, y) for x, y in
                              _polygon_points(counts, w, h, peak)])
            p.setPen(QPen(col, 1))
            p.setBrush(fill)
            p.drawPolygon(poly)
