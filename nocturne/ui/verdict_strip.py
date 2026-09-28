"""The night's verdict over Stack's frame list (spec 2026-09-27 decision 6;
stack-layout mockup A: above the list, in its column). Stack only — Ha/OIII
gets no verdict in delivery B.

It also carries the rejected-folder buttons (decision 7): they act on what
the verdict just counted, so they sit where it is read.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QPushButton, QSizePolicy,
                               QVBoxLayout)

from .option_band import WrappedNote

MORE_TEXT = "details ▸"
BACK_TEXT = "Move them back"


def move_label(n: int) -> str:
    return f"Move {n} {'frame' if n == 1 else 'frames'} to rejected/…"


class VerdictStrip(QFrame):
    move_requested = Signal()
    back_requested = Signal()
    expanded = Signal()          # the user opened the details the screen folded

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # The option groups' panel: one look for "a box of facts about this set".
        self.setObjectName("optionGroup")
        # Never widens the list — its width is its columns' (spec §2.4.7),
        # and ⇤ bigger preview must still narrow it to Time and Verdict.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        self.headline = WrappedNote("", object_name="verdictHeadline")
        self.headline.setStyleSheet("font-weight: bold;")
        self.more_btn = QPushButton(MORE_TEXT)
        self.more_btn.setObjectName("linkButton")
        self.more_btn.setFlat(True)
        self.more_btn.setToolTip("Show the whole verdict")
        self.more_btn.clicked.connect(self._on_more)
        self.details = WrappedNote("")
        self.message = WrappedNote("")
        self.move_btn = QPushButton("")
        self.move_btn.setToolTip(
            "Move every frame you have not ticked into a folder called rejected "
            "inside the subs folder. You are asked first; nothing is deleted, "
            "and you can move them back.")
        self.move_btn.clicked.connect(lambda: self.move_requested.emit())
        self.back_btn = QPushButton("")
        self.back_btn.setToolTip("Put back exactly the frames Nocturne moved into "
                                 "rejected, as recorded there")
        self.back_btn.clicked.connect(lambda: self.back_requested.emit())

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self.headline, 1)
        head.addWidget(self.more_btn)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(self.move_btn)
        actions.addWidget(self.back_btn)
        actions.addStretch(1)
        col = QVBoxLayout(self)
        col.setContentsMargins(8, 6, 8, 8)
        col.setSpacing(4)
        col.addLayout(head)
        col.addWidget(self.details)
        col.addWidget(self.message)
        col.addLayout(actions)

        self._verdict = None
        self._compact = False
        self._user_expanded = False
        self._move_n = 0
        self._back_n = 0
        self._sync()

    # --- what it says ---
    def set_verdict(self, verdict) -> None:
        self._verdict = verdict
        self._sync()

    def set_move_count(self, n: int) -> None:
        self._move_n = n
        self._sync()

    def set_back_count(self, n: int) -> None:
        self._back_n = n
        self._sync()

    def set_message(self, text: str) -> None:
        self.message.setText(text)
        self._sync()

    def set_actions_enabled(self, on: bool) -> None:
        self.move_btn.setEnabled(on)
        self.back_btn.setEnabled(on)

    # --- the screen's fold ---
    def set_compact(self, on: bool) -> None:
        self._compact = on
        self._sync()

    def is_compact(self) -> bool:
        return self._compact

    def user_expanded(self) -> bool:
        return self._user_expanded

    def _on_more(self) -> None:
        # His click outranks the screen's fold, as "How this works" does.
        self._user_expanded = True
        self.set_compact(False)
        self.expanded.emit()

    def _sync(self) -> None:
        v = self._verdict
        self.headline.setText(v.headline if v else "")
        self.headline.setToolTip(v.text() if v else "")
        detail = " ".join(v.details) if v else ""
        self.details.setText(detail)
        self.details.setVisible(bool(detail) and not self._compact)
        self.more_btn.setVisible(bool(detail) and self._compact)
        self.move_btn.setText(move_label(self._move_n))
        self.move_btn.setVisible(self._move_n > 0)
        self.back_btn.setText(f"{BACK_TEXT} ({self._back_n})")
        self.back_btn.setVisible(self._back_n > 0)
        self.setVisible(bool(v) or self._move_n > 0 or self._back_n > 0
                        or bool(self.message.text()))
