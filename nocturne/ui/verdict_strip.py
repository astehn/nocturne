"""The night's verdict, over the chart across the full width (spec 2026-09-28
§2.4, layout C; calm-layout-2 mockup, card C). Stack only — Ha/OIII has no
verdict.

One row of labelled facts — a bold headline, then "Kept 316 of 420 · 53 of
70 min", "Rejected 87 trailed · 17 soft", "Stars about 9″ (FWHM 2.3 px)" —
with Move / Move back at the right end. Andreas, 2026-09-28: the same text as
one paragraph was "just a blob of text". A narrow window wraps whole facts
onto a second line, each still labelled (FlowLayout).

It also carries the rejected-folder buttons (spec 2026-09-27 decision 7):
they act on what the verdict just counted, so they sit where it is read.
"""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from . import theme
from .flow_layout import FlowBox
from .option_band import WrappedNote

MORE_TEXT = "details ▸"
BACK_TEXT = "Move them back"


def move_label(n: int) -> str:
    return f"Move {n} {'frame' if n == 1 else 'frames'} to rejected/…"


def fact_html(label: str, value: str) -> str:
    """"<dim>Kept</dim> 316 of 420 · 53 of 70 min" — the label in TEXT_DIM."""
    return (f'<span style="color:{theme.TEXT_DIM}">{html.escape(label)}</span> '
            f"{html.escape(value)}")


# Ruling R7 (fix round 1, 2026-09-28): measured at 1920, FlowLayout's own
# default (14, rendering at 15px) between facts against ~4px between a
# fact's label and its value (one space character) — at that ratio the row
# read as one blob, not five facts. 26px, about 6.5x the intra-fact gap,
# reads as separate facts.
_FACT_H_SPACING = 26


class VerdictStrip(QFrame):
    move_requested = Signal()
    back_requested = Signal()
    expanded = Signal()          # the user opened the details the screen folded

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # The option groups' panel: one look for "a box of facts about this set".
        self.setObjectName("optionGroup")
        # Never widens the dialog: the facts wrap instead.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        self.headline = QLabel("")
        self.headline.setObjectName("verdictHeadline")
        self.headline.setStyleSheet("font-weight: bold;")
        self.more_btn = QPushButton(MORE_TEXT)
        self.more_btn.setObjectName("linkButton")
        self.more_btn.setFlat(True)
        self.more_btn.setToolTip("Show the whole verdict")
        self.more_btn.clicked.connect(self._on_more)
        self.facts_box = FlowBox(h_spacing=_FACT_H_SPACING)
        self.facts_box.flow.addWidget(self.headline)
        self.facts_box.flow.addWidget(self.more_btn)
        self.fact_labels: list[QLabel] = []
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

        # The row is a WIDGET, not a nested layout: when the facts wrap, the
        # FlowBox's updateGeometry must reach a layout that is some widget's
        # own. A nested QHBoxLayout kept its cached one-line minimum
        # (measured: 78 px at 2400 wide and at 600), so the dialog never saw
        # the second line.
        self.row = QWidget()
        row = QHBoxLayout(self.row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.facts_box, 1)
        row.addWidget(self.move_btn, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.back_btn, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout(self)
        col.setContentsMargins(9, 6, 9, 6)
        col.setSpacing(4)
        col.addWidget(self.row)
        col.addWidget(self.message)

        self._verdict = None
        self._compact = False
        self._user_expanded = False
        self._move_n = 0
        self._back_n = 0
        self._sync()

    # --- what it says ---
    def set_verdict(self, verdict) -> None:
        self._verdict = verdict
        self._rebuild_facts()
        self._sync()

    def details_text(self) -> str:
        """The detail sentences, as the old paragraph read — for a reader
        that wants the words, not the layout."""
        return " ".join(self._verdict.details) if self._verdict else ""

    def fact_pairs(self) -> list[tuple[str, str]]:
        return list(self._verdict.facts) if self._verdict else []

    def details_shown(self) -> bool:
        """The facts are on screen — not folded to the headline."""
        return bool(self.fact_labels) and not any(l.isHidden() for l in self.fact_labels)

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

    def _rebuild_facts(self) -> None:
        flow = self.facts_box.flow
        for label in self.fact_labels:
            flow.removeWidget(label)
            label.deleteLater()
        self.fact_labels = []
        if self._verdict is None:
            return
        # A fact never wraps inside itself: it is one labelled unit, and the
        # flow moves it whole onto the next line.
        for (label, value), sentence in zip(self._verdict.facts, self._verdict.details):
            fact = QLabel(fact_html(label, value))
            fact.setTextFormat(Qt.TextFormat.RichText)
            fact.setToolTip(sentence)
            flow.addWidget(fact)
            self.fact_labels.append(fact)

    def _sync(self) -> None:
        v = self._verdict
        self.headline.setText(v.headline if v else "")
        self.headline.setToolTip(v.text() if v else "")
        has_facts = bool(self.fact_labels)
        for label in self.fact_labels:
            label.setVisible(not self._compact)
        self.more_btn.setVisible(has_facts and self._compact)
        self.move_btn.setText(move_label(self._move_n))
        self.move_btn.setVisible(self._move_n > 0)
        self.back_btn.setText(f"{BACK_TEXT} ({self._back_n})")
        self.back_btn.setVisible(self._back_n > 0)
        self.setVisible(bool(v) or self._move_n > 0 or self._back_n > 0
                        or bool(self.message.text()))
