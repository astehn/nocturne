from __future__ import annotations

import glob
import os

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QProgressBar, QPushButton, QRadioButton, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..settings import start_dir
from ..stacking.grade import grade_frames, judge
from ..stacking.haoiii import HaOIIIOptions, run_haoiii_extract
from .frame_preview import FramePreview
from .frame_preview_controller import FramePreviewController
from .worker import run_async
from . import file_dialogs

KAPPA = {"Low": 3.0, "Medium": 2.5, "High": 2.0}

BLURB = (
    "Splits every <b>raw, un-debayered</b> sub into its two gases and stacks both at "
    "once — hydrogen (Ha) off the red sensor sites, oxygen (OIII) off the green and "
    "blue ones. The same folder you would hand to Stack; it will not take an "
    "already-stacked or debayered image. The master lands as one FITS with Ha in "
    "red and OIII in green and blue: process it like any other stack, then reach "
    "for <b>Narrowband</b> after the stretch to set the palette."
)


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

        self.blurb = QLabel(BLURB)
        self.blurb.setWordWrap(True)
        self.blurb.setObjectName("stepDesc")
        self.folder_edit = QLineEdit()
        self.folder_edit.setToolTip(
            "A folder of raw subs straight off the Seestar — the .fit files, not a "
            "stack, and not anything already debayered into colour.")
        self.output_edit = QLineEdit()
        self.output_edit.setToolTip(
            "Where the two-gas master FITS is written. Open it afterwards and process "
            "it like a normal stack.")
        self.strictness_box = QComboBox()
        self.strictness_box.addItems(["Relaxed", "Normal", "Strict"])
        self.strictness_box.setCurrentText("Normal")
        self.strictness_box.setToolTip(
            "How picky the automatic frame selection is. Relaxed keeps more frames for "
            "signal; Strict throws out anything soft or trailed. You can always tick "
            "frames back yourself.")
        self.strictness_box.currentTextChanged.connect(self._rejudge)
        self.crop_check = QCheckBox("Trim the ragged edges")
        self.crop_check.setChecked(True)
        self.crop_check.setToolTip(
            "Frames drift between exposures, so the border is covered by only some of "
            "them. Trimming cuts back to where every frame contributed; untick it to "
            "keep those thinner pixels.")
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Use", "File", "Stars", "FWHM", "Bg"])
        self.table.setToolTip(
            "One row per sub: how many stars it showed, how sharp they were (FWHM, "
            "lower is better) and how bright the sky was. Untick a frame to leave it out.")
        self._user_touched: set = set()
        self._updating_table = False
        self.table.itemChanged.connect(self._on_item_changed)
        self.avg_radio = QRadioButton("Average")
        self.avg_radio.setToolTip(
            "Plain mean of every frame. Slightly less noise, but a satellite or plane "
            "in one frame leaves its trail in the master.")
        self.sigma_radio = QRadioButton("Sigma-clipped")
        self.sigma_radio.setChecked(True)
        self.sigma_radio.setToolTip(
            "Averages each pixel after discarding frames that disagree with the rest — "
            "removes satellites, planes and cosmic rays. The usual choice.")
        self.kappa_box = QComboBox()
        self.kappa_box.addItems(list(KAPPA.keys()))
        self.kappa_box.setCurrentText("Medium")
        self.kappa_box.setToolTip(
            "How far a pixel may stray before it is discarded. High rejects the most "
            "and is the one to reach for when trails survive; Low keeps more signal.")
        self.preview = FramePreview()
        self.preview.setMinimumSize(300, 220)
        self._preview_ctl = FramePreviewController(
            self.preview, self._pool,
            lambda row: (self._stats[row].path
                         if self._stats and 0 <= row < len(self._stats) else None))
        self.table.currentCellChanged.connect(
            lambda row, _c, _pr, _pc: self._preview_ctl.show_row(row))

        self.progress = QProgressBar()
        self.status = QLabel("")
        self.status.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Folder of raw subs", _picker_row(self.folder_edit, self._browse_folder))

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
        crop_row = QHBoxLayout()
        crop_row.addWidget(self.crop_check)
        crop_row.addWidget(QLabel(
            "Off keeps the full frame — the edges are built from fewer frames, "
            "so they are noisier, but you can always crop later"))
        crop_row.addStretch(1)
        crop_wrap = QWidget()
        crop_wrap.setLayout(crop_row)
        form.addRow("Framing", crop_wrap)

        self._stack_btn = QPushButton("Extract")
        self._stack_btn.setObjectName("primary")
        self._stack_btn.clicked.connect(self.run)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self._stack_btn)
        buttons.addWidget(close_btn)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.table)
        self.splitter.addWidget(self.preview)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)   # preview absorbs extra width
        self.splitter.setSizes([600, 500])
        self.splitter.setChildrenCollapsible(False)

        root = QVBoxLayout(self)
        root.addWidget(self.blurb)
        root.addLayout(form)
        root.addWidget(self.splitter)
        root.addWidget(self.progress)
        root.addWidget(self.status)
        root.addLayout(buttons)

    # --- browse ---
    def _browse_folder(self) -> None:
        path = file_dialogs.choose_folder(self, "Folder of raw subs", start_dir(self._settings.base_dir))
        if path:
            self.folder_edit.setText(path)
            if not self.output_edit.text().strip():
                self.output_edit.setText(os.path.join(path, "HaOIII_master.fits"))
            self.grade()

    def _browse_output(self) -> None:
        path = file_dialogs.save_file(self, "Master FITS", start_dir(self._settings.base_dir), "FITS (*.fits)")[0]
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

        strictness = self.strictness_box.currentText().lower()

        def work():
            return runner(paths, on_progress=lambda i, n, name:
                          self._signals.progress.emit(i, n, "grading"),
                          strictness=strictness)

        run_async(self._pool, work, self._on_graded, self._on_error)

    def _on_graded(self, stats) -> None:
        self._set_busy(False)
        self._stats = stats
        # grade() captured Strictness when it started; if it moved while the folder
        # was being measured, the box is what the user meant.
        judge(stats, self.strictness_box.currentText().lower())
        self._user_touched.clear()
        self._updating_table = True
        try:
            self._fill_table(stats)
        finally:
            self._updating_table = False
        kept = sum(1 for s in stats if s.included)
        self.status.setText(f"Graded {len(stats)} frames — {kept} kept.")
        self._preview_ctl.resync(self.table.currentRow())

    def _fill_table(self, stats) -> None:
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

    def _on_item_changed(self, item) -> None:
        if not self._updating_table and item.column() == 0:
            self._user_touched.add(item.row())

    def _rejudge(self, _text=None) -> None:
        """Strictness is a threshold on statistics already measured, so it costs
        nothing to move — re-grading a folder for a dropdown would be minutes."""
        if not self._stats:
            return
        judge(self._stats, self.strictness_box.currentText().lower())
        self._updating_table = True
        try:
            for row, s in enumerate(self._stats):
                if row in self._user_touched:
                    s.included = (self.table.item(row, 0).checkState()
                                  == Qt.CheckState.Checked)
                else:
                    self.table.item(row, 0).setCheckState(
                        Qt.CheckState.Checked if s.included else Qt.CheckState.Unchecked)
        finally:
            self._updating_table = False
        kept = sum(1 for s in self._stats if s.included)
        self.status.setText(f"Graded {len(self._stats)} frames — {kept} kept.")

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
                             include, self.output_edit.text().strip(),
                             autocrop=self.crop_check.isChecked())
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
