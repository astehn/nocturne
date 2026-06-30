from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem


class Stepper(QListWidget):
    stageSelected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stages = []
        self.itemClicked.connect(self._on_click)

    def set_stages(self, stages) -> None:
        self._stages = list(stages)
        self.clear()
        for stage in self._stages:
            item = QListWidgetItem(self._label(stage.label, stage.enabled))
            if not stage.enabled:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.addItem(item)

    @staticmethod
    def _label(label: str, enabled: bool, done: bool = False) -> str:
        text = label if enabled else f"{label}  (soon)"
        return f"✓ {text}" if done else text

    def _on_click(self, item) -> None:
        index = self.row(item)
        if 0 <= index < len(self._stages) and self._stages[index].enabled:
            self.stageSelected.emit(index)

    def set_current(self, index: int) -> None:
        self.setCurrentRow(index)

    def mark_done(self, done_ids: set) -> None:
        for i, stage in enumerate(self._stages):
            self.item(i).setText(
                self._label(stage.label, stage.enabled, stage.id in done_ids)
            )
