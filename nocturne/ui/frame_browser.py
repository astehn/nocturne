"""The frame list and its preview, shared by Stack and Ha/OIII.

Both dialogs grade the same subs with the same code, so they must show them the
same way — two hand-built tables had already drifted once (the preview lived
only in Stack). Spec: docs/superpowers/specs/2026-09-27-stack-dialog-design.md
§2.4-2.5 and the list-preview mockup.

The FrameStats objects are the HOST's own list, never copies: `included` on
them is what the stack reads, and a tick here writes it directly.
"""
from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QSize,
                            QSortFilterProxyModel, Qt, Signal)
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QSplitter,
                               QSplitterHandle, QStyle, QStyleOptionHeader,
                               QTableView, QToolButton, QVBoxLayout, QWidget)

from ..stacking.capture_time import full_label, time_label
from . import theme
from .frame_preview import FramePreview
from .frame_preview_controller import FramePreviewController
from .quality_chart import QualityChart

# Round and Bg left the list (spec 2026-09-28 §2.6): they repeated what the
# Verdict already says, and Bg read to three decimals. Both are in every
# cell's tooltip (measures_line).
COL_USE, COL_TIME, COL_STARS, COL_FWHM, COL_VERDICT = range(5)
HEADERS = ("Use", "Time", "Stars", "FWHM", "Verdict")
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
SHOW_ALL, SHOW_KEPT, SHOW_REJECTED = "all", "kept", "rejected"

# What "bigger preview" hides: the measurements. Use stays — it IS the tick, and
# a list you cannot tick from is a list you have to widen again to use.
DETAIL_COLUMNS = (COL_STARS, COL_FWHM)

# Was "Back to the verdicts", which made no sense until pressed (Andreas,
# 2026-09-28; spec §4).
RESET_TEXT = "Reset to suggested"

# The Verdict cell of a frame moved into <folder>/rejected/.
MOVED_TEXT = "In rejected/"

# The divider's hit area. Qt's default on macOS is 1 px of visible line inside a
# few px of target — Andreas, 2026-09-27: "very hard to grab". The spec's floor
# is 10; 12 leaves room for the painted grip to sit centred.
GRIP_WIDTH = 12
# The list's share of the splitter is capped so the preview always gets the
# larger half, whatever the Verdict strings measure (spec §2.4.7). Load-bearing
# at the 1100 px the dialogs open at: with his session's longest verdicts the
# list's natural width (606 px offscreen, 622 cocoa, since _CompactHeader) is
# more than half of it (mutating this to 0.95 fails
# test_every_column_is_on_screen_at_the_width_it_opens). At 1280 the narrower
# columns now fit under half without it.
LIST_MAX_SHARE = 0.45


def is_moved(s) -> bool:
    return bool(getattr(s, "moved", False))


def verdict_text(s) -> str:
    if is_moved(s):
        return MOVED_TEXT
    if s.reason:
        return s.reason
    if s.warning:
        return s.warning
    return "OK"


def verdict_tooltip(s) -> str:
    """The unabbreviated verdict: the cell holds the short form."""
    if is_moved(s):
        why = s.reason_detail or s.reason or "unticked by hand"
        return (f"Moved into the rejected folder ({why}). Move them back to "
                "stack it again.")
    return s.reason_detail or verdict_text(s)


def is_rejected(s) -> bool:
    """What Show Rejected, the Rejected count and the chart's amber all mean —
    one definition, so the three cannot disagree. A frame in rejected/ counts,
    whatever its grader verdict was."""
    return bool(s.reason) or is_moved(s)


def _locked(s) -> bool:
    """Never tickable in: an error frame (nothing downstream filters it back
    out) or a frame in rejected/ (nothing may stack from there)."""
    return bool(s.error) or is_moved(s)


def _tint(s) -> str:
    if is_rejected(s):
        return theme.TEXT_FAINT        # rejected or moved: dimmed
    if s.warning:
        return theme.WARNING           # kept with a warning: amber
    return theme.TEXT


def _display(s, col: int) -> str:
    if col == COL_TIME:
        return time_label(getattr(s, "captured", None))
    if col == COL_STARS:
        return str(s.star_count)
    if col == COL_FWHM:
        return f"{s.fwhm:.1f}"
    if col == COL_VERDICT:
        return verdict_text(s)
    return ""


