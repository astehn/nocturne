"""A row of joined buttons for a fixed level: Off | Light | Strong.

Replaces the dropdown on steps whose choice is a LEVEL, not a different thing
(Andreas, 2026-10-08): a dropdown hides the alternatives until it is opened —
find it, open it, choose — where buttons show every level and take one click.
Buttons rather than a stepped slider because these steps have no live preview:
a slider reads as "drag and watch", and here nothing happens until Apply.

Speaks the subset of QComboBox the panels and MainWindow already use
(currentText/setCurrentText, currentIndex, count/itemText, currentTextChanged),
so the steps' option strings, history and recipes are unchanged.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget


class OptionButtons(QWidget):
    currentTextChanged = Signal(str)
    currentIndexChanged = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._values: list[str] = []
        self._buttons: list[QPushButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idToggled.connect(self._on_toggled)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(0)

    # --- the QComboBox subset ------------------------------------------------
    def addItems(self, values) -> None:  # noqa: N802
        for value in values:
            i = len(self._values)
            b = QPushButton(value[:1].upper() + value[1:])
            b.setCheckable(True)
            self._group.addButton(b, i)
            self._row.addWidget(b, 1)
            self._values.append(value)
            self._buttons.append(b)
        self._restyle()
        if self.currentIndex() < 0 and self._buttons:
            self._buttons[0].setChecked(True)

    def count(self) -> int:
        return len(self._values)

    def itemText(self, i: int) -> str:  # noqa: N802
        return self._values[i]

    def currentIndex(self) -> int:  # noqa: N802
        return self._group.checkedId()

    def currentText(self) -> str:  # noqa: N802
        i = self.currentIndex()
        return self._values[i] if 0 <= i < len(self._values) else ""

    def setCurrentIndex(self, i: int) -> None:  # noqa: N802
        if 0 <= i < len(self._buttons):
            self._buttons[i].setChecked(True)

    def setCurrentText(self, text: str) -> None:  # noqa: N802
        if text in self._values:
            self.setCurrentIndex(self._values.index(text))

    def buttons(self) -> list[QPushButton]:
        return list(self._buttons)

    # --- internals -------------------------------------------------------------
    def _on_toggled(self, i: int, checked: bool) -> None:
        if checked:
            self.currentIndexChanged.emit(i)
            self.currentTextChanged.emit(self._values[i])

    def _restyle(self) -> None:
        """Ends rounded, joints square: one control, not three buttons."""
        last = len(self._buttons) - 1
        for i, b in enumerate(self._buttons):
            b.setObjectName("level")
            b.setProperty("seg", "only" if last == 0 else
                          "first" if i == 0 else "last" if i == last else "mid")
