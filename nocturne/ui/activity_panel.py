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

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QTextEdit, QVBoxLayout,
                               QWidget)

from .theme import TEXT_DIM, TEXT_FAINT

# Quiet on purpose. The box sits right beside the image, and the eye goes to
# contrast (Andreas, 2026-09-25: "having fairly bright text next to a dark
# image your focus will be on the text and not the image"). So step lines
# are TEXT_DIM, not TEXT, and the three hues keep their meaning but lose
# their glare: each is the theme colour desaturated and set to ~5:1 against
# BG_2 — the same weight as TEXT_DIM (4.6:1), where they were 8.5, 7.6 and
# 4.4:1 before. Measured (WCAG contrast, BG_1 #1e1f22 behind the box / BG_2
# #26282c as the lighter worst case):
#   step   #8a9099  5.12 / 4.59     result #64a294  5.60 / 5.02
#   notice #b39244  5.58 / 5.00     warn   #d87d78  5.59 / 5.01
# The red could not simply be darkened: DANGER is already only 4.4:1 on BG_2,
# so toning it down means less saturation at the same weight, not less light.
RESULT_COLOUR = "#64a294"          # teal (was #7fd4c1): a result, what the output box used to show
NOTICE_COLOUR = "#b39244"          # amber, WARNING #e3b341 toned down
WARN_COLOUR = "#d87d78"            # red, DANGER #f85149 toned down
KIND_STYLE = {
    "step": f"color:{TEXT_DIM}",
    "result": f"color:{RESULT_COLOUR}",
    # Already TEXT_DIM, and dimmer would fall below 4.5:1 — so information
    # is told from a step by its italic alone.
    "info": f"color:{TEXT_DIM}; font-style:italic",
    "warn": f"color:{WARN_COLOUR}",
    # Amber, like the status slot's notice: a consequence of the user's own
    # action is not an error, and copying it here in red undid that.
    "notice": f"color:{NOTICE_COLOUR}",
}
# Smaller than the rest of the window by this many points (or pixels, where
# the stylesheet sizes in px), for the same reason as the colours.
FONT_STEP_DOWN = 2


def _row_html(kind: str, stamp: str, text: str) -> str:
    return (f'<span style="color:{TEXT_FAINT}">{stamp}</span> '
            f'<span style="{KIND_STYLE.get(kind, KIND_STYLE["step"])}">{html.escape(text)}</span>')


class _ActivityView(QTextEdit):
    """The small in-column view: a smaller font, and the newest line kept in
    sight through a resize."""

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().changeEvent(event)
        # QTextEdit copies its own font into the document on every font
        # change — including the app stylesheet's `* { font-size: 14px }`
        # arriving at polish — so the step-down is re-applied after it, and
        # is always relative to whatever the window's font actually is.
        if event.type() == QEvent.Type.FontChange:
            self._step_font_down()

    def _step_font_down(self) -> None:
        f = self.font()
        if f.pixelSize() > 0:
            f.setPixelSize(max(8, f.pixelSize() - FONT_STEP_DOWN))
        else:
            f.setPointSizeF(max(7.0, f.pointSizeF() - FONT_STEP_DOWN))
        self.document().setDefaultFont(f)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # There is no scrollbar, so a newest line pushed below the fold by a
        # window resize could not be brought back by eye. Re-anchor when the
        # view was showing the bottom (within a line of it) beforehand;
        # someone who wheeled up to read history stays where they are.
        bar = self.verticalScrollBar()
        at_bottom = bar.maximum() - bar.value() <= self.fontMetrics().lineSpacing()
        super().resizeEvent(event)
        if at_bottom:
            bar.setValue(bar.maximum())


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
        self.view = _ActivityView(self)
        self.view._step_font_down()
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
