from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPlainTextEdit


def format_log_entry(name, option, delta, dims=None) -> str:
    if dims is not None:
        return f"{name}  —  → {dims[0]}×{dims[1]}"
    label = f"{name} ({option})" if option not in (None, "") else name
    if delta is None:
        return label
    return f"{label}  —  Δ {delta:.1f}%"


class LogPanel(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumHeight(140)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def append_entry(self, body: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.appendPlainText(f"{stamp}  {body}")
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear_log(self) -> None:
        self.clear()

    def text(self) -> str:
        return self.toPlainText()


class OutputPanel(QPlainTextEdit):
    """Copyable box for routine results and progress (distinct from the timestamped
    Log). Read-only but selectable, so the user can copy a status line."""
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumHeight(140)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

    def show_line(self, text: str) -> None:
        if not text:
            return
        self.appendPlainText(text)
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())
