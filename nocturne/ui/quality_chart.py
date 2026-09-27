"""FWHM over the session, under the frame list (spec 2026-09-27 decision 4.6;
the list-preview mockup: a blue line, amber rejected dots, a caption top-left).
Shared: Stack and Ha/OIII both get it through FrameBrowser.

Painted, not matplotlib: a strip of dots that repaints as the cursor moves
through up to 2,500 frames, and matplotlib is a known hazard in the shipped
app. Rows are SOURCE rows, as everywhere in FrameBrowser's API.
"""
from __future__ import annotations

import os
from datetime import timedelta
from typing import Callable

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ..stacking.capture_time import full_label
from . import theme

CHART_HEIGHT = 60
# Any gap between two subs is drawn as at most this. His Sh2-108 folder holds
# nights on the 21st, 26th and 27th; on a true time axis each night would be a
# sliver a few pixels wide between days of nothing. Delivery C draws a dashed
# line where two nights meet.
GAP_CAP = timedelta(minutes=20)
KEPT_COLOUR = theme.ACCENT
# Amber, as the mockup draws it. The list DIMS a rejected row; a dimmed dot on
# a dark strip would vanish, which is the opposite of the point.
REJECTED_COLOUR = theme.WARNING
CURRENT_COLOUR = theme.TEXT
RING_RADIUS = 5.0
NOTE_TIME = "FWHM over the session — ● rejected"
NOTE_NO_TIME = "FWHM in file-name order (some frames have no capture time) — ● rejected"
_LEFT, _RIGHT, _TOP, _BOTTOM = 6.0, 6.0, 16.0, 6.0     # _TOP leaves the caption its line
_DOT = 2.5
_HIT = 6.0                                              # a click this close picks the dot


def plottable(s) -> bool:
    """Measured, with stars to measure: the chart can place it."""
    return not s.error and s.star_count > 0 and s.fwhm > 0


class QualityChart(QWidget):
    point_clicked = Signal(int)          # source row

    def __init__(self, describe: Callable[[object], str],
                 is_rejected: Callable[[object], bool], parent=None) -> None:
        super().__init__(parent)
        self._describe = describe
        self._is_rejected = is_rejected
        self._stats: list = []
        self._rows: list[int] = []
        self._x: list[float] = []
        self._timed = True
        self._current = -1
        self.setFixedHeight(CHART_HEIGHT)
        # Never widens the list: its width is its columns' (spec §2.4.7).
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.hide()

    # --- data ---
    def set_frames(self, stats: list) -> None:
        self._stats = stats
        self.refresh()

    def refresh(self) -> None:
        """Re-read the list: after a grade, a re-judge, or frames moved."""
        rows = [i for i, s in enumerate(self._stats) if plottable(s)]
        # One frame without a time and the whole axis is file-name order: a
        # half-timed axis would put the timeless frames somewhere false.
        self._timed = all(self._stats[i].captured is not None for i in rows)
        if self._timed:
            rows.sort(key=lambda i: self._stats[i].captured)
            xs = [0.0]
            for a, b in zip(rows, rows[1:]):
                gap = self._stats[b].captured - self._stats[a].captured
                xs.append(xs[-1] + min(gap, GAP_CAP).total_seconds())
        else:
            rows.sort(key=lambda i: os.path.basename(self._stats[i].path))
            xs = [float(k) for k in range(len(rows))]
        span = xs[-1] if len(xs) > 1 and xs[-1] > 0 else 1.0
        self._rows = rows
        self._x = [x / span for x in xs] if rows else []
        self.setVisible(len(rows) >= 2)
        self.update()

    def set_current(self, row: int) -> None:
        self._current = row
        self.update()

    def current_row(self) -> int:
        return self._current

    def is_timed(self) -> bool:
        return self._timed

    def note(self) -> str:
        return NOTE_TIME if self._timed else NOTE_NO_TIME

    def plotted(self) -> list[tuple[int, float]]:
        return list(zip(self._rows, self._x))

    def point_colour(self, row: int) -> str:
        return REJECTED_COLOUR if self._is_rejected(self._stats[row]) else KEPT_COLOUR

    # --- geometry ---
    def _plot_rect(self) -> QRectF:
        return QRectF(_LEFT, _TOP, max(1.0, self.width() - _LEFT - _RIGHT),
                      max(1.0, self.height() - _TOP - _BOTTOM))

    def _positions(self) -> list[tuple[int, QPointF]]:
        if not self._rows:
            return []
        r = self._plot_rect()
        values = [self._stats[i].fwhm for i in self._rows]
        lo, hi = min(values), max(values)
        pad = (hi - lo) * 0.05 if hi > lo else 0.5
        lo, hi = lo - pad, hi + pad
        # Softer is HIGHER, as the mockup draws the soft night: worse is up.
        return [(i, QPointF(r.left() + x * r.width(),
                            r.bottom() - (self._stats[i].fwhm - lo) / (hi - lo) * r.height()))
                for i, x in zip(self._rows, self._x)]

    def point_pos(self, row: int) -> QPointF | None:
        for i, p in self._positions():
            if i == row:
                return p
        return None

    def row_at(self, pos: QPointF) -> int:
        best, best_d = -1, _HIT * _HIT
        for i, p in self._positions():
            d = (p.x() - pos.x()) ** 2 + (p.y() - pos.y()) ** 2
            if d <= best_d:
                best, best_d = i, d
        return best

    def tooltip_at(self, pos: QPointF) -> str:
        row = self.row_at(pos)
        if row < 0:
            return ""
        s = self._stats[row]
        when = full_label(s.captured) or os.path.basename(s.path)
        return f"{when}\nFWHM {s.fwhm:.2f} px · {self._describe(s)}"

    # --- Qt ---
    def event(self, e) -> bool:
        if e.type() == QEvent.Type.ToolTip:
            text = self.tooltip_at(QPointF(e.pos()))
            if text:
                QToolTip.showText(e.globalPos(), text, self)
            else:
                QToolTip.hideText()
                e.ignore()
            return True
        return super().event(e)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            row = self.row_at(e.position())
            if row >= 0:
                self.point_clicked.emit(row)
                e.accept()
                return
        super().mousePressEvent(e)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.BG_2))
        font = QFont(self.font())
        font.setPixelSize(10)
        p.setFont(font)
        p.setPen(QColor(theme.TEXT_DIM))
        p.drawText(QRectF(_LEFT, 1.0, max(1.0, self.width() - _LEFT - _RIGHT), _TOP - 2),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.note())
        pts = self._positions()
        if len(pts) >= 2:
            p.setPen(QPen(QColor(KEPT_COLOUR), 1.0))
            p.drawPolyline(QPolygonF([q for _i, q in pts]))
        p.setPen(Qt.PenStyle.NoPen)
        # Rejected last, so a reject is never hidden under a kept neighbour.
        for i, q in sorted(pts, key=lambda t: self._is_rejected(self._stats[t[0]])):
            p.setBrush(QColor(self.point_colour(i)))
            p.drawEllipse(q, _DOT, _DOT)
        cur = next((q for i, q in pts if i == self._current), None)
        if cur is not None:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(CURRENT_COLOUR), 1.5))
            p.drawEllipse(cur, RING_RADIUS, RING_RADIUS)
        p.end()
