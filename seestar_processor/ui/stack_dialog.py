from __future__ import annotations

import os

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..stacking.frames import discover_subs
from ..stacking.grade import grade_frames
from ..stacking.stacker import StackOptions, run_stack
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


class StackDialog(QDialog):
    def __init__(self, settings, parent=None, on_master=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Stack subframes")
        self.setMinimumWidth(560)
        self._settings = settings
        self._on_master = on_master
        self._grade_runner = grade_frames  # injectable for tests
        self._stack_runner = run_stack      # injectable for tests
        self._stats = []
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
        form.addRow("Folder of subs", _picker_row(self.folder_edit, self._browse_folder))

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

        stack_btn = QPushButton("Stack")
        stack_btn.setObjectName("primary")
        stack_btn.clicked.connect(self.run)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(stack_btn)
        buttons.addWidget(close_btn)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self.table)
        root.addWidget(self.progress)
        root.addWidget(self.status)
        root.addLayout(buttons)

    # --- browse ---
    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Folder of subs")
        if path:
            self.folder_edit.setText(path)
            if not self.output_edit.text().strip():
                self.output_edit.setText(os.path.join(path, "master.fits"))
            self.grade()

    def _browse_output(self) -> None:
        path = QFileDialog.getSaveFileName(self, "Master FITS", "", "FITS (*.fits)")[0]
        if path:
            self.output_edit.setText(path)

    # --- grade ---
    def grade(self) -> None:
        folder = self.folder_edit.text().strip()
        paths = discover_subs(folder) if folder else []
        if not paths:
            self.status.setText("No .fit subs found in that folder.")
            return
        self.status.setText("Grading frames…")
        runner = self._grade_runner

        def work():
            return runner(paths, on_progress=lambda i, n, name:
                          self._signals.progress.emit(i, n, "grading"))

        run_async(self._pool, work, self._on_graded, self._on_error)

    def _on_graded(self, stats) -> None:
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
    def _included_paths_best_first(self) -> list:
        chosen = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked:
                chosen.append(self._stats[row])
        chosen.sort(key=lambda s: s.score, reverse=True)  # best first
        return [s.path for s in chosen]

    def run(self) -> None:
        if not self.output_edit.text().strip():
            self.status.setText("Pick an output path.")
            return
        include = self._included_paths_best_first()
        if len(include) < 3:
            self.status.setText("Select at least 3 frames to stack.")
            return
        method = "sigma_clip" if self.sigma_radio.isChecked() else "average"
        opts = StackOptions(method, KAPPA[self.kappa_box.currentText()],
                            include, self.output_edit.text().strip())
        runner = self._stack_runner
        self.status.setText("Stacking…")

        def work():
            return runner(opts, on_progress=lambda i, n, label:
                          self._signals.progress.emit(i, n, label))

        run_async(self._pool, work, self._on_stacked, self._on_error)

    def _on_progress(self, i: int, n: int, label: str) -> None:
        self.progress.setMaximum(max(1, n))
        self.progress.setValue(i)
        self.status.setText(f"{label}… {i}/{n}")

    def _on_stacked(self, result) -> None:
        self.status.setText(
            f"Done — {result.frame_count} frames, "
            f"{len(result.rejected)} rejected → {os.path.basename(result.output_path)}"
        )
        if self._on_master is not None:
            self._on_master(result.image)

    def _on_error(self, exc) -> None:
        self.status.setText(f"Failed: {exc}")
