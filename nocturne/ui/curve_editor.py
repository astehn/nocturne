from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core.curves import _MIN_GAP, build_lut, sanitize_points
from .theme import BG_0, BORDER

_HIT = 0.035          # handle hit radius in normalized coords
_MARGIN = 8           # px inset so handles at the edges stay visible


class CurveEditor(QWidget):
    """A draggable tone-curve editor. Interior points can be added (click empty
    space), moved (drag), and removed (double-click); the two corner endpoints
    (0,0) and (1,1) are pinned. Emits `curveChanged` with the point list."""

    curveChanged = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(240, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._points: list[tuple[float, float]] = [(0.0, 0.0), (1.0, 1.0)]
        self._hist = None          # normalized [0,1] bin heights, or None
        self._drag: int | None = None

    # --- model ---
    def points(self) -> list[tuple[float, float]]:
        return list(self._points)

    @staticmethod
    def _sanitize(pts) -> list[tuple[float, float]]:
        return sanitize_points(pts)

    def set_points(self, pts) -> None:
        self._points = self._sanitize(pts)
        self.update()
        self.curveChanged.emit(self.points())

    def add_point(self, x: float, y: float) -> None:
        self.set_points(self._points + [(x, y)])

    def remove_point(self, index: int) -> None:
        if 0 < index < len(self._points) - 1:   # never a corner
            self.set_points(self._points[:index] + self._points[index + 1:])

    def reset(self) -> None:
        self.set_points([(0.0, 0.0), (1.0, 1.0)])

    def set_histogram(self, data) -> None:
        lum = data.mean(axis=2) if data.ndim == 3 else data
        counts, _ = np.histogram(np.clip(lum, 0, 1), bins=128, range=(0.0, 1.0))
        peak = counts.max() or 1
        self._hist = (counts / peak).astype(float)
        self.update()

    # --- coordinate mapping (normalized [0,1] <-> widget px; y is inverted) ---
    def _plot_rect(self):
        return (_MARGIN, _MARGIN,
                max(1, self.width() - 2 * _MARGIN),
                max(1, self.height() - 2 * _MARGIN))

    def _to_px(self, x: float, y: float):
        ox, oy, w, h = self._plot_rect()
        return QPointF(ox + x * w, oy + (1.0 - y) * h)

    def _to_norm(self, px: float, py: float):
        ox, oy, w, h = self._plot_rect()
        return (float(np.clip((px - ox) / w, 0, 1)),
                float(np.clip(1.0 - (py - oy) / h, 0, 1)))

    def _nearest(self, x: float, y: float):
        best, best_d = None, _HIT
        for i, (px, py) in enumerate(self._points):
            d = ((px - x) ** 2 + (py - y) ** 2) ** 0.5
            if d < best_d:
                best, best_d = i, d
        return best

    # --- mouse ---
    def mousePressEvent(self, e) -> None:
        x, y = self._to_norm(e.position().x(), e.position().y())
        i = self._nearest(x, y)
        if i is None:
            self.add_point(x, y)
            self._drag = self._nearest(x, y)     # grab the just-added point
        else:
            self._drag = i
        e.accept()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is None:
            return
        i = self._drag
        if i == 0 or i == len(self._points) - 1:  # corners are pinned
            return
        x, y = self._to_norm(e.position().x(), e.position().y())
        lo = self._points[i - 1][0] + _MIN_GAP
        hi = self._points[i + 1][0] - _MIN_GAP
        if hi <= lo:                              # no room -> keep current x
            x = self._points[i][0]
        else:
            x = float(np.clip(x, lo, hi))
        pts = list(self._points)
        pts[i] = (x, y)
        self._points = pts
        self.update()
        self.curveChanged.emit(self.points())

    def mouseReleaseEvent(self, e) -> None:
        self._drag = None
        e.accept()

    def mouseDoubleClickEvent(self, e) -> None:   # noqa: N802 (Qt override)
        x, y = self._to_norm(e.position().x(), e.position().y())
        i = self._nearest(x, y)
        if i is not None:
            self.remove_point(i)
        e.accept()

    # --- paint ---
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(BG_0))
        ox, oy, w, h = self._plot_rect()

        if self._hist is not None:
            fill = QColor(BORDER)
            fill.setAlpha(70)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            n = len(self._hist)
            for i, v in enumerate(self._hist):
                bx = ox + i / n * w
                bh = v * h
                p.drawRect(int(bx), int(oy + h - bh), max(1, int(w / n) + 1), int(bh))

        grid = QColor(BORDER)
        grid.setAlpha(110)
        p.setPen(QPen(grid, 1))
        for i in range(1, 4):
            p.drawLine(int(ox + w * i / 4), oy, int(ox + w * i / 4), oy + h)
            p.drawLine(ox, int(oy + h * i / 4), ox + w, int(oy + h * i / 4))
        diag = QColor(BORDER)
        diag.setAlpha(140)
        p.setPen(QPen(diag, 1, Qt.PenStyle.DashLine))
        p.drawLine(self._to_px(0, 0), self._to_px(1, 1))

        lut = build_lut(self._points, n=max(2, w))
        curve = QPolygonF([self._to_px(i / (len(lut) - 1), float(v))
                           for i, v in enumerate(lut)])
        p.setPen(QPen(QColor("#cccccc"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(curve)

        for i, (px, py) in enumerate(self._points):
            corner = i == 0 or i == len(self._points) - 1
            p.setBrush(QColor("#888888") if corner else QColor("#ffffff"))
            p.setPen(QPen(QColor("#333333"), 1))
            c = self._to_px(px, py)
            p.drawEllipse(c, 5, 5)
