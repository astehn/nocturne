"""FWHM over the session, full width above the frame list (spec 2026-09-28
§2.4; calm-layout-2 mockup, card C): a caption and "▾ Hide chart" on one line,
the plot under it with a few clock times and two FWHM values. Andreas,
2026-09-28, of the old 730 × 60 px strip under the list: liked, but "too small
to be useful". Shared: Stack and Ha/OIII both get it through FrameBrowser.

Painted, not matplotlib: a strip of dots that repaints as the cursor moves
through up to 2,500 frames, and matplotlib is a known hazard in the shipped
app. Rows are SOURCE rows, as everywhere in FrameBrowser's API.
"""
from __future__ import annotations

import bisect
import html
import os
from datetime import timedelta
from typing import Callable

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QToolTip, QVBoxLayout, QWidget)

from ..stacking.capture_time import full_label
from . import theme

# The plot alone; the caption line above it is ChartPanel's.
CHART_HEIGHT = 70
# Any gap between two subs is drawn as at most this. His Sh2-108 folder holds
# two nights — the 21st, and the 26th into the 27th; on a true time axis each
# night would be a sliver a few pixels wide between days of nothing. Delivery C
# draws a dashed line where two nights meet.
GAP_CAP = timedelta(minutes=20)
KEPT_COLOUR = theme.ACCENT
# Amber, as the mockup draws it. The list DIMS a rejected row; a dimmed dot on
# a dark strip would vanish, which is the opposite of the point.
REJECTED_COLOUR = theme.WARNING
CURRENT_COLOUR = theme.TEXT
AXIS_COLOUR = theme.TEXT_FAINT
RING_RADIUS = 5.0
NOTE_TIME = "FWHM over the session — ● rejected"
NOTE_NO_TIME = "FWHM in file-name order (some frames have no capture time) — ● rejected"
HIDE_TEXT = "▾ Hide chart"
SHOW_TEXT = "▸ Show chart"
# Below this much usable screen height (the dialogs' _available_height) the
# chart starts folded, for that window only. Spec 2026-09-28 §2.4 and §8: on a
# short screen it starts folded, and the 1280×800 floor leaves 740. The line
# is the spec's, not a measurement: 800 also folds it on a 1440×900 screen
# with the Dock showing (about 745) and leaves it open on anything taller.
CHART_ROOM_MIN = 800
# _LEFT holds the FWHM values, _BOTTOM the clock times.
_LEFT, _RIGHT, _TOP, _BOTTOM = 30.0, 8.0, 6.0, 14.0
_AXIS_PX = 9
_DOT = 2.5
_HIT = 6.0                                              # a click this close picks the dot
# Clock times sit at least this far apart, so labels never touch; a narrow
# chart simply gets fewer of them (2 at the least, 6 at the most).
TIME_LABEL_SPACING = 110
_TIME_LABELS_MAX = 6
_LABEL_GAP = 6.0


def plottable(s) -> bool:
    """Measured, with stars to measure: the chart can place it."""
    return not s.error and s.star_count > 0 and s.fwhm > 0


def note_html(note: str) -> str:
    """The caption with its "●" in REJECTED_COLOUR — the legend must be the
    colour of the dots the chart paints, not the caption's grey."""
    before, dot, after = note.partition("●")
    if not dot:
        return html.escape(note)
    return (f'{html.escape(before)}<span style="color:{REJECTED_COLOUR}">●</span>'
            f"{html.escape(after)}")


