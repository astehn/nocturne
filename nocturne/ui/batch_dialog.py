from __future__ import annotations

import glob
import os

from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from ..batch import run_batch
from ..recipe import load_recipe
from ..settings import start_dir
from .worker import run_async


class _ProgressSignals(QObject):
    progress = Signal(int, int)


def _picker_row(edit: QLineEdit, on_browse) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(edit)
    btn = QPushButton("Browse…")
    btn.clicked.connect(on_browse)
    lay.addWidget(btn)
    return row


class BatchDialog(QDialog):
    def __init__(self, settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Batch process")
        self.setMinimumWidth(460)
        self._settings = settings
        self._batch_runner = run_batch  # injectable for tests
        self._pool = QThreadPool.globalInstance()
        self._signals = _ProgressSignals()
        self._signals.progress.connect(self._on_progress)

        self.recipe_edit = QLineEdit()
        self.input_edit = QLineEdit()
        self.output_edit = QLineEdit()
        self.format_box = QComboBox()
        self.format_box.addItems(["TIFF", "PNG", "FITS"])
        self.progress = QProgressBar()
        self.status = QLabel("")
        self.status.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Recipe", _picker_row(self.recipe_edit, self._browse_recipe))
        form.addRow("Input folder", _picker_row(self.input_edit, self._browse_input))
        form.addRow("Output folder", _picker_row(self.output_edit, self._browse_output))
        form.addRow("Format", self.format_box)

        run_btn = QPushButton("Run")
        run_btn.setObjectName("primary")
        run_btn.clicked.connect(self.run)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(run_btn)
        buttons.addWidget(close_btn)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self.progress)
        root.addWidget(self.status)
        root.addLayout(buttons)

    # --- browse handlers ---
    def _browse_recipe(self) -> None:
        path = QFileDialog.getOpenFileName(self, "Recipe", start_dir(self._settings.base_dir), "Recipe (*.json)")[0]
        if path:
            self.recipe_edit.setText(path)

    def _browse_input(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Input folder", start_dir(self._settings.base_dir))
        if path:
            self.input_edit.setText(path)

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Output folder", start_dir(self._settings.base_dir))
        if path:
            self.output_edit.setText(path)

    # --- run ---
    def _input_files(self) -> list[str]:
        folder = self.input_edit.text().strip()
        files: list[str] = []
        for pat in ("*.fit", "*.fits", "*.fts"):
            files.extend(glob.glob(os.path.join(folder, pat)))
        return sorted(files)

    def run(self) -> None:
        recipe_path = self.recipe_edit.text().strip()
        if not recipe_path or not self.output_edit.text().strip():
            self.status.setText("Pick a recipe and an output folder.")
            return
        recipe = load_recipe(recipe_path)
        paths = self._input_files()
        fmt = self.format_box.currentText()
        outdir = self.output_edit.text().strip()
        settings = self._settings
        runner = self._batch_runner
        self.progress.setMaximum(max(1, len(paths)))
        self.progress.setValue(0)
        self.status.setText("Processing…")

        def work():
            return runner(recipe, paths, outdir, fmt, settings,
                          on_progress=lambda i, n, p: self._signals.progress.emit(i, n))

        run_async(self._pool, work, self._on_done, self._on_error)

    def _on_progress(self, i: int, n: int) -> None:
        self.progress.setMaximum(max(1, n))
        self.progress.setValue(i)

    def _on_done(self, results) -> None:
        ok = sum(1 for r in results if r.get("ok"))
        self.status.setText(f"Done — {ok}/{len(results)} succeeded.")

    def _on_error(self, exc) -> None:
        self.status.setText(f"Failed: {exc}")
