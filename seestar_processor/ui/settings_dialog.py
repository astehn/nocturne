from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..settings import Settings
from ..tools.probe import probe_binary


def _path_row(edit: QLineEdit, on_test, result: QLabel) -> QWidget:
    row = QWidget()
    outer = QVBoxLayout(row)
    outer.setContentsMargins(0, 0, 0, 0)
    line = QHBoxLayout()
    line.addWidget(edit)
    browse = QPushButton("Browse…")
    browse.clicked.connect(
        lambda: edit.setText(QFileDialog.getOpenFileName(row)[0] or edit.text())
    )
    test = QPushButton("Test")
    test.clicked.connect(on_test)
    line.addWidget(browse)
    line.addWidget(test)
    outer.addLayout(line)
    outer.addWidget(result)
    return row


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._probe_runner = None  # injectable for tests
        self._gx = QLineEdit(settings.graxpert_path)
        self._rc = QLineEdit(settings.rcastro_path)
        self._gx_result = QLabel("")
        self._rc_result = QLabel("")
        self._gx_result.setWordWrap(True)
        self._rc_result.setWordWrap(True)

        form = QFormLayout(self)
        form.addRow("GraXpert (required)",
                    _path_row(self._gx, self._test_graxpert, self._gx_result))
        form.addRow("RC-Astro (optional)",
                    _path_row(self._rc, self._test_rcastro, self._rc_result))
        note = QLabel("RC-Astro unlocks BlurX / NoiseX / StarX and the starless+stars export.")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _show_result(self, label: QLabel, path: str, args: list[str]) -> None:
        if not path.strip():
            label.setText("✗ No path set")
            return
        ok, msg = probe_binary(path.strip(), args, runner=self._probe_runner)
        label.setText(("✓ " if ok else "✗ ") + msg)

    def _test_graxpert(self) -> None:
        self._show_result(self._gx_result, self._gx.text(), ["-v"])

    def _test_rcastro(self) -> None:
        self._show_result(self._rc_result, self._rc.text(), ["--no-banner", "--help"])

    def result_settings(self) -> Settings:
        return Settings(self._gx.text().strip(), self._rc.text().strip())
