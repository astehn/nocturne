from __future__ import annotations

import glob
import os

from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from ..batch import overwrites_source, run_batch
from ..core.tasks import CancelToken, Cancelled, clear_ambient, set_ambient
from ..recipe import load_recipe
from ..settings import start_dir
from .worker import run_async
from . import file_dialogs


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
        self._active_token: CancelToken | None = None
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

        self.run_btn = QPushButton("Run")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self.run)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel_active)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.hide()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.run_btn)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(close_btn)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self.progress)
        root.addWidget(self.status)
        root.addLayout(buttons)

    # --- browse handlers ---
    def _browse_recipe(self) -> None:
        path = file_dialogs.open_file(self, "Recipe", start_dir(self._settings.base_dir), "Recipe (*.json)")
        if path:
            self.recipe_edit.setText(path)

    def _browse_input(self) -> None:
        path = file_dialogs.choose_folder(self, "Input folder", start_dir(self._settings.base_dir))
        if path:
            self.input_edit.setText(path)

    def _browse_output(self) -> None:
        path = file_dialogs.choose_folder(self, "Output folder", start_dir(self._settings.base_dir))
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
        # Guard here, not only via the disabled button: two runs would write the
        # same output filenames. A disabled QPushButton stops clicks, but not a
        # shortcut, a duplicate connect, or a programmatic call.
        if self._active_token is not None:
            return
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
        # run_batch guards this per file too, and that is the authoritative
        # check. Saying it once up front is simply kinder than fifty identical
        # failures after the fact. Only when EVERY file collides: a partial
        # collision is per-file business, and refusing the whole batch would
        # strand the files that are fine.
        if paths and all(overwrites_source(p, outdir, fmt) for p in paths):
            self.status.setText(
                "Every file would overwrite the source it was read from — "
                "choose a different output folder or format.")
            return
        self.progress.setMaximum(max(1, len(paths)))
        self.progress.setValue(0)
        self.status.setText("Processing…")

        token = CancelToken()
        self._active_token = token
        self._set_busy(True)

        def work():
            set_ambient(token)
            try:
                return runner(recipe, paths, outdir, fmt, settings,
                              on_progress=lambda i, n, p: self._signals.progress.emit(i, n))
            finally:
                clear_ambient()

        run_async(self._pool, work, self._on_done, self._on_error)

    def _set_busy(self, busy: bool) -> None:
        """Block re-entrant runs so two workers can't write the same output file."""
        self.run_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.cancel_btn.setVisible(busy)

    def _cancel_active(self) -> None:
        tok = self._active_token
        if tok is not None:
            tok.cancel()
            # Not "finishing the current file": cancel() SIGTERMs any external
            # tool bound to the token (run_cli binds GraXpert/RC-Astro), so a
            # file mid-way through such a step is abandoned, not completed. No
            # partial export results either way — the kill lands before export.
            self.status.setText("Cancelling…")

    def _on_progress(self, i: int, n: int) -> None:
        self.progress.setMaximum(max(1, n))
        self.progress.setValue(i)

    def _on_done(self, results) -> None:
        """Name the files that failed and why. run_batch already returns a
        per-file verdict; reporting only the count hid every reason."""
        self._active_token = None
        self._set_busy(False)
        failed = [r for r in results if not r.get("ok")]
        ok = len(results) - len(failed)
        summary = f"Done — {ok}/{len(results)} succeeded."
        if failed:
            lines = "\n".join(
                f"• {os.path.basename(r['path'])} — {r.get('message') or 'unknown error'}"
                for r in failed)
            summary = f"{summary}\n{len(failed)} failed:\n{lines}"
        self.status.setText(summary)

    def _on_error(self, exc) -> None:
        self._active_token = None
        self._set_busy(False)
        if isinstance(exc, Cancelled):
            done = self.progress.value()
            self.status.setText(f"Cancelled — {done} file(s) written before stopping.")
            return
        self.status.setText(f"Failed: {exc}")
