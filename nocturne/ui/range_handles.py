from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .theme import BG_0, BORDER

_MARGIN = 8
_MIN_SPAN = 0.02      # a band narrower than this selects essentially nothing
_ACCENT = "#ffd479"
_STRIP_GAP = 3        # breathing room between the histogram and the strip


class RangeHandles(QWidget):
    """A luminance histogram with two draggable bounds marking the band a tool
    applies to.

    `rangeChanged` fires on user drags only — `set_range` is deliberately
    silent, so a preset combo driving the handles cannot echo back and drive the
    combo in turn.
    """

    rangeChanged = Signal(float, float)

    # A black-to-white bar under the histogram, so the axis explains itself.
    # A histogram alone does not say WHAT is being selected — someone who has
    # not spent years in image editors has no way to know the handles pick by
    # brightness, or which end is which.
    STRIP_H = 12

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._lo, self._hi = 0.0, 1.0
        self._hist = None
        self._drag: str | None = None

    # --- model ---
    def range(self) -> tuple[float, float]:
        return (self._lo, self._hi)

    def set_range(self, lo: float, hi: float) -> None:
        lo = float(np.clip(lo, 0.0, 1.0))
        hi = float(np.clip(hi, 0.0, 1.0))
        self._lo, self._hi = min(lo, hi), max(lo, hi)
        self.update()

    def set_histogram(self, data) -> None:
        lum = data.mean(axis=2) if getattr(data, "ndim", 2) == 3 else data
        counts, _ = np.histogram(np.clip(lum, 0, 1), bins=128, range=(0.0, 1.0))
        self._hist = (counts / (counts.max() or 1)).astype(float)
        self.update()

    # --- coordinate mapping ---
    def _plot(self):
        """The histogram/handle area, excluding the gradient strip below it."""
        return (_MARGIN, _MARGIN, max(1, self.width() - 2 * _MARGIN),
                max(1, self.height() - 2 * _MARGIN - self.STRIP_H - _STRIP_GAP))

    def _x_to_px(self, x: float) -> float:
        ox, _oy, w, _h = self._plot()
        return ox + x * w

    def _px_to_x(self, px: float) -> float:
        ox, _oy, w, _h = self._plot()
        return float(np.clip((px - ox) / w, 0.0, 1.0))

    # --- mouse ---
    def mousePressEvent(self, e) -> None:
        x = self._px_to_x(e.position().x())
        self._drag = "lo" if abs(x - self._lo) <= abs(x - self._hi) else "hi"
        self._move(x)
        e.accept()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None:
            self._move(self._px_to_x(e.position().x()))

    def mouseReleaseEvent(self, e) -> None:
        self._drag = None
        e.accept()

    def _move(self, x: float) -> None:
        """Move the grabbed bound, keeping the two from crossing. A crossed pair
        is an empty band, and an empty band makes the tool silently inert."""
        if self._drag == "lo":
            self._lo = float(np.clip(min(x, self._hi - _MIN_SPAN), 0.0, 1.0))
        else:
            self._hi = float(np.clip(max(x, self._lo + _MIN_SPAN), 0.0, 1.0))
        self.update()
        self.rangeChanged.emit(self._lo, self._hi)

    # --- paint ---
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(BG_0))
        ox, oy, w, h = self._plot()

        if self._hist is not None:
            fill = QColor(BORDER)
            fill.setAlpha(70)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            n = len(self._hist)
            for i, v in enumerate(self._hist):
                p.drawRect(int(ox + i / n * w), int(oy + h - v * h),
                           max(1, int(w / n) + 1), int(v * h))

        band = QColor(_ACCENT)
        band.setAlpha(40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(band)
        lo_px, hi_px = self._x_to_px(self._lo), self._x_to_px(self._hi)
        p.drawRect(int(lo_px), oy, max(1, int(hi_px - lo_px)), h)

        p.setPen(QPen(QColor(_ACCENT), 2))
        for x in (lo_px, hi_px):
            p.drawLine(int(x), oy, int(x), oy + h + _STRIP_GAP + self.STRIP_H)

        strip_y = oy + h + _STRIP_GAP
        ramp = QLinearGradient(float(ox), 0.0, float(ox + w), 0.0)
        ramp.setColorAt(0.0, QColor(0, 0, 0))
        ramp.setColorAt(1.0, QColor(255, 255, 255))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ramp)
        p.drawRect(ox, int(strip_y), w, self.STRIP_H)
