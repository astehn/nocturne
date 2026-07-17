from __future__ import annotations

import os

import numpy as np

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core.autostretch import autostretch
from ..core.image import AstroImage
from ..stacking.frames import discover_subs, load_sub
from ..stacking.grade import grade_frames, judge
from ..stacking.stacker import StackOptions, run_stack, master_filename
from . import theme
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
        self._busy = False
        self._output_user_edited = False
        self._pool = QThreadPool.globalInstance()
        self._signals = _Signals()
        self._signals.progress.connect(self._on_progress)

        self.folder_edit = QLineEdit()
        self.output_edit = QLineEdit()
        self.output_edit.textEdited.connect(self._mark_output_edited)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Use", "File", "Stars", "FWHM", "Bg", "Verdict"])
        self.avg_radio = QRadioButton("Average")
        self.sigma_radio = QRadioButton("Sigma-clipped")
        self.sigma_radio.setChecked(True)
        self.kappa_box = QComboBox()
        self.kappa_box.addItems(list(KAPPA.keys()))
        self.kappa_box.setCurrentText("Medium")
        self.strictness_box = QComboBox()
        self.strictness_box.addItems(["Relaxed", "Normal", "Strict"])
        self.strictness_box.setCurrentText("Normal")
        self.strictness_box.currentTextChanged.connect(self._rejudge)
        self._user_touched: set[int] = set()
        self._updating_table = False
        self.table.itemChanged.connect(self._on_item_changed)
        self.progress = QProgressBar()
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.preview = QLabel("Select a frame\nto preview it")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(300, 220)
        self.preview.setObjectName("framePreview")

        self._preview_cache: dict[str, QPixmap] = {}
        self._preview_wanted = ""            # stale-result guard
        self._preview_loader = self._load_preview_array   # injectable for tests
        self.table.currentCellChanged.connect(
            lambda row, _c, _pr, _pc: self._show_preview(row))

        form = QFormLayout()
        form.addRow("Folder of subs", _picker_row(self.folder_edit, self._browse_folder))

        strict_row = QHBoxLayout()
        strict_row.addWidget(self.strictness_box)
        strict_row.addWidget(QLabel("How picky the automatic frame selection is"))
        strict_row.addStretch(1)
        strict_wrap = QWidget()
        strict_wrap.setLayout(strict_row)
        form.addRow("Strictness", strict_wrap)

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

        self._stack_btn = QPushButton("Stack")
        self._stack_btn.setObjectName("primary")
        self._stack_btn.clicked.connect(self.run)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self._stack_btn)
        buttons.addWidget(close_btn)

        table_row = QHBoxLayout()
        table_row.addWidget(self.table, 1)
        table_row.addWidget(self.preview)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addLayout(table_row)
        root.addWidget(self.progress)
        root.addWidget(self.status)
        root.addLayout(buttons)

    def _mark_output_edited(self, _text: str) -> None:
        self._output_user_edited = True

    # --- browse ---
    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Folder of subs")
        if path:
            self.folder_edit.setText(path)
            self.grade()

    def _browse_output(self) -> None:
        path = QFileDialog.getSaveFileName(self, "Master FITS", "", "FITS (*.fits)")[0]
        if path:
            self.output_edit.setText(path)
            self._output_user_edited = True

    # --- busy state ---
    def _set_busy(self, busy: bool) -> None:
        """Block the Stack button (and re-entrant runs) while async work runs, so
        two workers can't stack to the same output path at once."""
        self._busy = busy
        self._stack_btn.setEnabled(not busy)

    # --- grade ---
    def grade(self) -> None:
        if self._busy:
            return
        folder = self.folder_edit.text().strip()
        paths = discover_subs(folder) if folder else []
        if not paths:
            self.status.setText("No .fit subs found in that folder.")
            return
        self.status.setText("Grading frames…")
        self._set_busy(True)
        runner = self._grade_runner
        strictness = self.strictness_box.currentText().lower()

        def work():
            return runner(paths, on_progress=lambda i, n, name:
                          self._signals.progress.emit(i, n, "grading"),
                          strictness=strictness)

        run_async(self._pool, work, self._on_graded, self._on_error)

    def _on_graded(self, stats) -> None:
        self._set_busy(False)
        self._stats = stats
        self._user_touched = set()
        self._updating_table = True
        try:
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
                self.table.setItem(row, 5, QTableWidgetItem(self._verdict_text(s)))
                self._tint_row(row, s)
        finally:
            self._updating_table = False
        self.status.setText(self._selection_summary())
        self._auto_output_path()

    def _on_item_changed(self, item) -> None:
        if self._updating_table or item.column() != 0:
            return
        self._user_touched.add(item.row())
        if self._stats:
            self.status.setText(self._sync_included_and_summarize())
            self._auto_output_path()

    def _sync_included_and_summarize(self) -> str:
        for row in range(self.table.rowCount()):
            checked = self.table.item(row, 0).checkState() == Qt.CheckState.Checked
            self._stats[row].included = checked
        return self._selection_summary()

    def _rejudge(self, _text=None) -> None:
        if not self._stats:
            return
        judge(self._stats, self.strictness_box.currentText().lower())
        self._updating_table = True
        try:
            for row, s in enumerate(self._stats):
                if row not in self._user_touched:
                    self.table.item(row, 0).setCheckState(
                        Qt.CheckState.Checked if s.included else Qt.CheckState.Unchecked)
                else:
                    s.included = (self.table.item(row, 0).checkState()
                                  == Qt.CheckState.Checked)
                self.table.item(row, 5).setText(self._verdict_text(s))
                self._tint_row(row, s)
        finally:
            self._updating_table = False
        self.status.setText(self._selection_summary())
        self._auto_output_path()

    def _auto_output_path(self) -> None:
        if self._output_user_edited or not self._stats:
            return
        folder = self.folder_edit.text().strip()
        kept = [s for s in self._stats if s.included]
        exposures = [s.exposure for s in kept if s.exposure > 0]
        exposure = exposures[0] if exposures and max(exposures) == min(exposures) else 0.0
        target = next((s.target for s in kept if s.target), "")
        name = master_filename(target, len(kept), exposure,
                               sum(s.exposure for s in kept))
        self.output_edit.setText(os.path.join(folder, name))

    @staticmethod
    def _verdict_text(s) -> str:
        if s.reason:
            return s.reason
        if s.warning:
            return s.warning
        return "OK"

    def _tint_row(self, row: int, s) -> None:
        colour = None
        if s.reason:
            colour = QColor(theme.TEXT_FAINT)   # rejected: dimmed
        elif s.warning:
            colour = QColor(theme.WARNING)      # kept with warning: amber
        for col in range(1, self.table.columnCount()):
            item = self.table.item(row, col)
            if item is not None:
                item.setForeground(colour) if colour else item.setForeground(QColor(theme.TEXT))

    def _selection_summary(self) -> str:
        total = len(self._stats)
        kept = [s for s in self._stats if s.included]
        text = f"Keeping {len(kept)} of {total} frames"
        kept_s = sum(s.exposure for s in kept)
        all_s = sum(s.exposure for s in self._stats)
        if all_s > 0:
            unit = "minute" if round(all_s / 60) == 1 else "minutes"
            text += (f" — {max(1, round(kept_s / 60))} of "
                     f"{max(1, round(all_s / 60))} {unit} of light")
        if 0 < total < 5:
            text += " (too few frames to grade reliably — keeping all)"
        return text + "."

    # --- preview ---
    @staticmethod
    def _load_preview_array(path: str) -> np.ndarray:
        """Small autostretched RGB array for a sub (debayer + display stretch)."""
        img = load_sub(path)                       # normalized + debayered
        data = img.data
        step = max(1, data.shape[1] // 512)        # downsample for speed
        small = data[::step, ::step]
        return autostretch(AstroImage(small, is_linear=img.is_linear,
                                      metadata=dict(img.metadata)))

    def _show_preview(self, row: int) -> None:
        if not self._stats or not (0 <= row < len(self._stats)):
            return
        path = self._stats[row].path
        self._preview_wanted = path
        cached = self._preview_cache.get(path)
        if cached is not None:
            self.preview.setPixmap(cached)
            return
        loader = self._preview_loader

        def work():
            return path, loader(path)

        run_async(self._pool, work, self._on_preview, self._on_preview_error)

    def _on_preview(self, result) -> None:
        path, arr = result
        arr8 = (np.clip(arr, 0.0, 1.0) * 255).astype(np.uint8)
        if arr8.ndim == 2:
            arr8 = np.stack([arr8] * 3, axis=2)
        arr8 = np.ascontiguousarray(arr8)
        h, w = arr8.shape[:2]
        image = QImage(arr8.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        pix = QPixmap.fromImage(image).scaled(
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        if len(self._preview_cache) > 32:
            self._preview_cache.clear()            # simple bound; tiny pixmaps
        self._preview_cache[path] = pix
        if path == self._preview_wanted:
            self.preview.setPixmap(pix)

    def _on_preview_error(self, exc) -> None:
        self.preview.setText("Preview failed:\ncould not read frame")

    # --- run ---
    def _included_paths_best_first(self) -> list:
        chosen = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked:
                chosen.append(self._stats[row])
        chosen.sort(key=lambda s: s.score, reverse=True)  # best first
        return [s.path for s in chosen]

    def run(self) -> None:
        if self._busy:
            self.status.setText("Please wait — still working…")
            return
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
        self._set_busy(True)

        def work():
            return runner(opts, on_progress=lambda i, n, label:
                          self._signals.progress.emit(i, n, label))

        run_async(self._pool, work, self._on_stacked, self._on_error)

    def _on_progress(self, i: int, n: int, label: str) -> None:
        self.progress.setMaximum(max(1, n))
        self.progress.setValue(i)
        self.status.setText(f"{label}… {i}/{n}")

    def _on_stacked(self, result) -> None:
        self._set_busy(False)
        self.status.setText(
            f"Done — {result.frame_count} frames, "
            f"{len(result.rejected)} rejected → {os.path.basename(result.output_path)}"
        )
        if self._on_master is not None:
            self._on_master(result.image)
        self.accept()  # hand off done — close the dialog (master is now in the editor)

    def _on_error(self, exc) -> None:
        self._set_busy(False)
        self.status.setText(f"Failed: {exc}")