class QualityChart(QWidget):
    point_clicked = Signal(int)          # source row
    points_changed = Signal()            # after every refresh: ChartPanel shows or hides

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
        # Never widens the dialog: its width is whatever the dialog has.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

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
        self.update()
        self.points_changed.emit()

    def point_count(self) -> int:
        return len(self._rows)

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

    def _value_range(self) -> tuple[float, float]:
        """The FWHM scale, padded 5% so no dot sits on the edge."""
        values = [self._stats[i].fwhm for i in self._rows]
        lo, hi = min(values), max(values)
        pad = (hi - lo) * 0.05 if hi > lo else 0.5
        return lo - pad, hi + pad

    def _y(self, value: float, r: QRectF, lo: float, hi: float) -> float:
        # Softer is HIGHER, as the mockup draws the soft night: worse is up.
        return r.bottom() - (value - lo) / (hi - lo) * r.height()

    def _positions(self) -> list[tuple[int, QPointF]]:
        if not self._rows:
            return []
        r = self._plot_rect()
        lo, hi = self._value_range()
        return [(i, QPointF(r.left() + x * r.width(),
                            self._y(self._stats[i].fwhm, r, lo, hi)))
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

    # --- the axes ---
    def _axis_font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(_AXIS_PX)
        return font

    def fwhm_labels(self) -> list[tuple[QRectF, str]]:
        """The softest and the sharpest frame's FWHM, left of the plot and
        level with where they are drawn. One value when every frame is alike."""
        if not self._rows:
            return []
        r = self._plot_rect()
        lo, hi = self._value_range()
        values = [self._stats[i].fwhm for i in self._rows]
        out, seen = [], set()
        for v in (max(values), min(values)):
            text = f"{v:.1f}"
            if text in seen:
                continue
            seen.add(text)
            y = min(max(self._y(v, r, lo, hi) - 6.0, 0.0), self.height() - _BOTTOM - 12.0)
            out.append((QRectF(0.0, y, _LEFT - 4.0, 12.0), text))
        return out

    def time_labels(self) -> list[tuple[QRectF, str]]:
        """A few clock times under the plot, each at a real frame's x. Never
        overlapping and never past either edge, however many frames or however
        narrow the chart: a label that would come within _LABEL_GAP of the one
        before it is left out. None without capture times."""
        if not self._timed or len(self._rows) < 2:
            return []
        r = self._plot_rect()
        fm = QFontMetrics(self._axis_font())
        want = max(2, min(_TIME_LABELS_MAX, int(r.width() // TIME_LABEL_SPACING) + 1))
        out: list[tuple[QRectF, str]] = []
        last_right = -1e9
        for k in range(want):
            target = k / (want - 1)
            i = min(bisect.bisect_left(self._x, target), len(self._x) - 1)
            if i > 0 and abs(self._x[i - 1] - target) <= abs(self._x[i] - target):
                i -= 1
            text = f"{self._stats[self._rows[i]].captured.astimezone():%H:%M}"
            w = fm.horizontalAdvance(text) + 4.0
            cx = r.left() + self._x[i] * r.width()
            left = min(max(cx - w / 2, 0.0), self.width() - w)
            if left < last_right + _LABEL_GAP:
                continue
            out.append((QRectF(left, self.height() - _BOTTOM + 1.0, w, _BOTTOM - 1.0), text))
            last_right = left + w
        return out

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
        p.setFont(self._axis_font())
        p.setPen(QColor(AXIS_COLOUR))
        for rect, text in self.fwhm_labels():
            p.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
        for rect, text in self.time_labels():
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
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


class ChartPanel(QWidget):
    """The chart and its fold: the caption and "▾ Hide chart" on one line, the
    plot under it. Hidden while there are fewer than two points to draw;
    folded, only the caption line stays, with "▸ Show chart"."""

    folded_changed = Signal(bool)        # the user's click only — the one to save

    def __init__(self, chart: QualityChart, parent=None) -> None:
        super().__init__(parent)
        self.chart = chart
        self.caption = QLabel("")
        self.caption.setObjectName("stepExplainer")
        self.caption.setTextFormat(Qt.TextFormat.RichText)
        self.fold_btn = QPushButton(HIDE_TEXT)
        self.fold_btn.setObjectName("linkButton")
        self.fold_btn.setFlat(True)
        self.fold_btn.clicked.connect(self._on_click)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self.caption)
        head.addStretch(1)
        head.addWidget(self.fold_btn)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addLayout(head)
        col.addWidget(chart)
        self._folded = False
        self._user_set = False
        chart.points_changed.connect(self._sync)
        self._sync()

    def is_folded(self) -> bool:
        return self._folded

    def user_set(self) -> bool:
        """True once he has clicked the fold in this window: the screen's own
        fold leaves it alone from then on, as it does "details ▸"."""
        return self._user_set

    def set_folded(self, folded: bool) -> None:
        """A fold the DIALOG makes — his saved choice, or the screen's. Emits
        nothing: only his click is saved."""
        self._folded = folded
        self._sync()

    def _on_click(self) -> None:
        self._user_set = True
        self.set_folded(not self._folded)
        self.folded_changed.emit(self._folded)

    def _sync(self) -> None:
        has = self.chart.point_count() >= 2
        self.setVisible(has)
        self.chart.setVisible(has and not self._folded)
        self.fold_btn.setText(SHOW_TEXT if self._folded else HIDE_TEXT)
        self.caption.setText(note_html(self.chart.note()))
