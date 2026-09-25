"""One stream for everything that happened: steps, results, information, and
copies of warnings. Replaces the bottom bar's log and output boxes.

The old output box sat half-empty most of the time (Andreas, 2026-09-25: "why
occupy that much real estate for something that is barely used"), and the two
boxes together took height from every column. The three message INTENTS stay
distinct — they are told apart by colour here, and `ActivityChannel` keeps each
old API so the step log and the result channel can still be read separately.
"""
from __future__ import annotations

import html
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QTextEdit, QVBoxLayout,
                               QWidget)

from .theme import DANGER, TEXT, TEXT_DIM, WARNING

RESULT_COLOUR = "#7fd4c1"          # teal: a result, what the output box used to show
KIND_STYLE = {
    "step": f"color:{TEXT}",
    "result": f"color:{RESULT_COLOUR}",
    "info": f"color:{TEXT_DIM}; font-style:italic",
    "warn": f"color:{DANGER}",
    # Amber, like the status slot's notice: a consequence of the user's own
    # action is not an error, and copying it here in red undid that.
    "notice": f"color:{WARNING}",
}


def _row_html(kind: str, stamp: str, text: str) -> str:
    return (f'<span style="color:{TEXT_DIM}">{stamp}</span> '
            f'<span style="{KIND_STYLE.get(kind, KIND_STYLE["step"])}">{html.escape(text)}</span>')


class _LargeView(QDialog):
    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Activity")
        self.resize(820, 520)
        lay = QVBoxLayout(self)
        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.text_edit.setPlainText(text)
        lay.addWidget(self.text_edit)


class ActivityPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[tuple[str, str, str]] = []     # (kind, stamp, text)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        head = QHBoxLayout()
        title = QLabel("Activity")
        title.setObjectName("panelSectionLabel")
        head.addWidget(title)
        head.addStretch(1)
        copy_btn = QPushButton("Copy")
        copy_btn.setFlat(True)
        copy_btn.clicked.connect(self.copy_all)
        big_btn = QPushButton("⤢")
        big_btn.setFlat(True)
        big_btn.setToolTip("Open the full history")
        big_btn.clicked.connect(lambda: self.open_large())
        head.addWidget(copy_btn)
        head.addWidget(big_btn)
        lay.addLayout(head)
        self.view = QTextEdit(self)
        self.view.setReadOnly(True)
        self.view.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # No scrollbar (Andreas, 2026-09-25): the newest line is always at the
        # bottom, older ones scroll off the top, the whole history is one
        # click away (⤢). Wheel and trackpad scrolling still work.
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Nothing: the text view gives up ALL its space before the step list
        # above loses any (Andreas, 2026-09-25: "if something should scroll
        # in the left column it should be the activity log"). The panel's
        # floor is its header row alone; the list keeps its full content
        # height until the column is shorter than list + header.
        # setMinimumHeight(0) means "unset" in Qt and falls back to QTextEdit's
        # own 90 px hint; a vertical Ignored policy drops that hint instead.
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        lay.addWidget(self.view, 1)

    def add(self, kind: str, text: str) -> None:
        if not text:
            return
        stamp = datetime.now().strftime("%H:%M")
        self._entries.append((kind, stamp, text))
        self.view.append(_row_html(kind, stamp, text))
        self._show_newest()

    def _show_newest(self) -> None:
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def entries(self, kind: str | None = None) -> list[str]:
        return [f"{stamp} {text}" for k, stamp, text in self._entries
                if kind is None or k == kind]

    def text(self) -> str:
        return "\n".join(self.entries())

    def clear(self, kind: str | None = None) -> None:
        if kind is None:
            self._entries = []
        else:
            self._entries = [e for e in self._entries if e[0] != kind]
        self.view.clear()
        for k, stamp, text in self._entries:
            self.view.append(_row_html(k, stamp, text))
        self._show_newest()

    def copy_all(self) -> None:
        QApplication.clipboard().setText(self.text())

    def open_large(self, extra: str = "") -> _LargeView:
        body = self.text() + (f"\n\n{extra}" if extra else "")
        dlg = _LargeView(body, self.window())
        dlg.show()
        return dlg


class ActivityChannel:
    """The old step-log and output-box APIs over one kind of the stream."""

    def __init__(self, panel: ActivityPanel, kind: str) -> None:
        self._panel = panel
        self._kind = kind

    # step-log API
    def append_entry(self, body: str) -> None:
        self._panel.add(self._kind, body)

    def append_info(self, body: str) -> None:
        self._panel.add("info", body)

    def append_result(self, body: str) -> None:
        self._panel.add("result", body)

    def clear_log(self) -> None:
        self._panel.clear(self._kind)

    def entries(self) -> list[str]:
        return self._panel.entries(self._kind)

    def text(self) -> str:
        return "\n".join(self.entries())

    # output-box API
    def show_line(self, text: str) -> None:
        self._panel.add(self._kind, text)

    def clear(self) -> None:
        self._panel.clear(self._kind)

    def toPlainText(self) -> str:  # noqa: N802 — the Qt name the tests use
        return "\n".join(e.split(" ", 1)[1] for e in self.entries()) \
            if self._kind == "result" else self.text()

    def isReadOnly(self) -> bool:  # noqa: N802
        return self._panel.view.isReadOnly()

    def textInteractionFlags(self):  # noqa: N802
        return self._panel.view.textInteractionFlags()
