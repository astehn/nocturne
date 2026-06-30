from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QLineEdit, QPushButton, QHBoxLayout,
    QDialogButtonBox, QWidget,
)

from ..settings import Settings


def _path_row(edit: QLineEdit) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(edit)
    browse = QPushButton("Browse…")
    browse.clicked.connect(
        lambda: edit.setText(QFileDialog.getOpenFileName(row)[0] or edit.text())
    )
    lay.addWidget(browse)
    return row


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._gx = QLineEdit(settings.graxpert_path)
        self._rc = QLineEdit(settings.rcastro_path)
        form = QFormLayout(self)
        form.addRow("GraXpert binary", _path_row(self._gx))
        form.addRow("RC-Astro binary (optional)", _path_row(self._rc))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def result_settings(self) -> Settings:
        return Settings(self._gx.text().strip(), self._rc.text().strip())
