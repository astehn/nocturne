from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSlider


class ResetSlider(QSlider):
    """Slider that resets to its construction default on double-click."""

    def __init__(self, default: int, *, minimum: int = 0, maximum: int = 100,
                 orientation: Qt.Orientation = Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setRange(minimum, maximum)   # range BEFORE value so default isn't clamped
        self.setValue(default)
        self._default = default
        self.setToolTip("Double-click to reset")

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.setValue(self._default)
        event.accept()
