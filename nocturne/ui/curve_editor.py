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
    """A draggable tone-curve editor. Points can be added (click empty space),
    moved (drag, or arrow-key the selected one), and removed (double-click).

    The two END points move like any other — dragging the low one right sets a
    black point, the high one left a white point. They used to be pinned at
    (0,0) and (1,1), which made both impossible; `build_lut` holds the end values
    outside the point range so a moved endpoint clips or rolls off correctly.
    Only the first and last cannot be deleted, since a curve needs two points.

    Emits `curveChanged` with the point list."""

    curveChanged = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(240, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._points: list[tuple[float, float]] = [(0.0, 0.0), (1.0, 1.0)]
        self._hist = None          # normalized [0,1] bin heights, or None
        self._drag: int | None = None
        self._selected: int | None = None    # survives release, so keys can nudge
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

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
        if 0 < index < len(self._points) - 1:   # a curve needs two points
            self.set_points(self._points[:index] + self._points[index + 1:])

    def reset(self) -> None:
        self._selected = None
        self.set_points([(0.0, 0.0), (1.0, 1.0)])

    def select_point(self, i: int | None) -> None:
        """Mark a point as the one the keyboard acts on."""
        self._selected = i if i is None or 0 <= i < len(self._points) else None
        self.update()

    def readout_text(self) -> str:
        """Input/output of the selected point. A curve editor without numbers is
        guesswork: one pixel of a 240 px widget is about 0.004, so there was no
        way to know what value a drag had actually set."""
        if self._selected is None or self._selected >= len(self._points):
            return ""
        x, y = self._points[self._selected]
        return f"in {x:.2f}   out {y:.2f}"

    def set_histogram(self, data) -> None:
        lum = data.mean(axis=2) if data.ndim == 3 else data
        counts, _ = np.histogram(np.clip(lum, 0, 1), bins=128, range=(0.0, 1.0))
        peak = counts.max() or 1
        self._hist = (counts / peak).astype(float)
        self.update()

    # --- coordinate mapping (normalized [0,1] <-> widget px; y is inverted) ---
    def _plot_rect(self):
        """A SQUARE plot, centred.

        A tone curve maps [0,1] to [0,1], so a stretched plot is a lie: the
        identity line is not at 45 degrees and a horizontal drag moves further
        per pixel than a vertical one. Measured in the real app the inline
        editor is 336 x 240, so a horizontal drag moved 1.4x further — hand and
        curve disagreed, which is much of what "fiddly" meant.

        Drawing AND hit-testing both come through here (_to_px / _to_norm), so
        they cannot drift apart.
        """
        side = max(1, min(self.width(), self.height()) - 2 * _MARGIN)
        ox = (self.width() - side) // 2
        oy = (self.height() - side) // 2
        return (ox, oy, side, side)

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
        self._selected = self._drag              # the keyboard follows the mouse
        e.accept()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is None:
            return
        self._move_to(self._drag, *self._to_norm(e.position().x(), e.position().y()))

    def _move_to(self, i: int, x: float, y: float) -> None:
        """Move point `i`, keeping the x-order build_lut depends on.

        The endpoints move like any other point — dragging the low one right is
        how you set a black point, the high one left a white point. They used to
        be pinned at the corners, which made both impossible. Only the
        neighbours constrain them, so an endpoint is free to slide along its own
        end of the range.
        """
        lo = self._points[i - 1][0] + _MIN_GAP if i > 0 else 0.0
        hi = self._points[i + 1][0] - _MIN_GAP if i < len(self._points) - 1 else 1.0
        x = self._points[i][0] if hi <= lo else float(np.clip(x, lo, hi))
        pts = list(self._points)
        pts[i] = (x, float(np.clip(y, 0.0, 1.0)))
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

    # --- keyboard ---
    _NUDGE = 1.0 / 255.0        # one 8-bit output level: the smallest step the
                                # exported file can actually represent
    _NUDGE_COARSE = 10.0 / 255.0

    def keyPressEvent(self, e) -> None:      # noqa: N802 (Qt override)
        deltas = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                  Qt.Key.Key_Down: (0, -1), Qt.Key.Key_Up: (0, 1)}
        d = deltas.get(e.key())
        if d is None or self._selected is None:
            super().keyPressEvent(e)
            return
        step = (self._NUDGE_COARSE
                if e.modifiers() & Qt.KeyboardModifier.ShiftModifier
                else self._NUDGE)
        x, y = self._points[self._selected]
        self._move_to(self._selected, x + d[0] * step, y + d[1] * step)
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
            end = i == 0 or i == len(self._points) - 1
            p.setBrush(QColor("#ffd479") if i == self._selected
                       else QColor("#bbbbbb") if end else QColor("#ffffff"))
            p.setPen(QPen(QColor("#333333"), 1))
            c = self._to_px(px, py)
            p.drawEllipse(c, 6 if i == self._selected else 5,
                          6 if i == self._selected else 5)

        text = self.readout_text()
        if text:
            p.setPen(QPen(QColor("#cccccc"), 1))
            p.drawText(ox + 4, oy + 14, text)
