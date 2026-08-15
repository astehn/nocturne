from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QVBoxLayout,
)

from ..settings import start_dir
from . import file_dialogs


def _default_save(text: str, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _default_clipboard(text: str) -> None:
    QApplication.clipboard().setText(text)


class ProvenanceDialog(QDialog):
    """Read-only rendered-Markdown view of a processing provenance report, with
    Save (raw .md) and Copy-to-clipboard."""

    def __init__(self, report: str, settings, *, parent=None, source_label=None,
                 save_runner=_default_save, clipboard_runner=_default_clipboard) -> None:
        super().__init__(parent)
        self.setWindowTitle("Provenance report")
        self.setMinimumSize(640, 560)
        self._report = report
        self._settings = settings
        self._source_label = source_label
        self._save_runner = save_runner
        self._clipboard_runner = clipboard_runner

        view = QTextEdit()
        view.setReadOnly(True)
        view.setMarkdown(report)          # rendered display; raw text kept in self._report

        self.status = QLabel("")
        self._save_btn = QPushButton("Save…")
        self._save_btn.clicked.connect(self._save)
        self._copy_btn = QPushButton("Copy to clipboard")
        self._copy_btn.clicked.connect(self._copy)
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(self._save_btn)
        buttons.addWidget(self._copy_btn)
        buttons.addWidget(self.status)
        buttons.addStretch(1)
        buttons.addWidget(self._close_btn)

        root = QVBoxLayout(self)
        root.addWidget(view, 1)
        root.addLayout(buttons)

    def _save(self) -> None:
        stem = os.path.splitext(os.path.basename(self._source_label))[0] if self._source_label else ""
        name = f"{stem}-provenance.md" if stem else "provenance.md"
        default = os.path.join(start_dir(self._settings.base_dir), name)
        path, _ = file_dialogs.save_file(self, "Save provenance report", default,
                                              "Markdown (*.md);;Text (*.txt)")
        if path:
            self._save_runner(self._report, path)
            self.status.setText(f"Saved {os.path.basename(path)}")

    def _copy(self) -> None:
        self._clipboard_runner(self._report)
        self.status.setText("Copied to clipboard.")
