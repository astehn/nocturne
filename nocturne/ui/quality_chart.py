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
from statistics import median
from typing import Callable, Sequence

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QToolTip, QVBoxLayout, QWidget)

from ..stacking.capture_time import full_label
from ..stacking.nights import night_key, night_label
from . import theme

# The plot alone; the caption line above it is ChartPanel's.
CHART_HEIGHT = 70
# Any gap WITHIN a night is drawn as at most this — unchanged, and it still
# applies there (his own request, Ruling R11, kept the within-night rule).
# Between two nights the axis instead reserves a FIXED PIXEL width
# (NIGHT_GAP_PX, below): on a true time axis his Sh2-108 folder's two nights
# — the 21st, and the 26th into the 27th — would put a night days of nothing
# on the same axis as ten-minute frames, so GAP_CAP alone used to leave the
# boundary's on-screen width wandering with however many minutes the real
# gap happened to be capped to, relative to whatever else was on the chart.
# A dashed line in the middle says where one night ends and the next begins,
# with the new night's date beside it (spec 2026-09-28 §9.5).
GAP_CAP = timedelta(minutes=20)
# The width of a night boundary, in real pixels, whatever the actual time
# gap was — his own request, Ruling R11 (2026-09-28): "enough for the dashed
# line", not measured further. Reserved out of the plot's width before the
# within-night, time-proportional part is laid out (see `_avail`/`_px`), so
# resizing the window changes every night's own width but never the gap's.
NIGHT_GAP_PX = 24.0
# The trend line's two smoothing windows, in frames (Ruling R12, 2026-09-28,
# his own real-window try on NGC 6995 and IC 1805): a single running median
# over 9 (round 1) read as dead straight even through a visible cluster of
# rejected frames — a value only needs to be a MINORITY of its window to be
# swallowed by a median, and a cluster of up to 4 frames still is one in a
# window that wide. Two stages fix it: a MEDIAN of 5 first (so a cluster of
# 3 is already a majority, 3 of 5, and survives, while any lone frame, 1 of
# 5, cannot), then a MEAN of the median's own output, which turns its sharp
# plateau into a genuinely gentle rise.
#
# The mean window was tuned on synthetic nights shaped like his real
# sessions (scratchpad/finalC/tune_trend.py; renders saved as
# chart_steady.png — 60 frames at 2.2-2.4 px with two single outliers — and
# chart_clusters.png — an IC 1805-like 400 frames/2 h at 2.2 px with 9
# clusters of 2-5 frames at 2.5-2.6 px). All of 5, 7 and 9 left a single
# outlier at exactly zero effect on the line either way (the median stage
# alone already erases it); a fixed +0.3 px, 4-frame cluster's peak rise was
# 0.24 px at mean=5, 0.17 px at mean=7, 0.13 px at mean=9. At mean=5 the
# render shows a sharp triangular spike, barely gentler than round 1's
# plateau; at mean=9 the rise flattens enough to start blurring his smaller
# 2-3 frame clusters into the noise floor. 7 is the middle ground the
# renders back: still a visibly rounded, gentle bump, comfortably clear of
# the 0.1 px floor a genuine cluster must clear.
TREND_MEDIAN_WINDOW = 5
TREND_MEAN_WINDOW = 7
# The FWHM scale's minimum height (Ruling R12): centred on the data, so a
# steady night — his common case — is not blown up edge-to-edge by its own
# quantisation noise. 0.5 px is his own figure (final-fix.md, round 2).
MIN_FWHM_SPAN = 0.5
KEPT_COLOUR = theme.ACCENT
# Amber, as the mockup draws it. The list DIMS a rejected row; a dimmed dot on
# a dark strip would vanish, which is the opposite of the point.
REJECTED_COLOUR = theme.WARNING
# Moved to rejected/: out of this stack and the decision already acted on, so
# no longer amber's "still your call" — but kept, faint, as the record of the
# night (Andreas, 2026-10-01: his VdB 141, 347 moved after conditions turned).
MOVED_COLOUR = theme.TEXT_FAINT
CURRENT_COLOUR = theme.TEXT
# Fix round 1 (Ruling R5): TEXT_FAINT at 9 px measured 2.44:1 on BG_2 — dimmer
# and smaller than any other secondary text in the app. TEXT_DIM at 11 px
# matches the app's own floor for secondary text (QLabel#optionGroupTitle and
# friends, theme.py).
AXIS_COLOUR = theme.TEXT_DIM
RING_RADIUS = 5.0
NOTE_TIME = "FWHM over the session — ● rejected"
NOTE_NO_TIME = "FWHM in file-name order (some frames have no capture time) — ● rejected"
NOTE_MOVED = "  ● moved"          # appended only while a moved frame is plotted
HIDE_TEXT = "▾ Hide chart"
SHOW_TEXT = "▸ Show chart"
# Below this much usable screen height (the dialogs' _available_height) the
# chart starts folded, for that window only. Spec 2026-09-28 §2.4 and §8: on a
# short screen it starts folded, and the 1280×800 floor leaves 740. The line
# is the spec's, not a measurement: 800 also folds it on a 1440×900 screen
# with the Dock showing (about 745) and leaves it open on anything taller.
CHART_ROOM_MIN = 800
# _LEFT holds the FWHM values, _BOTTOM the clock times. _BOTTOM grew with the
# 11 px axis font (fix round 1): its line height is 13 px against 9 px's 11,
# and the old 14 px band clipped descenders.
_LEFT, _RIGHT, _TOP, _BOTTOM = 30.0, 8.0, 6.0, 16.0
_AXIS_PX = 11
_AXIS_LABEL_H = 14.0                                    # the FWHM label box's own height
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


