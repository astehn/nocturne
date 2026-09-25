from __future__ import annotations

from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core.histogram import histogram
from .theme import BG_0, BORDER

_COLORS = {"r": "#ff5555", "g": "#55ff55", "b": "#5599ff", "l": "#cccccc"}

# The height the histogram had on every window before 2026-09-25, and still
# gets whenever the window has the room (SidePanel._rebalance).
HIST_NATURAL_H = 240
# The smallest height at which the plot still reads — the floor it yields to
# on a short window, before the step's controls give up anything.
#
# MEASURED on a real master (M8, 460 x 10 s, stretched at the default 0.30,
# 382 px wide), rendering heights 48-240 and reading off, per channel, the
# rightmost bin still drawn at >= 1 px — how far the faint tail (the
# nebulosity's shoulder, the part a stretch decision turns on) stays visible:
#
#     height   48    64    72    80    88    96    112   128   240
#     G tail  106   129   132   138   138   139   157   157   205
#     B tail  112   123   131   135   135   135   145   152   174
#
# 80 is the knee: below it the tail disappears quickly (-9 to -12 bins at 64,
# -26 to -32 at 48), while 80 -> 96 gains at most one bin. At 80 the channel
# peaks still stand 3-4 px apart, so a colour cast still shows, and the grid
# quarters are 20 px apart. Not lowered to fit any window budget.
HIST_FLOOR_H = 80


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
        self.setMinimumHeight(HIST_FLOOR_H)
        # Its height is SET by the side panel (SidePanel._rebalance), between
        # this floor and HIST_NATURAL_H, from the window size alone.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._hist = None

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return QSize(super().sizeHint().width(), HIST_NATURAL_H)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return QSize(0, HIST_FLOOR_H)

    def set_image(self, img) -> None:
        self._hist = histogram(img, bins=256)
        self.update()

    def hist(self) -> dict | None:
        """The counts behind the drawn curves, so the clipping summary can read
        the top and bottom bins instead of recomputing them."""
        return self._hist

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
