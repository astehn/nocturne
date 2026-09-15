from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .theme import BG_0, BORDER

_MARGIN = 8
_MIN_SPAN = 0.02      # a band narrower than this selects essentially nothing
_ACCENT = "#ffd479"
_STRIP_GAP = 3        # breathing room between the histogram and the strip
_DATA = "#0d0e10"     # the histogram itself: darker than either ground
_OUTSIDE = "#1e2024"  # ground beyond the handles, so dark bars still read
_KNOB_PX = 18         # round grab handle, as the before/after divider has.
                      # 14 was tried first: the two arrows inside it read as a
                      # ring with a dot rather than "drag me sideways".


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
        # 96 was the height before the knobs had a row of their own; without
        # this the extra row comes out of the histogram instead.
        self.setMinimumHeight(96 + _STRIP_GAP + _KNOB_PX)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # The whole widget is a horizontal drag surface — a press anywhere
        # grabs the nearer bound — so the cursor should say so everywhere.
        self.setCursor(Qt.CursorShape.SplitHCursor)
        self._lo, self._hi = 0.0, 1.0
        self._hist = None
        self._drag: str | None = None
        # Persists past mouse release, unlike `_drag` (which is only "which
        # handle is currently held"). Starless Levels needs "which handle was
        # worked LAST" to follow Photoshop's black/white-point polarity, and
        # that has to survive the button-up that ends the gesture. A small
        # accessor rather than a widened `rangeChanged` signal, because
        # `color_balance_dialog.py`'s existing `rangeChanged.connect(lambda lo,
        # hi: ...)` would break on an extra positional argument.
        self._last_handle: str | None = None

    # --- model ---
    def range(self) -> tuple[float, float]:
        return (self._lo, self._hi)

    def last_handle(self) -> str | None:
        """"lo", "hi", or None if no drag has happened yet on this widget.

        Only a real drag (`_move`, via mouse press/move) updates this —
        `set_range` stays silent on purpose (see its own docstring), so a
        preset or a typed readout does not make it look as though a handle
        was touched by hand."""
        return self._last_handle

    def reset_last_handle(self) -> None:
        """Forget which handle was last dragged.

        For a caller whose Reset means "nothing is being worked now" — without
        it, a view that follows the worked end keeps pointing at an edit the
        user has just thrown away."""
        self._last_handle = None

    def set_range(self, lo: float, hi: float) -> None:
        """Set both bounds, ordered, clamped into [0, 1] and never narrower
        than `_MIN_SPAN`.

        The span clamp is here as well as in `_move` because the mouse is not
        the only way in: `set_range(0.5, 0.5)` gave a zero span that
        `apply_levels` silently rescues as `white = black + 1e-4`, so the
        readouts described an operation that never happened — the exact failure
        `_move`'s clamp exists to prevent, reachable by every preset, spin box
        and test that comes through this door instead.

        The low bound is the one kept: a caller that hands over a degenerate
        band has usually computed the low end from the image and let the high
        end collapse onto it, and at the very top of the range there is nowhere
        left to push the high bound, so the low one gives way instead.
        """
        lo = float(np.clip(lo, 0.0, 1.0))
        hi = float(np.clip(hi, 0.0, 1.0))
        lo, hi = min(lo, hi), max(lo, hi)
        if hi - lo < _MIN_SPAN:
            hi = min(1.0, lo + _MIN_SPAN)
            lo = max(0.0, hi - _MIN_SPAN)
        self._lo, self._hi = lo, hi
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
                max(1, self.height() - 2 * _MARGIN - self.STRIP_H - _STRIP_GAP
                    - _STRIP_GAP - _KNOB_PX))

    def _x_to_px(self, x: float) -> float:
        ox, _oy, w, _h = self._plot()
        return ox + x * w

    def _px_to_x(self, px: float) -> float:
        ox, _oy, w, _h = self._plot()
        return float(np.clip((px - ox) / w, 0.0, 1.0))

    def knob_center(self, which: str) -> QPointF:
        """Where the round grab handle for "lo"/"hi" is drawn.

        BELOW the gradient strip, in a row of its own. Two other places were
        tried and are worse: at mid-height it covers the tallest bars, which is
        exactly where the handles are being aimed; on the strip itself, the
        default full range parks both knobs on the ramp's black and white ends —
        the two reference points that make the axis self-explanatory. Below it
        is also where Photoshop puts its level triangles.
        """
        _ox, oy, _w, h = self._plot()
        x = self._x_to_px(self._lo if which == "lo" else self._hi)
        return QPointF(x, oy + h + _STRIP_GAP + self.STRIP_H
                       + _STRIP_GAP + _KNOB_PX / 2.0)

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
        self._last_handle = self._drag
        self.update()
        self.rangeChanged.emit(self._lo, self._hi)

    # --- paint ---
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(BG_0))
        ox, oy, w, h = self._plot()

        # Outside the selected band there is no amber wash to silhouette the
        # bars against, and a dark bar on the near-black ground is invisible —
        # which matters most exactly there, because the handles are dragged to
        # where the data BEGINS and ENDS. A slight lift gives the excluded
        # region a ground of its own without competing with the band.
        lo_px, hi_px = self._x_to_px(self._lo), self._x_to_px(self._hi)
        p.fillRect(int(ox), oy, max(0, int(lo_px - ox)), h, QColor(_OUTSIDE))
        p.fillRect(int(hi_px), oy, max(0, int(ox + w - hi_px)), h, QColor(_OUTSIDE))

        if self._hist is not None:
            # Solid and DARKER than either ground, so the data reads as a
            # silhouette cut out of the band rather than as a faint wash on it.
            # It was BORDER #3c4046 at alpha 70 over BG_0, which against the
            # band's amber lift left the shape barely discernible.
            fill = QColor(_DATA)
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
        p.drawRect(int(lo_px), oy, max(1, int(hi_px - lo_px)), h)

        p.setPen(QPen(QColor(_ACCENT), 2))
        for x in (lo_px, hi_px):
            p.drawLine(int(x), oy, int(x),
                       int(oy + h + _STRIP_GAP + self.STRIP_H + _STRIP_GAP))

        strip_y = oy + h + _STRIP_GAP
        ramp = QLinearGradient(float(ox), 0.0, float(ox + w), 0.0)
        ramp.setColorAt(0.0, QColor(0, 0, 0))
        ramp.setColorAt(1.0, QColor(255, 255, 255))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ramp)
        p.drawRect(ox, int(strip_y), w, self.STRIP_H)

        # The grab handles. Two amber hairlines told the user nothing — the
        # caption said "drag the two handles" and there was nothing that looked
        # like one. Shaped like the before/after divider's knob on purpose, so
        # the gesture is recognisable from a control they have already used.
        r = _KNOB_PX / 2.0
        for which in ("lo", "hi"):
            c = self.knob_center(which)
            p.setPen(QPen(QColor(_ACCENT), 2))
            p.setBrush(QColor(BG_0))
            p.drawEllipse(c, r, r)
            # Two small arrows, so it reads as "drag me sideways" rather than
            # as a dot someone left on the axis.
            p.setPen(QPen(QColor(_ACCENT), 1.5))
            for direction in (-1, 1):
                tip = direction * (r - 2.0)
                p.drawLine(QPointF(c.x() + tip, c.y()),
                           QPointF(c.x() + tip - direction * 3.2, c.y() - 3.2))
                p.drawLine(QPointF(c.x() + tip, c.y()),
                           QPointF(c.x() + tip - direction * 3.2, c.y() + 3.2))