def _running(values: Sequence[float], breaks: Sequence[int], window: int,
            agg: Callable[[Sequence[float]], float]) -> list[float]:
    """A running `agg` (median or mean) over `values`, one per value, in
    order. `breaks` are the indices where a new night starts (never 0): the
    window never reaches across one — the polyline already breaks there —
    so it narrows near a night's own ends instead of borrowing another
    night's values."""
    if not values:
        return []
    bounds = [0, *sorted(breaks), len(values)]
    half = window // 2
    out: list[float] = []
    for s, e in zip(bounds, bounds[1:]):
        for idx in range(s, e):
            out.append(agg(values[max(s, idx - half):min(e, idx + half + 1)]))
    return out


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def trend_values(values: Sequence[float], breaks: Sequence[int] = (),
                 median_window: int = TREND_MEDIAN_WINDOW,
                 mean_window: int = TREND_MEAN_WINDOW) -> list[float]:
    """The trend line's own FWHM at each plotted point (Ruling R12,
    2026-09-28): a fair trend on a noisy night without following every
    wobble, which a raw point-to-point line does — but without erasing a
    real CLUSTER of several rejected frames either, which a single wide
    median (round 1's TREND_WINDOW = 9) did: a value only needs to be a
    minority of its window to be swallowed by a median, and a wide enough
    window makes a real cluster of several a minority too.

    Two stages: a narrow running MEDIAN (drops a lone odd frame outright,
    since one frame is always a minority of 5 or more) followed by a
    running MEAN of the median's own output (turns its sharp plateau at a
    surviving cluster into the "gentle rise" he asked for). Both stages
    share the same per-night `breaks` and the same edge-narrowing window,
    so neither ever reaches across a night boundary. Pure (no Qt), so it is
    tested directly, without a widget."""
    med = _running(values, breaks, median_window, median)
    return _running(med, breaks, mean_window, _mean)


def note_html(note: str) -> str:
    """The caption with each "●" in the colour of the dots it names — the
    legend must be the colour the chart paints, not the caption's grey."""
    parts = note.split("●")
    out = html.escape(parts[0])
    for part in parts[1:]:
        colour = MOVED_COLOUR if part.lstrip().startswith("moved") else REJECTED_COLOUR
        out += f'<span style="color:{colour}">●</span>{html.escape(part)}'
    return out