def measures_line(s) -> str:
    """Every measurement of a frame on one line — the two the list shows and
    the two it no longer does. "Round" is elongation: 1.00 is circular."""
    return (f"Stars {s.star_count} · FWHM {s.fwhm:.2f} px · "
            f"Round {s.elongation:.2f} · Bg {s.background:.3f}")


def _tooltip(s, col: int) -> str:
    if col == COL_USE:
        return ""
    if col == COL_TIME:
        when = full_label(getattr(s, "captured", None))
        name = os.path.basename(s.path)
        return "\n".join(t for t in (name, when, measures_line(s)) if t)
    if col == COL_VERDICT:
        return f"{verdict_tooltip(s)}\n{measures_line(s)}"
    return measures_line(s)


def _sort_key(s, col: int):
    """A key every row of one column can compare against. Frames with no
    capture time sort after the dated ones; the sort is stable, so among
    themselves they keep the grader's order."""
    if col == COL_USE:
        return (0, int(bool(s.included)))
    if col == COL_TIME:
        dt = getattr(s, "captured", None)
        return (1, 0.0) if dt is None else (0, dt.timestamp())
    if col == COL_STARS:
        return (0, s.star_count)
    if col == COL_FWHM:
        return (0, s.fwhm)
    return (0, verdict_text(s))


def _is_checked(value) -> bool:
    # The delegate hands setData a plain int (2), a caller may hand the enum.
    return getattr(value, "value", value) == Qt.CheckState.Checked.value


