"""The band of option groups above a frame list, and its fold.

Stack and Ha/OIII both build one: a row of titled groups — Frames · Combine ·
Result — that folds to a one-line summary with "Change…". Andreas,
2026-09-27: the rows between Folder and Output "feel busy and waste horizontal
space". Spec §2.1-2.2 and §2.5 (same group style, same fold in both dialogs).
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

# Words both dialogs show. One copy each, because two had already drifted
# apart (Ha/OIII's trim note was a dash splice with no full stop).
TRIM_NOTE = ("Off keeps the full frame. The edges are built from fewer frames, "
             "so they are noisier, but you can always crop later.")
PICKY_NOTE = "how picky to be about which subs to keep"


class WrappedNote(QLabel):
    """Wrapped text whose MINIMUM height is all of its wrapped lines.

    A word-wrapped QLabel reports ONE line as its minimum, because it can
    always get narrower. In a box layout it still paints fully, but every
    minimumSizeHint above it then understates the dialog — and that is the
    number StackDialog._fit_to_content reads to decide a screen is too short.
    Here the minimum is the real wrapped height AT THE WIDTH THE LABEL HAS,
    recomputed whenever that width or the text changes.

    EMPTY, it takes no room at all: no height, and hidden so the layout drops
    its spacing too. Several are decision notes that are blank most of the
    time (drizzle_note before grading, exclusive_note unless mosaic AND
    drizzle); reserving a line each left 21-42 px of dead gaps at the 800 px
    floor. Only a hide it made itself is undone when text arrives — a note a
    caller hid (the help toggle) stays hidden.
    """

    def __init__(self, text: str = "", object_name: str = "stepExplainer") -> None:
        super().__init__(text)
        self.setObjectName(object_name)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._last_width = -1
        self._hidden_while_empty = False
        self._sync_empty()

    def _sync_empty(self) -> None:
        explicit = Qt.WidgetAttribute.WA_WState_ExplicitShowHide
        if not self.text():
            # Claim the hide unless a caller already hid it on purpose (a fresh
            # widget is "hidden" too, but not explicitly).
            if not self.isHidden() or not self.testAttribute(explicit):
                super().setVisible(False)
                self._hidden_while_empty = True
        elif self._hidden_while_empty:
            self._hidden_while_empty = False
            if self.parentWidget() is None:
                self.setAttribute(explicit, False)   # shown with its future parent
            else:
                super().setVisible(True)

    def setVisible(self, visible: bool) -> None:
        # Anyone else deciding visibility overrides the empty-hide bookkeeping.
        self._hidden_while_empty = False
        super().setVisible(visible)

    def minimumSizeHint(self) -> QSize:
        base = super().minimumSizeHint()
        width = self.width() if self.width() > 0 else 240
        return QSize(base.width(), self.heightForWidth(width) if self.text() else 0)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        if not self.text():
            return QSize(hint.width(), 0)
        return QSize(hint.width(), max(hint.height(), self.minimumSizeHint().height()))

    def setText(self, text: str) -> None:
        super().setText(text)
        self._sync_empty()
        self.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if event.size().width() != self._last_width:
            self._last_width = event.size().width()
            self.updateGeometry()


class OptionGroup(QFrame):
    """One titled group. Callers add their controls to `body`."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("optionGroup")
        self.title = QLabel(title.upper())
        self.title.setObjectName("optionGroupTitle")
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(4)
        col = QVBoxLayout(self)
        col.setContentsMargins(8, 6, 8, 8)
        col.setSpacing(4)
        col.addWidget(self.title)
        col.addLayout(self.body)
        col.addStretch(1)


class OptionBand(QWidget):
    """Groups side by side, or — folded — one summary line and "Change…"."""

    folded_changed = Signal(bool)

    def __init__(self, summary: Callable[[], str], parent=None) -> None:
        super().__init__(parent)
        self._summary = summary
        self.groups: list[OptionGroup] = []

        self._open = QWidget()
        self._open_row = QHBoxLayout(self._open)
        self._open_row.setContentsMargins(0, 0, 0, 0)
        self._open_row.setSpacing(6)
        self.fold_btn = QToolButton()
        # Words, not a bare arrow: a 5 px glyph alone in the corner was the
        # one control in the band nobody would find (review, 2026-09-27).
        self.fold_btn.setText("▴ Fold")
        self.fold_btn.setToolTip("Fold the options into one line")
        self.fold_btn.clicked.connect(lambda: self.set_folded(True))
        self._open_row.addWidget(self.fold_btn, 0, Qt.AlignmentFlag.AlignTop)

        self._closed = QWidget()
        closed_col = QVBoxLayout(self._closed)
        closed_col.setContentsMargins(0, 0, 0, 0)
        closed_col.setSpacing(2)
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("stepExplainer")
        self.change_btn = QPushButton("Change…")
        self.change_btn.clicked.connect(lambda: self.set_folded(False))
        line.addWidget(self.summary_label, 1)
        line.addWidget(self.change_btn)
        closed_col.addLayout(line)
        # What the hidden groups were WARNING about. Folding must not hide a
        # cost you are about to pay — the same rule the help toggle follows
        # for drizzle_note and exclusive_note.
        self.folded_note = WrappedNote("")
        closed_col.addWidget(self.folded_note)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._open)
        root.addWidget(self._closed)
        self._folded = False
        self._closed.hide()

    def add_group(self, title: str, stretch: int = 1) -> OptionGroup:
        group = OptionGroup(title)
        # before the fold button, which stays last
        self._open_row.insertWidget(len(self.groups), group, stretch)
        self.groups.append(group)
        return group

    def is_folded(self) -> bool:
        return self._folded

    def set_folded(self, folded: bool) -> None:
        if folded == self._folded:
            return
        self._folded = folded
        self._open.setVisible(not folded)
        self._closed.setVisible(folded)
        self.refresh_summary()
        self.folded_changed.emit(folded)

    def refresh_summary(self) -> None:
        self.summary_label.setText(self._summary())

    def set_folded_note(self, text: str) -> None:
        self.folded_note.setText(text)
        self.folded_note.setVisible(bool(text))