class QualityChart(QWidget):
    point_clicked = Signal(int)          # source row
    points_changed = Signal()            # after every refresh: ChartPanel shows or hides

    def __init__(self, describe: Callable[[object], str],
                 is_rejected: Callable[[object], bool],
                 shown: Callable[[object], bool] | None = None, parent=None,
                 is_moved: Callable[[object], bool] | None = None) -> None:
        super().__init__(parent)
        self._describe = describe
        self._is_rejected = is_rejected
        self._is_moved = is_moved or (lambda _s: False)
        # Which frames are drawn at all: an unticked night is left out
        # (spec 2026-09-28 §9.2, §9.5), and the axis closes up behind it.
        self._shown = shown or (lambda _s: True)
        self._stats: list = []
        # The list's own frames (rows 0..n-1, which the list and clicks use),
        # then — drawing only — frames moved to rejected/ in an earlier session,
        # rebuilt from the move record (set_history). `_stats` is both, in
        # that order, rebuilt on every refresh.
        self._list: list = []
        self._history: list = []
        self._rows: list[int] = []
        self._x: list[float] = []
        # Which night-segment each row of `_rows`/`_x` belongs to, 0-based in
        # plot order — how many fixed-pixel night gaps (NIGHT_GAP_PX) sit to
        # its left. Parallel to `_rows`/`_x`.
        self._seg: list[int] = []
        self._timed = True
        self._current = -1
        # Where each night starts, as (index into _rows, its date) — empty
        # unless the plotted frames span two nights or more.
        self._night_starts: list[tuple[int, str]] = []
        self.setFixedHeight(CHART_HEIGHT)
        # Never widens the dialog: its width is whatever the dialog has.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    # --- data ---
    def set_frames(self, stats: list) -> None:
        self._list = stats
        self.refresh()

    def set_history(self, frames: list) -> None:
        """Frames moved to rejected/ before this session, from the move
        record: drawn grey, never rows of the list (Andreas, 2026-10-01 — a
        reopened folder lost the end of its night from the chart)."""
        self._history = list(frames)
        self.refresh()

    def _is_history(self, row: int) -> bool:
        return row >= len(self._list)

    def refresh(self) -> None:
        """Re-read the list: after a grade, a re-judge, or frames moved."""
        # A frame moved THIS session is a list row already; never draw it twice.
        # By full path: a frame moved this session already points into
        # rejected/, and two added folders may hold the same names.
        listed = {os.path.abspath(s.path) for s in self._list}
        self._stats = list(self._list) + [
            h for h in self._history if os.path.abspath(h.path) not in listed]
        rows = [i for i, s in enumerate(self._stats) if plottable(s) and self._shown(s)]
        # One frame without a time and the whole axis is file-name order: a
        # half-timed axis would put the timeless frames somewhere false.
        self._timed = all(self._stats[i].captured is not None for i in rows)
        if self._timed:
            rows.sort(key=lambda i: self._stats[i].captured)
            keys = [night_key(self._stats[i]) for i in rows]
            breaks = [k for k in range(1, len(rows)) if keys[k] != keys[k - 1]]
            xs, seg = [0.0], [0]
            for k in range(1, len(rows)):
                if k in breaks:
                    # A night boundary carries no virtual time (Ruling R11,
                    # 2026-09-28): its own fixed pixel width is reserved at
                    # paint/geometry time instead (`_avail`/`_px`), so it
                    # never competes with GAP_CAP for the same budget.
                    xs.append(xs[-1])
                    seg.append(seg[-1] + 1)
                else:
                    a, b = rows[k - 1], rows[k]
                    gap = self._stats[b].captured - self._stats[a].captured
                    xs.append(xs[-1] + min(gap, GAP_CAP).total_seconds())
                    seg.append(seg[-1])
            self._night_starts = self._label_starts(keys, breaks)
        else:
            rows.sort(key=lambda i: os.path.basename(self._stats[i].path))
            xs = [float(k) for k in range(len(rows))]
            seg = [0] * len(rows)
            self._night_starts = []
        span = xs[-1] if len(xs) > 1 and xs[-1] > 0 else 1.0
        self._rows = rows
        self._x = [x / span for x in xs] if rows else []
        self._seg = seg
        self.update()
        self.points_changed.emit()

    @staticmethod
    def _label_starts(keys: list, breaks: list[int]) -> list[tuple[int, str]]:
        starts = [0, *breaks]
        if len(starts) < 2:
            return []
        with_year = len({keys[k].year for k in starts}) > 1
        return [(k, night_label(keys[k], with_year)) for k in starts]

    def _gap_px_total(self) -> float:
        """How much of the plot's width the night boundaries reserve, before
        the time-proportional part is laid out."""
        return max(0, len(self._night_starts) - 1) * NIGHT_GAP_PX if self._night_starts else 0.0

    def _avail(self, r: QRectF) -> float:
        return max(1.0, r.width() - self._gap_px_total())

    def _px(self, idx: int, r: QRectF, avail: float) -> float:
        """The pixel x of the idx-th plotted point (an index into `_rows`/
        `_x`/`_seg`): its within-night share of `avail`, plus one
        NIGHT_GAP_PX for every night boundary to its left."""
        return r.left() + self._x[idx] * avail + self._seg[idx] * NIGHT_GAP_PX

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
        note = NOTE_TIME if self._timed else NOTE_NO_TIME
        stats = [self._stats[i] for i in self._rows]
        if any(self._is_moved(s) for s in stats):
            if any(self._is_rejected(s) and not self._is_moved(s) for s in stats):
                note += NOTE_MOVED
            else:
                # Every reject moved: no amber dot left to name.
                note = note.replace("● rejected", NOTE_MOVED.strip())
        return note

    def plotted(self) -> list[tuple[int, float]]:
        return list(zip(self._rows, self._x))

    def point_colour(self, row: int) -> str:
        s = self._stats[row]
        if self._is_moved(s):
            return MOVED_COLOUR
        return REJECTED_COLOUR if self._is_rejected(s) else KEPT_COLOUR

    # --- geometry ---
    def _plot_rect(self) -> QRectF:
        return QRectF(_LEFT, _TOP, max(1.0, self.width() - _LEFT - _RIGHT),
                      max(1.0, self.height() - _TOP - _BOTTOM))

    def _trend_fwhm(self) -> list[float]:
        """The smoothed FWHM at each plotted point, in `_rows` order — pure
        values, no pixel geometry. Feeds both the scale (`_value_range`,
        Ruling R12: the line's own excursions must fit) and the line itself
        (`_trend_line`)."""
        if not self._rows:
            return []
        breaks = [k for k, _label in self._night_starts if k > 0]
        values = [self._stats[i].fwhm for i in self._rows]
        return trend_values(values, breaks)

    def _value_range(self) -> tuple[float, float]:
        """The FWHM scale: the KEPT dots plus wherever the trend line
        reaches, padded 5%, never narrower than MIN_FWHM_SPAN (Ruling R12,
        2026-09-28) — his real-window try on NGC 6995 read the trend as
        dead flat partly because a handful of REJECTED outliers, included in
        the old min/max, squeezed every kept dot into a sliver at the
        bottom. A rejected dot outside this range is drawn pinned at the
        plot's edge instead (`_y`), never dropped and never allowed to
        stretch the scale."""
        kept = [self._stats[i].fwhm for i in self._rows
               if not self._is_rejected(self._stats[i])]
        base = kept or [self._stats[i].fwhm for i in self._rows]
        values = base + self._trend_fwhm()
        lo, hi = min(values), max(values)
        span = hi - lo
        if span < MIN_FWHM_SPAN:
            mid = (lo + hi) / 2.0
            lo, hi = mid - MIN_FWHM_SPAN / 2.0, mid + MIN_FWHM_SPAN / 2.0
            span = MIN_FWHM_SPAN
        pad = span * 0.05
        return lo - pad, hi + pad

    def _y(self, value: float, r: QRectF, lo: float, hi: float) -> float:
        # Softer is HIGHER, as the mockup draws the soft night: worse is up.
        # Clamped to the plot rect (Ruling R12): a rejected outlier outside
        # the range is pinned at the edge, not dropped and not allowed to
        # drag the range back out to fit it.
        y = r.bottom() - (value - lo) / (hi - lo) * r.height()
        return min(max(y, r.top()), r.bottom())

    def _positions(self) -> list[tuple[int, QPointF]]:
        if not self._rows:
            return []
        r = self._plot_rect()
        avail = self._avail(r)
        lo, hi = self._value_range()
        return [(i, QPointF(self._px(idx, r, avail),
                            self._y(self._stats[i].fwhm, r, lo, hi)))
                for idx, i in enumerate(self._rows)]

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

    def _trend_line(self, pts: list[tuple[int, QPointF]]) -> list[QPointF]:
        """The line's own y at each dot's x: two-stage smoothed FWHM (Ruling
        R12, 2026-09-28) — the dots (`pts`) keep their real values and real
        x; only what connects them is smoothed."""
        if not pts:
            return []
        r = self._plot_rect()
        lo, hi = self._value_range()
        return [QPointF(q.x(), self._y(m, r, lo, hi))
                for (_i, q), m in zip(pts, self._trend_fwhm())]

    # --- the axes ---
    def _axis_font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(_AXIS_PX)
        return font

    def fwhm_labels(self) -> list[tuple[QRectF, str]]:
        """The plot's own top and bottom FWHM, left of the plot and level
        with where they are drawn — the scale's own ends (Ruling R12,
        2026-09-28), not necessarily the rawest kept or rejected frame:
        since the range no longer simply spans every plotted value, a label
        must say what the AXIS reads there, not what one extreme frame
        happened to measure. One value when the range rounds to one."""
        if not self._rows:
            return []
        r = self._plot_rect()
        lo, hi = self._value_range()
        out, seen = [], set()
        for v in (hi, lo):
            text = f"{v:.1f}"
            if text in seen:
                continue
            seen.add(text)
            y = min(max(self._y(v, r, lo, hi) - _AXIS_LABEL_H / 2, 0.0),
                    self.height() - _BOTTOM - _AXIS_LABEL_H)
            # M1 (final fix wave, 2026-09-28): the first kept frame sits at
            # the plot's own left edge (_LEFT), and Task 2's auto-preview
            # rings it after every grade -- so a label box reaching all the
            # way to _LEFT - 4 put the ring's own radius through the text.
            # End short of the ring instead.
            out.append((QRectF(0.0, y, _LEFT - RING_RADIUS - 2.0, _AXIS_LABEL_H), text))
        return out

    def night_lines(self) -> list[float]:
        """The x of each dashed line: halfway across the fixed-pixel gap
        (NIGHT_GAP_PX) between one night's last frame and the next night's
        first."""
        if not self._night_starts:
            return []
        r = self._plot_rect()
        avail = self._avail(r)
        return [(self._px(k - 1, r, avail) + self._px(k, r, avail)) / 2
                for k, _label in self._night_starts if k > 0]

    def date_labels(self) -> list[tuple[QRectF, str]]:
        """Each night's date in the band under the plot: the first at the
        plot's left edge, the others just right of their dashed line — where
        there is room there, never pulled back across it. They
        outrank the clock times there (time_labels steps around them). Two
        that would touch — a night of a few frames is a few pixels wide —
        keep the date of the wider night, never one drawn over the other."""
        if not self._night_starts:
            return []
        r = self._plot_rect()
        fm = QFontMetrics(self._axis_font())
        anchors = [r.left()] + self.night_lines()
        ends = self.night_lines() + [r.right()]
        kept: list[tuple[QRectF, str, float]] = []
        for n, (anchor, end, (_k, text)) in enumerate(zip(anchors, ends, self._night_starts)):
            w = fm.horizontalAdvance(text) + 4.0
            if n and anchor + 2.0 + w > self.width():
                # Pulled back to fit, a short last night's date sat LEFT of
                # its own line and read as the night before's. Left out
                # instead: the chips and a hover still say it.
                continue
            left = min(anchor + 2.0, self.width() - w)
            rect = QRectF(left, self.height() - _BOTTOM + 1.0, w, _BOTTOM - 1.0)
            if kept and left < kept[-1][0].right() + _LABEL_GAP:
                if end - anchor <= kept[-1][2]:
                    continue
                kept.pop()      # the wider night's date wins the place
            kept.append((rect, text, end - anchor))
        return [(rect, text) for rect, text, _span in kept]

    def time_labels(self) -> list[tuple[QRectF, str]]:
        """A few clock times under the plot, each at a real frame's x. Never
        overlapping and never past either edge, however many frames or however
        narrow the chart: a label that would come within _LABEL_GAP of the one
        before it, or of a night's date, is left out. None without capture
        times."""
        if not self._timed or len(self._rows) < 2:
            return []
        r = self._plot_rect()
        avail = self._avail(r)
        fm = QFontMetrics(self._axis_font())
        dates = [rect for rect, _t in self.date_labels()]
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
            cx = self._px(i, r, avail)
            left = min(max(cx - w / 2, 0.0), self.width() - w)
            if left < last_right + _LABEL_GAP:
                continue
            if any(left < d.right() + _LABEL_GAP and left + w + _LABEL_GAP > d.left()
                   for d in dates):
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
            if row >= 0 and not self._is_history(row):
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
        for rect, text in self.date_labels():
            p.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        r = self._plot_rect()
        p.setPen(QPen(QColor(AXIS_COLOUR), 1.0, Qt.PenStyle.DashLine))
        for x in self.night_lines():
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        pts = self._positions()
        if len(pts) >= 2:
            p.setPen(QPen(QColor(KEPT_COLOUR), 1.0))
            trend = self._trend_line(pts)
            breaks = {k for k, _label in self._night_starts if k > 0}
            seg_start = 0
            for k in range(1, len(pts) + 1):
                if k == len(pts) or k in breaks:
                    if k - seg_start >= 2:
                        p.drawPolyline(QPolygonF(trend[seg_start:k]))
                    seg_start = k
        p.setPen(Qt.PenStyle.NoPen)
        # Moved first, faint, underneath everything; rejected last, so a reject
        # still your call is never hidden under a kept neighbour.
        def layer(t):
            s = self._stats[t[0]]
            return 0 if self._is_moved(s) else (2 if self._is_rejected(s) else 1)
        for i, q in sorted(pts, key=layer):
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
        note = self.chart.note()
        if self._folded:
            # M7 (final fix wave, 2026-09-28): folded, the dots themselves
            # are not drawn — the "● rejected" legend describing them was
            # left dangling with nothing on screen to point at.
            note = note.split(" — ")[0]
        self.caption.setText(note_html(note))
