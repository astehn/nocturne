from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStyledItemDelegate

from .theme import ACCENT, BG_3, SUCCESS, TEXT, TEXT_DIM, TEXT_FAINT


def step_state(index: int, current_index: int, done_indexes, enabled: bool,
               high_water: int | None = None) -> str:
    """Pure state decision for a stepper row.

    `high_water` is the furthest row reached this session. It separates a step
    you walked PAST and chose not to apply from one you have never been to —
    "upcoming" used to render both identically grey, and at the end of a pass
    "which steps did I skip?" is a real question the list is uniquely placed to
    answer.

    A high-water mark rather than `index < current_index`, because jumping back
    makes the current index go DOWN: walk to 8, return to 3, and rows 4-7 would
    quietly become unreached again — exactly when the question is hardest to
    answer from memory.

    Defaults to None, which restores the old four-state behaviour for any caller
    that has not been taught about it.
    """
    if not enabled:
        return "locked"
    if index == current_index:
        return "current"
    if index in done_indexes:
        return "done"
    if high_water is not None and index < high_water:
        return "skipped"
    return "upcoming"


class StepDelegate(QStyledItemDelegate):
    """Paints a status badge + label per row (state from the parent Stepper)."""

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        s.setHeight(max(s.height(), 40))
        return s

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        stepper = self.parent()
        state = stepper.state_at(index.row())
        r = option.rect
        cx, cy = r.left() + 18, r.center().y()

        # current: subtle background + accent left bar
        if state == "current":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(BG_3))
            painter.drawRoundedRect(QRectF(r.left() + 4, r.top() + 2,
                                           r.width() - 8, r.height() - 4), 8, 8)
            painter.setBrush(QColor(ACCENT))
            painter.drawRoundedRect(QRectF(r.left() + 4, r.top() + 6, 3,
                                           r.height() - 12), 1.5, 1.5)

        # badge
        badge = {"done": SUCCESS, "current": ACCENT, "skipped": TEXT_DIM,
                 "upcoming": TEXT_FAINT, "locked": TEXT_FAINT}[state]
        painter.setPen(QPen(QColor(badge), 2))
        if state == "done":
            painter.setBrush(QColor(SUCCESS))
            painter.drawEllipse(QRectF(cx - 8, cy - 8, 16, 16))
            painter.setPen(QPen(QColor("#06201c"), 2))
            painter.drawLine(int(cx - 3), int(cy), int(cx - 1), int(cy + 3))
            painter.drawLine(int(cx - 1), int(cy + 3), int(cx + 4), int(cy - 3))
        elif state == "current":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(cx - 8, cy - 8, 16, 16))
            painter.setBrush(QColor(ACCENT))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(cx - 3, cy - 3, 6, 6))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(cx - 6, cy - 6, 12, 12))
            if state == "skipped":
                # A dash through the empty ring: you were here and left it
                # alone. Deliberately NOT amber — pending was considered and
                # rejected for this list on 2026-09-13, and reusing its colour
                # would make a future reader think the two ideas were one.
                # Deliberately quiet, too: in a normal pass MOST steps are
                # skipped, so anything louder would shout at the common case.
                painter.drawLine(int(cx - 3), int(cy), int(cx + 3), int(cy))

        # label
        label = index.data(Qt.ItemDataRole.DisplayRole) or ""
        # Skipped keeps UPCOMING's label colour, not locked's fainter one: a
        # skipped step is still available to go back to, and dimming it would
        # read as unavailable.
        color = {"done": TEXT, "current": TEXT, "skipped": TEXT_DIM,
                 "upcoming": TEXT_DIM, "locked": TEXT_FAINT}[state]
        font = QFont(painter.font())
        font.setBold(state == "current")
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(QRectF(r.left() + 36, r.top(), r.width() - 80, r.height()),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                         str(label))

        # "soon" pill for locked rows
        if state == "locked":
            pill = QRectF(r.right() - 48, cy - 9, 40, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(BG_3))
            painter.drawRoundedRect(pill, 9, 9)
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), "soon")

        painter.restore()


class Stepper(QListWidget):
    stageSelected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stages = []
        self._current = -1
        self._done: set = set()
        self._high_water: int | None = None
        self.setItemDelegate(StepDelegate(self))
        self.itemClicked.connect(self._on_click)

    def set_stages(self, stages) -> None:
        self._stages = list(stages)
        self.clear()
        for stage in self._stages:
            item = QListWidgetItem(stage.label)
            if not stage.enabled:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.addItem(item)

    def _on_click(self, item) -> None:
        index = self.row(item)
        if 0 <= index < len(self._stages) and self._stages[index].enabled:
            self.stageSelected.emit(index)

    def set_current(self, index: int) -> None:
        self._current = index
        self.setCurrentRow(index)
        self.viewport().update()

    def set_high_water(self, index: int | None) -> None:
        """The furthest row reached this session; None disables skipped marks."""
        self._high_water = index
        self.viewport().update()

    def mark_done(self, done_ids: set) -> None:
        self._done = {i for i, s in enumerate(self._stages) if s.id in done_ids}
        self.viewport().update()

    def state_at(self, index: int) -> str:
        stage = self._stages[index]
        return step_state(index, self._current, self._done, stage.enabled,
                          self._high_water)
