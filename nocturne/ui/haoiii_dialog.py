from __future__ import annotations

import glob
import os

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..settings import start_dir
from ..stacking.grade import grade_frames
from ..stacking.haoiii import HaOIIIOptions, run_haoiii_extract
from .worker import run_async

KAPPA = {"Low": 3.0, "Medium": 2.5, "High": 2.0}


class _Signals(QObject):
    progress = Signal(int, int, str)


def _picker_row(edit: QLineEdit, on_browse) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(edit)
    btn = QPushButton("Browse…")
    btn.clicked.connect(on_browse)
    lay.addWidget(btn)
    return row


class HaOIIIDialog(QDialog):
    def __init__(self, settings, parent=None, on_master=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ha/OIII extract")
        self.setMinimumWidth(560)
        self._settings = settings
        self._on_master = on_master
        self._grade_runner = grade_frames       # injectable for tests
        self._extract_runner = run_haoiii_extract  # injectable for tests
        self._stats = []
        self._busy = False
        self._pool = QThreadPool.globalInstance()
        self._signals = _Signals()
        self._signals.progress.connect(self._on_progress)

        self.folder_edit = QLineEdit()
        self.output_edit = QLineEdit()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Use", "File", "Stars", "FWHM", "Bg"])
        self.avg_radio = QRadioButton("Average")
        self.sigma_radio = QRadioButton("Sigma-clipped")
        self.sigma_radio.setChecked(True)
        self.kappa_box = QComboBox()
        self.kappa_box.addItems(list(KAPPA.keys()))
        self.kappa_box.setCurrentText("Medium")
        self.progress = QProgressBar()
        self.status = QLabel("")
        self.status.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Folder of raw subs", _picker_row(self.folder_edit, self._browse_folder))
        method_row = QHBoxLayout()
        method_row.addWidget(self.avg_radio)
        method_row.addWidget(self.sigma_radio)
        method_row.addWidget(QLabel("κ:"))
        method_row.addWidget(self.kappa_box)
        method_row.addStretch(1)
        method_wrap = QWidget()
        method_wrap.setLayout(method_row)
        form.addRow("Integration", method_wrap)
        form.addRow("Output", _picker_row(self.output_edit, self._browse_output))

        self._stack_btn = QPushButton("Extract")
        self._stack_btn.setObjectName("primary")
        self._stack_btn.clicked.connect(self.run)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self._stack_btn)
        buttons.addWidget(close_btn)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self.table)
        root.addWidget(self.progress)
        root.addWidget(self.status)
        root.addLayout(buttons)

    # --- browse ---
    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Folder of raw subs", start_dir(self._settings.base_dir))
        if path:
            self.folder_edit.setText(path)
            if not self.output_edit.text().strip():
                self.output_edit.setText(os.path.join(path, "HaOIII_master.fits"))
            self.grade()

    def _browse_output(self) -> None:
        path = QFileDialog.getSaveFileName(self, "Master FITS", start_dir(self._settings.base_dir), "FITS (*.fits)")[0]
        if path:
            self.output_edit.setText(path)

    def _discover(self) -> list:
        folder = self.folder_edit.text().strip()
        files: list = []
        for pat in ("*.fit", "*.fits", "*.fts"):
            files.extend(glob.glob(os.path.join(folder, pat)))
        return sorted(files)

    # --- busy ---
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._stack_btn.setEnabled(not busy)

    # --- grade ---
    def grade(self) -> None:
        if self._busy:
            return
        paths = self._discover()
        if not paths:
            self.status.setText("No .fit subs found in that folder.")
            return
        self.status.setText("Grading frames…")
        self._set_busy(True)
        runner = self._grade_runner

        def work():
            return runner(paths, on_progress=lambda i, n, name:
                          self._signals.progress.emit(i, n, "grading"))

        run_async(self._pool, work, self._on_graded, self._on_error)

    def _on_graded(self, stats) -> None:
        self._set_busy(False)
        self._stats = stats
        self.table.setRowCount(len(stats))
        for row, s in enumerate(stats):
            check = QTableWidgetItem()
            check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked if s.included else Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, check)
            self.table.setItem(row, 1, QTableWidgetItem(os.path.basename(s.path)))
            self.table.setItem(row, 2, QTableWidgetItem(str(s.star_count)))
            self.table.setItem(row, 3, QTableWidgetItem(f"{s.fwhm:.1f}"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{s.background:.3f}"))
        kept = sum(1 for s in stats if s.included)
        self.status.setText(f"Graded {len(stats)} frames — {kept} kept.")

    # --- run ---
    def _included_best_first(self) -> list:
        chosen = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked:
                chosen.append(self._stats[row])
        chosen.sort(key=lambda s: s.score, reverse=True)
        return [s.path for s in chosen]

    def run(self) -> None:
        if self._busy:
            self.status.setText("Please wait — still working…")
            return
        if not self.output_edit.text().strip():
            self.status.setText("Pick an output path.")
            return
        include = self._included_best_first()
        if len(include) < 3:
            self.status.setText("Select at least 3 frames to extract.")
            return
        method = "sigma_clip" if self.sigma_radio.isChecked() else "average"
        opts = HaOIIIOptions(method, KAPPA[self.kappa_box.currentText()],
                             include, self.output_edit.text().strip())
        runner = self._extract_runner
        self.status.setText("Extracting…")
        self._set_busy(True)

        def work():
            return runner(opts, on_progress=lambda i, n, label:
                          self._signals.progress.emit(i, n, label))

        run_async(self._pool, work, self._on_done, self._on_error)

    def _on_progress(self, i: int, n: int, label: str) -> None:
        self.progress.setMaximum(max(1, n))
        self.progress.setValue(i)
        self.status.setText(f"{label}… {i}/{n}")

    def _on_done(self, result) -> None:
        self._set_busy(False)
        self.status.setText(
            f"Done — {result.frame_count} frames, "
            f"{len(result.rejected)} rejected → {os.path.basename(result.output_path)}"
        )
        if self._on_master is not None:
            self._on_master(result.image)
        self.accept()

    def _on_error(self, exc) -> None:
        self._set_busy(False)
        self.status.setText(f"Failed: {exc}")