class FrameTableModel(QAbstractTableModel):
    """One row per graded frame, in the host's order (source rows = indices
    into the host's list, whatever the view's sort)."""

    ticks_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stats: list = []
        self._overrides: dict[int, bool] = {}

    # --- the host's list ---
    def set_frames(self, stats: list) -> None:
        self.beginResetModel()
        self._stats = stats
        self._overrides = {}
        self.endResetModel()

    def frames(self) -> list:
        return self._stats

    def frame(self, row: int):
        return self._stats[row]

    def touched(self) -> set[int]:
        return set(self._overrides)

    def add_frames(self, new_stats: list) -> None:
        """Append frames graded AFTER the fact — Stack's "Move them back"
        merging in subs restored from an earlier session — without
        disturbing a single existing row. `set_frames` would
        clear `_overrides` and re-measure everything already listed, which is
        exactly the bug: a hand tick on an existing frame lived only in
        `_overrides`, so a full reset silently threw it away. Existing rows
        keep their index here, so `_overrides` still points at the same
        frames afterward."""
        if not new_stats:
            return
        first = len(self._stats)
        self.beginInsertRows(QModelIndex(), first, first + len(new_stats) - 1)
        self._stats.extend(new_stats)
        self.endInsertRows()

    def remove_frames(self, predicate) -> None:
        """Drop every frame `predicate(stat)` accepts: a name `move_back`
        could not find anywhere (deleted from rejected/ by hand) must stop
        describing a frame that is nowhere, not go on reading `moved=True`
        against a path that no longer exists.
        Removed highest index first so the row numbers of everything else —
        and so `_overrides`, keyed by row — stay valid throughout."""
        rows = sorted((i for i, s in enumerate(self._stats) if predicate(s)), reverse=True)
        for row in rows:
            self.beginRemoveRows(QModelIndex(), row, row)
            del self._stats[row]
            self._overrides = {(r - 1 if r > row else r): v
                               for r, v in self._overrides.items() if r != row}
            self.endRemoveRows()

    # --- ticks ---
    def set_ticked(self, rows, checked: bool) -> None:
        """A tick the USER made. It is remembered, so a re-judge (Strictness
        moved) does not undo it — the old tables' `_user_touched`.

        An error frame, or one moved into rejected/, can never be ticked IN
        (see `flags`) — Select All must respect the same rule the checkbox
        itself does, or "All" would still smuggle a non-raw/unreadable file
        past it.
        """
        rows = list(rows)
        if not rows:
            return
        changed = False
        for row in rows:
            s = self._stats[row]
            if checked and _locked(s):
                continue
            self._overrides[row] = checked
            if bool(s.included) != checked:
                s.included = checked
                changed = True
        self._emit_rows(min(rows), max(rows))
        if changed:
            self.ticks_changed.emit()

    def revert_to_verdicts(self) -> None:
        """Forget every hand-made tick: the grader's verdict decides again.
        `reason` is non-empty exactly when judge() excluded a frame."""
        self._overrides.clear()
        changed = False
        for s in self._stats:
            want = not s.reason and not is_moved(s)
            if bool(s.included) != want:
                s.included = want
                changed = True
        if self._stats:
            self._emit_rows(0, len(self._stats) - 1)
        if changed:
            self.ticks_changed.emit()

    def reapply_ticks(self) -> None:
        """After the host re-ran judge(): the fresh verdict stands except where
        the user ticked by hand. judge() sets `included` on every usable frame
        — moved ones too — so a locked frame is put back out here, always."""
        for row, checked in self._overrides.items():
            self._stats[row].included = checked
        for s in self._stats:
            if _locked(s):
                s.included = False
        if self._stats:
            self._emit_rows(0, len(self._stats) - 1)

    def _emit_rows(self, first: int, last: int) -> None:
        self.dataChanged.emit(self.index(first, 0),
                              self.index(last, len(HEADERS) - 1))

    # --- QAbstractTableModel ---
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._stats)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (orientation == Qt.Orientation.Horizontal
                and role == Qt.ItemDataRole.DisplayRole):
            return HEADERS[section]
        return None

    def flags(self, index):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        # An error frame (a stacked master, or a sub that couldn't be measured)
        # is never checkable: nothing downstream filters it back out, so a
        # tick reaching one would hand a non-raw or unreadable file straight
        # to the stack.
        if index.column() == COL_USE and not _locked(self._stats[index.row()]):
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        s = self._stats[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.CheckStateRole and col == COL_USE:
            return Qt.CheckState.Checked if s.included else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            return _display(s, col)
        if role == Qt.ItemDataRole.ToolTipRole:
            return _tooltip(s, col)
        if role == Qt.ItemDataRole.ForegroundRole and col != COL_USE:
            return QColor(_tint(s))
        if role == SORT_ROLE:
            return _sort_key(s, col)
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.CheckStateRole or index.column() != COL_USE:
            return False
        self.set_ticked([index.row()], _is_checked(value))
        return True


class FrameFilterProxy(QSortFilterProxyModel):
    """Show All / Kept / Rejected, and any sort.

    Kept/Rejected is the GRADER's verdict, not the tick: filtered on the tick,
    ticking a rejected frame back in would make it vanish from under the
    pointer — and take the preview with it — mid-review.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._show = SHOW_ALL
        self._extra: Callable[[object], bool] | None = None
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)

    def set_show(self, show: str) -> None:
        self.beginFilterChange()
        self._show = show
        self.endFilterChange()

    def show_mode(self) -> str:
        return self._show

    def set_extra_filter(self, accepts: Callable[[object], bool] | None) -> None:
        """A further condition on a frame — delivery C's night toggles."""
        self.beginFilterChange()
        self._extra = accepts
        self.endFilterChange()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        s = self.sourceModel().frame(source_row)
        if self._show == SHOW_KEPT and is_rejected(s):
            return False
        if self._show == SHOW_REJECTED and not is_rejected(s):
            return False
        return self._extra is None or bool(self._extra(s))

    def lessThan(self, left, right) -> bool:
        lk, rk = left.data(SORT_ROLE), right.data(SORT_ROLE)
        if lk[0] != rk[0]:
            # A timeless row's key is tagged 1, a dated one's 0, precisely so
            # it sorts last when ASCENDING. Qt reverses the whole comparison
            # for a descending column by swapping the arguments it hands us,
            # which would otherwise put the timeless row FIRST; invert just
            # this tag comparison to cancel that out, so it stays last either
            # way. Same-tag rows are left to Qt's own reversal, which is what
            # makes every other column behave the way clicking the header
            # twice is supposed to.
            base = lk < rk
            return not base if self.sortOrder() == Qt.SortOrder.DescendingOrder else base
        return lk < rk


class _FrameTable(QTableView):
    """Space ticks the current frame from ANY column. Qt's own Space only
    toggles when the current cell is the checkbox itself, and after a click on
    Time or Verdict it is not."""

    space_pressed = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space and not event.modifiers():
            self.space_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _CompactHeader(QHeaderView):
    """Room for the sort arrow only in the column that shows it.

    With sorting on, Qt reserves the arrow's width — the section's height plus
    a margin — in EVERY section, arrow or not. Measured under cocoa with the
    real stylesheet, 2026-09-27: 29 px a column, 761 px of columns for a list
    capped at 552 px in a 1280 px dialog, so Bg and Verdict sat behind a
    horizontal scrollbar. Without the six unused arrows the list needs 581
    and Verdict is on screen, eliding its longest reasons (the full text is
    its tooltip).

    The width is the style's own, computed as Qt computes it (bold font, as
    for a highlighted section) — it matched sectionSizeHint to the pixel,
    offscreen and cocoa — minus the arrow.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        # What QTableView gives its own header, and a replacement does not get.
        self.setSectionsClickable(True)
        self.setHighlightSections(True)
        # When the arrow moves, Qt re-sizes ResizeToContents sections itself,
        # so the newly sorted column gets its room without help from here.

    def sectionSizeFromContents(self, logical: int) -> QSize:
        size = super().sectionSizeFromContents(logical)
        if not self.isSortIndicatorShown() or logical == self.sortIndicatorSection():
            return size
        opt = QStyleOptionHeader()
        self.initStyleOption(opt)
        opt.section = logical
        opt.text = str(self.model().headerData(logical, self.orientation()) or "")
        font = self.font()
        font.setBold(True)
        opt.fontMetrics = QFontMetrics(font)
        opt.sortIndicator = QStyleOptionHeader.SortIndicator.None_
        bare = self.style().sizeFromContents(QStyle.ContentsType.CT_HeaderSection,
                                             opt, QSize(), self)
        return QSize(min(size.width(), bare.width()), size.height())


class _GripHandle(QSplitterHandle):
    """A divider you can see: dotted bars centred in the handle."""

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.TEXT_FAINT))
        x = self.width() // 2 - 1
        top = self.height() // 2 - 20
        for y in range(top, top + 40, 5):
            p.drawRoundedRect(x - 1, y, 4, 2, 1, 1)
        p.end()


class GripSplitter(QSplitter):
    def __init__(self, orientation, parent=None) -> None:
        super().__init__(orientation, parent)
        self.setHandleWidth(GRIP_WIDTH)

    def createHandle(self) -> QSplitterHandle:
        return _GripHandle(self.orientation(), self)


class FrameBrowser(QWidget):
    """List (left) + preview (right) behind one grip, with Show/Select/sort.

    Rows in this class's API are SOURCE rows — indices into the host's list —
    whatever the view's current sort or filter.
    """

    selection_changed = Signal()      # the set of ticked frames changed
    current_changed = Signal(int)     # source row now previewed, -1 for none

    def __init__(self, pool, parent=None) -> None:
        super().__init__(parent)
        self._fitted = False       # fit_list runs once, on first show
        self.model = FrameTableModel(self)
        self.proxy = FrameFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.model.ticks_changed.connect(self._on_ticks_changed)

        self.view = _FrameTable()
        self.view.setHorizontalHeader(_CompactHeader(self.view))
        self.view.setModel(self.proxy)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.verticalHeader().setVisible(False)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(COL_TIME, Qt.SortOrder.AscendingOrder)
        hdr = self.view.horizontalHeader()
        for col in range(len(HEADERS)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        # Verdict takes what the list is given and elides; its long form is on hover.
        hdr.setSectionResizeMode(COL_VERDICT, QHeaderView.ResizeMode.Stretch)
        self.view.space_pressed.connect(self._toggle_current)
        self.view.selectionModel().currentRowChanged.connect(
            lambda cur, _prev: self._on_current(cur))

        self.preview = FramePreview()
        self.preview.setMinimumSize(300, 220)
        self.preview_controller = FramePreviewController(
            self.preview, pool, self._path_for_row)

        # --- the bar above the list ---
        self._show_group = QButtonGroup(self)
        self._show_buttons = {}
        show_row = QHBoxLayout()
        show_row.setContentsMargins(0, 0, 0, 0)
        show_row.addWidget(QLabel("Show:"))
        for mode in (SHOW_ALL, SHOW_KEPT, SHOW_REJECTED):
            b = QPushButton()
            b.setCheckable(True)
            b.setObjectName("segment")
            self._show_group.addButton(b)
            self._show_buttons[mode] = b
            b.clicked.connect(lambda _c=False, m=mode: self.set_show(m))
            show_row.addWidget(b)
        self._show_buttons[SHOW_ALL].setChecked(True)
        show_row.addSpacing(12)
        show_row.addWidget(QLabel("Select:"))
        self.select_all_btn = self._link("All", self.select_all)
        self.select_none_btn = self._link("None", self.select_none)
        self.reset_btn = self._link(RESET_TEXT, self.reset_to_suggested)
        self.reset_btn.setToolTip("Undo every tick you made yourself: the "
                                  "grader's suggestion decides again")
        for b in (self.select_all_btn, self.select_none_btn, self.reset_btn):
            show_row.addWidget(b)
        show_row.addStretch(1)

        # --- the preview's own header: full name left, the numbers right ---
        self.preview_name = QLabel("")
        self.preview_name.setObjectName("stepExplainer")
        self.preview_facts = QLabel("")
        self.preview_facts.setObjectName("stepExplainer")
        self.bigger_btn = QToolButton()
        self.bigger_btn.setText("⇤ bigger preview")
        self.bigger_btn.setCheckable(True)
        self.bigger_btn.setToolTip("Narrow the list to Time and Verdict; click "
                                   "again to bring the columns back")
        self.bigger_btn.toggled.connect(self.set_bigger_preview)
        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 4, 0)
        head.addWidget(self.preview_name, 1)
        head.addWidget(self.preview_facts)
        head.addWidget(self.bigger_btn)

        list_side = QWidget()
        self.list_layout = QVBoxLayout(list_side)   # delivery B adds its chart here
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.addWidget(self.view, 1)
        # FWHM over the session (spec decision 4.6), under the list in both
        # dialogs. Fixed height: the list is the stretch and gives it up. The
        # list column's floor stays far under the preview's (56 + 60 against
        # 250 px, measured offscreen 2026-09-27), so neither dialog's minimum
        # height moves and the 1280×800 floor holds.
        self.chart = QualityChart(verdict_text, is_rejected)
        self.chart.point_clicked.connect(self.select_from_chart)
        self.list_layout.addWidget(self.chart)
        preview_side = QWidget()
        pv = QVBoxLayout(preview_side)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.addLayout(head)
        pv.addWidget(self.preview, 1)

        self.splitter = GripSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(list_side)
        self.splitter.addWidget(preview_side)
        # The PREVIEW absorbs extra width now, the reverse of before: the list
        # is only as wide as its columns (spec §2.4.7), the preview is the
        # surface that judges a frame.
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setChildrenCollapsible(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addLayout(show_row)
        root.addWidget(self.splitter, 1)
        self._sizes_before_bigger: list[int] | None = None
        self._update_show_counts()

    def _link(self, text, slot) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("linkButton")
        b.setFlat(True)
        b.clicked.connect(slot)
        return b

    # --- the host's side ---
    def set_frames(self, stats: list) -> None:
        """Show a freshly graded list with its first kept frame previewed, so
        the preview is never an empty panel after a grade (spec 2026-09-28
        §2.6). Hand-made ticks are forgotten: they belonged to the previous
        list."""
        self.model.set_frames(stats)
        self.chart.set_frames(stats)
        self._update_show_counts()
        self.fit_list()
        first = self._first_to_preview()
        if first >= 0:
            # The reset left no current row, so this always moves the cursor
            # and _on_current does the rest: preview, header, chart ring.
            self.set_current_row(first)
        else:
            self.preview_controller.clear()
            self._update_preview_header(-1)
            self.chart.set_current(-1)
            # No row for Qt's selection model to land the cursor on, so
            # nothing else fires this signal.
            self.current_changed.emit(-1)

    def _first_to_preview(self) -> int:
        """The first kept frame in the list's own order; failing that the
        first frame that is not an error (every frame rejected: show one of
        them, which is the next thing he will want to see); else -1."""
        stats = self.model.frames()
        rows = [r for r in self._visible_rows() if not stats[r].error]
        kept = [r for r in rows if not is_rejected(stats[r])]
        return (kept or rows or [-1])[0]

    def refresh_verdicts(self) -> None:
        """Call after judge() re-ran on the same list."""
        self.model.reapply_ticks()
        self._update_show_counts()
        self.chart.refresh()

    def frames_moved(self) -> None:
        """After the host moved frames into rejected/ or back (their `path`
        and `moved` changed): rows, Show, counts and chart follow, and the
        preview re-reads the current frame from where it now is."""
        self.model.reapply_ticks()
        self.proxy.set_show(self.proxy.show_mode())     # Kept/Rejected read `moved`
        self._update_show_counts()
        self.chart.refresh()
        row = self.current_row()
        # A preceding remove_frames() can shift the current row (Qt moves
        # the selection when rows above it vanish), and the
        # chart's own idea of "current" is separate state the row alone
        # doesn't carry — left stale, the highlight kept pointing at the OLD
        # row's x-position, which after a removal can belong to a different
        # frame entirely, or none.
        self.chart.set_current(row)
        self._update_preview_header(row)
        if row >= 0:
            self.preview_controller.show_row(row)

    def add_frames(self, new_stats: list) -> None:
        """Merge newly graded frames in without touching what is already
        listed — Show, counts and chart pick up the addition; the preview and
        current row are untouched since nothing about the EXISTING rows
        moved."""
        if not new_stats:
            return
        self.model.add_frames(new_stats)
        self._update_show_counts()
        self.chart.refresh()

    def remove_frames(self, predicate) -> None:
        """Drop rows `predicate(stat)` accepts. MUST be followed by
        `frames_moved()` in the same pass — that call is what re-settles the
        chart's own "current" index, which a removal can shift or
        invalidate; without it the chart highlight is left pointing at
        whatever the OLD row index now means, which can be a different frame
        entirely, or none."""
        self.model.remove_frames(predicate)
        self._update_show_counts()
        self.chart.refresh()

    def add_above_list(self, widget: QWidget) -> None:
        """A host's own strip over the list, in the list's column: Stack's
        night verdict (spec decision 6). Not built in: Ha/OIII has none."""
        self.list_layout.insertWidget(0, widget)

    def frames(self) -> list:
        return self.model.frames()

    @staticmethod
    def headers() -> list[str]:
        return list(HEADERS)

    def checked_frames(self) -> list:
        """What the stack reads. A locked frame is left out even if something
        set `included` on it behind the model's back."""
        return [s for s in self.model.frames() if s.included and not _locked(s)]

    @property
    def user_touched(self) -> set[int]:
        return self.model.touched()

    # --- selection helpers (buttons) ---
    def _visible_rows(self) -> list[int]:
        return [self.proxy.mapToSource(self.proxy.index(r, 0)).row()
                for r in range(self.proxy.rowCount())]

    def select_all(self) -> None:
        """Ticks what is SHOWN: under Rejected, "All" takes back the rejects
        and leaves nothing else touched."""
        self.model.set_ticked(self._visible_rows(), True)

    def select_none(self) -> None:
        self.model.set_ticked(self._visible_rows(), False)

    def reset_to_suggested(self) -> None:
        self.model.revert_to_verdicts()

    def set_show(self, mode: str) -> None:
        self.proxy.set_show(mode)
        self._show_buttons[mode].setChecked(True)

    def _update_show_counts(self) -> None:
        stats = self.model.frames()
        rejected = sum(1 for s in stats if is_rejected(s))
        counts = {SHOW_ALL: len(stats), SHOW_KEPT: len(stats) - rejected,
                  SHOW_REJECTED: rejected}
        names = {SHOW_ALL: "All", SHOW_KEPT: "Kept", SHOW_REJECTED: "Rejected"}
        for mode, b in self._show_buttons.items():
            b.setText(f"{names[mode]} {counts[mode]}")

    # --- rows, in SOURCE terms ---
    def row_count(self) -> int:
        """Rows currently SHOWN."""
        return self.proxy.rowCount()

    def view_rows(self) -> list[int]:
        """Source rows in the order the list shows them."""
        return self._visible_rows()

    def is_checked(self, row: int) -> bool:
        return bool(self.model.frame(row).included)

    def set_checked(self, row: int, checked: bool) -> None:
        """Exactly what a click on the box does."""
        self.model.setData(self.model.index(row, COL_USE),
                           Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked,
                           Qt.ItemDataRole.CheckStateRole)

    def cell_text(self, row: int, col: int) -> str:
        return self.model.data(self.model.index(row, col)) or ""

    def cell_tooltip(self, row: int, col: int) -> str:
        return self.model.data(self.model.index(row, col),
                               Qt.ItemDataRole.ToolTipRole) or ""

    def cell_colour(self, row: int, col: int) -> str:
        return self.model.data(self.model.index(row, col),
                               Qt.ItemDataRole.ForegroundRole).name()

    def current_row(self) -> int:
        idx = self.view.currentIndex()
        return self.proxy.mapToSource(idx).row() if idx.isValid() else -1

    def set_current_row(self, row: int) -> None:
        """Select a frame by source row — also how delivery B's chart will
        jump to the point that was clicked."""
        src = self.model.index(row, COL_TIME)
        idx = self.proxy.mapFromSource(src)
        if idx.isValid():
            self.view.setCurrentIndex(idx)

    def select_from_chart(self, row: int) -> None:
        """A click on the chart: that frame, in the list. If Show hides it,
        Show goes to All first — a click that selected nothing would read as
        a broken chart. (Delivery C's night toggles hide through the extra
        filter; C must lift that too.)"""
        if not self.proxy.mapFromSource(self.model.index(row, COL_TIME)).isValid():
            self.set_show(SHOW_ALL)
        self.set_current_row(row)
        idx = self.view.currentIndex()
        if idx.isValid():
            self.view.scrollTo(idx)

    # --- internals ---
    def _path_for_row(self, row: int):
        stats = self.model.frames()
        return stats[row].path if 0 <= row < len(stats) else None

    def _on_current(self, proxy_index) -> None:
        row = (self.proxy.mapToSource(proxy_index).row()
               if proxy_index.isValid() else -1)
        if row >= 0:
            self.preview_controller.show_row(row)
        else:
            self.preview_controller.clear()
        self._update_preview_header(row)
        self.chart.set_current(row)
        self.current_changed.emit(row)

    def _update_preview_header(self, row: int) -> None:
        stats = self.model.frames()
        if not (0 <= row < len(stats)):
            self.preview_name.setText("")
            self.preview_name.setToolTip("")
            self.preview_facts.setText("")
            return
        s = stats[row]
        self.preview_name.setText(os.path.basename(s.path))
        self.preview_name.setToolTip(s.path)
        facts = [full_label(getattr(s, "captured", None)),
                 f"{s.star_count} stars", f"FWHM {s.fwhm:.1f}"]
        self.preview_facts.setText(" · ".join(f for f in facts if f))

    def _toggle_current(self) -> None:
        row = self.current_row()
        if row >= 0:
            self.set_checked(row, not self.is_checked(row))

    def _on_ticks_changed(self) -> None:
        self.selection_changed.emit()

    # --- width ---
    def list_natural_width(self) -> int:
        """What the visible columns need, plus the frame and a scrollbar."""
        hdr = self.view.horizontalHeader()
        total = 0
        for col in range(len(HEADERS)):
            if self.view.isColumnHidden(col):
                continue
            total += max(self.view.sizeHintForColumn(col), hdr.sectionSizeHint(col))
        return (total + self.view.verticalScrollBar().sizeHint().width()
                + 2 * self.view.frameWidth())

    def fit_list(self) -> None:
        """Give the list what its columns need, capped, and the preview the rest."""
        total = sum(self.splitter.sizes()) or self.splitter.width()
        if total <= 0:
            return
        want = min(self.list_natural_width(), int(total * LIST_MAX_SHARE))
        self.splitter.setSizes([want, total - want])

    def set_bigger_preview(self, on: bool) -> None:
        if self.bigger_btn.isChecked() != on:
            self.bigger_btn.setChecked(on)      # re-enters through toggled
            return
        if on:
            self._sizes_before_bigger = self.splitter.sizes()
            for col in DETAIL_COLUMNS:
                self.view.hideColumn(col)
            self.fit_list()
        else:
            for col in DETAIL_COLUMNS:
                self.view.showColumn(col)
            if self._sizes_before_bigger:
                self.splitter.setSizes(self._sizes_before_bigger)
            self._sizes_before_bigger = None

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            self.fit_list()
