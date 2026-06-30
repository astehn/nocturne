from __future__ import annotations

from datetime import datetime

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

    def append_entry(self, body: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.appendPlainText(f"{stamp}  {body}")
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear_log(self) -> None:
        self.clear()

    def text(self) -> str:
        return self.toPlainText()
