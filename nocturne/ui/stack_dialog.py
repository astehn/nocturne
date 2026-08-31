from __future__ import annotations

import os

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QCheckBox, QMessageBox, QProgressBar, QPushButton, QRadioButton, QSplitter, QTableWidget,
    QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core.tasks import CancelToken, Cancelled, clear_ambient, set_ambient
from ..settings import astap_valid, start_dir
from ..stacking.frames import discover_subs
from ..stacking.grade import grade_frames, judge, order_best_first
from ..stacking.mosaic import (MosaicOptions, discover_panels, read_pointings,
                               run_mosaic)
from ..stacking.stacker import StackOptions, run_stack, master_filename
from . import theme
from .frame_preview import FramePreview
from .frame_preview_controller import FramePreviewController
from .worker import run_async
from . import file_dialogs

KAPPA = {"Low": 3.0, "Medium": 2.5, "High": 2.0}
# The verdict is the last column and _rejudge rewrites it in place. Named
# because it was a bare 5 in two places and adding the Round column moved it —
# a literal index would have written verdicts into the Bg cell.
_VERDICT_COL = 6


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
        self.setMinimumSize(800, 500)
        self.resize(1100, 700)
        self._settings = settings
        self._on_master = on_master
        self._grade_runner = grade_frames  # injectable for tests
        self._stack_runner = run_stack      # injectable for tests
        self._mosaic_runner = run_mosaic    # injectable for tests
        self._stats = []
        self._busy = False
        self._active_token: CancelToken | None = None
        self._output_user_edited = False
        self._pool = QThreadPool.globalInstance()
        self._signals = _Signals()
        self._signals.progress.connect(self._on_progress)

        self.folder_edit = QLineEdit()
        self.output_edit = QLineEdit()
        self.output_edit.textEdited.connect(self._mark_output_edited)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Use", "File", "Stars", "FWHM", "Round", "Bg", "Verdict"])
        hdr = self.table.horizontalHeader()
        for col in (0, 2, 3, 4, 5):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        for col in (1, 6):                    # File and Verdict share the slack
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.avg_radio = QRadioButton("Average")
        self.sigma_radio = QRadioButton("Sigma-clipped")
        self.sigma_radio.setChecked(True)
        self.kappa_box = QComboBox()
        self.kappa_box.addItems(list(KAPPA.keys()))
        self.kappa_box.setCurrentText("Medium")
        self.drizzle_check = QCheckBox("Drizzle ×2 — more detail, much bigger")
        self.drizzle_check.toggled.connect(lambda *_: self._auto_output_path())
        self.mosaic_check = QCheckBox("Stack as mosaic")
        self.mosaic_check.setEnabled(False)
        self.mosaic_check.setToolTip(
            "Available when the subs cover more than one pointing")
        self.mosaic_check.toggled.connect(lambda _on: self._auto_output_path())
        self.crop_check = QCheckBox("Trim the ragged edges")
        self.crop_check.setChecked(True)
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

        self.preview = FramePreview()
        self.preview.setMinimumSize(300, 220)

        self._preview_ctl = FramePreviewController(
            self.preview, self._pool,
            lambda row: (self._stats[row].path
                         if self._stats and 0 <= row < len(self._stats) else None))
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

        crop_row = QHBoxLayout()
        crop_row.addWidget(self.crop_check)
        crop_row.addWidget(QLabel(
            "Off keeps the full frame — the edges are built from fewer frames, "
            "so they are noisier, but you can always crop later"))
        crop_row.addStretch(1)
        crop_wrap = QWidget()
        crop_wrap.setLayout(crop_row)
        form.addRow("Framing", crop_wrap)

        # Its own row, not squeezed alongside "Trim the ragged edges". Sharing a
        # line truncated both hints and read as an either/or choice, when they
        # are independent: a mosaic can be trimmed or not, exactly like a stack.
        mosaic_row = QHBoxLayout()
        mosaic_row.addWidget(self.mosaic_check)
        self.mosaic_hint = QLabel(
            "Several pointings assembled into one wide image — needs ASTAP, "
            "and takes considerably longer")
        self.mosaic_hint.setWordWrap(True)
        mosaic_row.addWidget(self.mosaic_hint, 1)
        mosaic_wrap = QWidget()
        mosaic_wrap.setLayout(mosaic_row)
        form.addRow("Mosaic", mosaic_wrap)

        # Its own row, like Mosaic, and for the same reason: it is a real
        # trade rather than a tick-for-free, and the hint has to have room to
        # say so. Everything AFTER the stack works on four times the pixels
        # too, which is the part people do not expect.
        drizzle_row = QHBoxLayout()
        drizzle_row.addWidget(self.drizzle_check)
        self.drizzle_hint = QLabel(
            "Rebuilds the image on a 2× grid instead of enlarging it — finer "
            "detail and more stars from well-dithered subs. Stacking takes "
            "about 10× longer, and every step afterwards works on an image four "
            "times the size.")
        self.drizzle_hint.setWordWrap(True)
        drizzle_row.addWidget(self.drizzle_hint, 1)
        drizzle_wrap = QWidget()
        drizzle_wrap.setLayout(drizzle_row)
        form.addRow("Detail", drizzle_wrap)
        self.drizzle_note = QLabel("")
        self.drizzle_note.setWordWrap(True)
        form.addRow("", self.drizzle_note)
        form.addRow("Output", _picker_row(self.output_edit, self._browse_output))

        self._stack_btn = QPushButton("Stack")
        self._stack_btn.setObjectName("primary")
        self._stack_btn.clicked.connect(self.run)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._cancel_active)
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.hide()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self._stack_btn)
        buttons.addWidget(self._cancel_btn)
        buttons.addWidget(close_btn)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.table)
        self.splitter.addWidget(self.preview)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)   # preview absorbs extra width
        self.splitter.setSizes([600, 500])
        self.splitter.setChildrenCollapsible(False)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self.splitter, 1)
        root.addWidget(self.progress)
        root.addWidget(self.status)
        root.addLayout(buttons)

    def _mark_output_edited(self, _text: str) -> None:
        self._output_user_edited = True

    # --- browse ---
    def _update_drizzle_note(self) -> None:
        """Say whether this particular set of subs would benefit.

        Advice, never a block: the gate shipped in 2026-07 with FWHM_MAX = 2.0
        while the S30 Pro sits at about 2.5 px, so it told every user their own
        camera was unsuitable. It is 3.0 now, and it still only advises.
        """
        from ..stacking.drizzle_gate import drizzle_advice
        if not self._stats:
            self.drizzle_note.setText("")
            return
        advice = drizzle_advice(self._stats)
        colour = {"recommended": theme.SUCCESS,
                  "not_recommended": theme.WARNING}.get(advice.level, theme.TEXT_DIM)
        self.drizzle_note.setText(advice.reason)
        self.drizzle_note.setStyleSheet(f"color: {colour};")

    def _browse_folder(self) -> None:
        path = file_dialogs.choose_folder(self, "Folder of subs", start_dir(self._settings.base_dir))
        if path:
            self.folder_edit.setText(path)
            self.grade()

    def _browse_output(self) -> None:
        path = file_dialogs.save_file(self, "Master FITS", start_dir(self._settings.base_dir), "FITS (*.fits)")[0]
        if path:
            self.output_edit.setText(path)
            self._output_user_edited = True

    # --- busy state ---
    def _set_busy(self, busy: bool) -> None:
        """Block the Stack button (and re-entrant runs) while async work runs, so
        two workers can't stack to the same output path at once."""
        self._busy = busy
        self._stack_btn.setEnabled(not busy)
        self._cancel_btn.setEnabled(busy)
        self._cancel_btn.setVisible(busy)

    # --- cancellable async dispatch ---
    def _start(self, work, on_done, status: str) -> None:
        token = CancelToken()
        self._active_token = token
        self.status.setText(status)
        self._set_busy(True)

        def wrapped():
            set_ambient(token)
            try:
                return work()
            finally:
                clear_ambient()

        run_async(self._pool, wrapped, on_done, self._on_error)

    def _cancel_active(self) -> None:
        tok = self._active_token
        if tok is not None:
            tok.cancel()

    def scan_pointings(self) -> None:
        """Notice a mosaic and say so.

        Nothing in this dialog distinguished 400 subs of one field from 400
        across twenty pointings, so a user who shot a mosaic got a stack of the
        whole lot registered to one frame — which cannot work. Reading the
        pointings is header-only and costs about 0.2 s for 400 subs.
        """
        folder = self.folder_edit.text().strip()
        paths = discover_subs(folder) if folder else []
        panels = discover_panels(read_pointings(paths), 0.56) if paths else []

        if len(panels) < 2:
            self.mosaic_check.setChecked(False)
            self.mosaic_check.setEnabled(False)
            self.mosaic_check.setText("Stack as mosaic")
            self.mosaic_check.setToolTip(
                "These subs all cover one pointing — an ordinary stack is right")
            return

        self.mosaic_check.setText(f"Stack as mosaic — {len(panels)} pointings")
        if not astap_valid(self._settings):
            self.mosaic_check.setChecked(False)
            self.mosaic_check.setEnabled(False)
            self.mosaic_check.setToolTip(
                "A mosaic is placed on the sky by plate solving, so it needs "
                "ASTAP — set its path in Settings")
            return
        self.mosaic_check.setEnabled(True)
        self.mosaic_check.setToolTip(
            "Stack each pointing separately, plate-solve them, and assemble one "
            "wide image")

    # --- grade ---
    def grade(self) -> None:
        if self._busy:
            return
        folder = self.folder_edit.text().strip()
        paths = discover_subs(folder) if folder else []
        if not paths:
            self.status.setText("No .fit subs found in that folder.")
            return
        self.scan_pointings()
        runner = self._grade_runner
        strictness = self.strictness_box.currentText().lower()

        def work():
            return runner(paths, on_progress=lambda i, n, name:
                          self._signals.progress.emit(i, n, "grading"),
                          strictness=strictness)

        self._start(work, self._on_graded,
                    "Measuring every frame — this is the slow part, and your "
                    "Strictness and Integration choices apply instantly afterwards.")

    def _on_graded(self, stats) -> None:
        # Strictness may have changed while the async measure was running —
        # re-judge against the knob's current value before painting anything.
        judge(stats, self.strictness_box.currentText().lower())
        self._active_token = None
        self._set_busy(False)
        self._stats = stats
        self._update_drizzle_note()
        self._user_touched = set()
        self._updating_table = True

        def _cell(text: str) -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setToolTip(text)
            return it

        try:
            self.table.setRowCount(len(stats))
            for row, s in enumerate(stats):
                check = QTableWidgetItem()
                check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                check.setCheckState(Qt.CheckState.Checked if s.included else Qt.CheckState.Unchecked)
                self.table.setItem(row, 0, check)
                self.table.setItem(row, 1, _cell(os.path.basename(s.path)))
                self.table.setItem(row, 2, _cell(str(s.star_count)))
                self.table.setItem(row, 3, _cell(f"{s.fwhm:.1f}"))
                # "Round" is elongation: 1.00 is circular, higher is trailed.
                # Shown because a "stars trailed" rejection is unreadable
                # without the number that caused it.
                self.table.setItem(row, 4, _cell(f"{s.elongation:.2f}"))
                self.table.setItem(row, 5, _cell(f"{s.background:.3f}"))
                self.table.setItem(row, _VERDICT_COL, _cell(self._verdict_text(s)))
                self._tint_row(row, s)
        finally:
            self._updating_table = False
        self.status.setText(self._selection_summary())
        self._auto_output_path()
        self._resync_preview()

    # The preview machinery moved to FramePreviewController so Ha/OIII could have
    # it too; these keep the dialog's own surface unchanged.
    @property
    def _preview_cache(self):
        return self._preview_ctl.cache

    @property
    def _preview_loader(self):
        return self._preview_ctl.loader

    @_preview_loader.setter
    def _preview_loader(self, fn):
        self._preview_ctl.loader = fn

    @property
    def _preview_wanted(self):
        return self._preview_ctl.wanted

    def _show_preview(self, row: int) -> None:
        self._preview_ctl.show_row(row)

    def _resync_preview(self) -> None:
        self._preview_ctl.resync(self.table.currentRow())

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
                verdict = self.table.item(row, _VERDICT_COL)
                verdict.setText(self._verdict_text(s))
                verdict.setToolTip(verdict.text())
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
                               sum(s.exposure for s in kept),
                               mosaic=self.mosaic_check.isChecked(),
                               drizzle=self.drizzle_check.isChecked())
        self.output_edit.setText(os.path.join(folder, name))

    @staticmethod
    def _verdict_text(s) -> str:
        if s.reason:
            return s.reason
        if s.warning:
            return s.warning
        return "OK"

    def _tint_row(self, row: int, s) -> None:
        default = QColor(theme.TEXT)
        colour = None
        if s.reason:
            colour = QColor(theme.TEXT_FAINT)   # rejected: dimmed
        elif s.warning:
            colour = QColor(theme.WARNING)      # kept with warning: amber
        for col in range(1, self.table.columnCount()):
            item = self.table.item(row, col)
            if item is not None:
                item.setForeground(colour if colour is not None else default)

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
        usable = sum(1 for s in self._stats if not s.error)
        if 0 < usable < 5:
            text += " (too few frames to grade reliably — keeping all)"
        return text + "."

    # --- run ---
    def _included_paths_best_first(self) -> list:
        chosen = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked:
                chosen.append(self._stats[row])
        return order_best_first(chosen)

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
        if self.drizzle_check.isChecked():
            method = "drizzle"      # drizzle does its own sigma-clip rejection
        else:
            method = "sigma_clip" if self.sigma_radio.isChecked() else "average"

        if self.mosaic_check.isChecked():
            mosaic_opts = MosaicOptions(
                include=include, output_path=self.output_edit.text().strip(),
                astap_path=self._settings.astap_path, method=method,
                kappa=KAPPA[self.kappa_box.currentText()],
                autocrop=self.crop_check.isChecked())
            mosaic_runner = self._mosaic_runner

            def mosaic_work():
                return mosaic_runner(mosaic_opts, on_progress=lambda i, n, label:
                                     self._signals.progress.emit(i, n, label))

            self._start(mosaic_work, self._on_stacked,
                        "Stacking each pointing, then assembling the mosaic — "
                        "this takes considerably longer than one stack.")
            return

        opts = StackOptions(method, KAPPA[self.kappa_box.currentText()],
                            include, self.output_edit.text().strip(),
                            autocrop=self.crop_check.isChecked())
        runner = self._stack_runner

        def work():
            return runner(opts, on_progress=lambda i, n, label:
                          self._signals.progress.emit(i, n, label))

        self._start(work, self._on_stacked, "Stacking…")

    def _on_progress(self, i: int, n: int, label: str) -> None:
        self.progress.setMaximum(max(1, n))
        self.progress.setValue(i)
        # The bar refills once per phase; the label carries "Step N of M" so a
        # restart reads as progress rather than as a hang. A mosaic's phases
        # count panels, and saying "frames" there is just wrong.
        noun = "panels" if "panel" in label else "frames"
        self.status.setText(f"{label} — {i}/{n} {noun}")

    @staticmethod
    def _stack_report(result) -> str:
        # A mosaic and an ordinary stack finish through the SAME handler, and
        # their results name the skipped-frame list differently: StackResult has
        # `rejected`, MosaicResult has `dropped`. Reading only `rejected` raised
        # AttributeError here — before the image was handed to the editor and
        # before the dialog closed — so a finished mosaic went nowhere and the
        # user had to close the window and open the file by hand. Reported as an
        # annoyance; it was an unhandled exception.
        skipped = getattr(result, "rejected", None)
        if skipped is None:
            skipped = getattr(result, "dropped", [])
        panels = getattr(result, "panel_count", None)
        mins = result.integration_seconds / 60
        what = (f"assembled {panels} panels from {result.frame_count} frames"
                if panels is not None else
                f"stacked {result.frame_count} frames")
        text = ("Done — " + what
                + (f" ({mins:.0f} minutes of light)" if mins >= 1 else "")
                + f" → {os.path.basename(result.output_path)}")
        unaligned = [(p, r) for p, r in skipped
                     if r.startswith("registration failed")]
        other = [(p, r) for p, r in skipped
                 if not r.startswith("registration failed")]
        if unaligned:
            names = ", ".join(os.path.basename(p) for p, _ in unaligned)
            text += f"\n{len(unaligned)} frame(s) couldn't be aligned and were skipped: {names}"
        if other:
            names = ", ".join(os.path.basename(p) for p, _ in other)
            text += f"\n{len(other)} frame(s) skipped: {names}"
        return text

    def _on_stacked(self, result) -> None:
        self._active_token = None
        self._set_busy(False)
        report = self._stack_report(result)
        self.status.setText(report)
        if getattr(result, "rejected", None) or getattr(result, "dropped", None):
            QMessageBox.information(self, "Stack finished", report)
        if self._on_master is not None:
            self._on_master(result.image)
        self.accept()  # hand off done — close the dialog (master is now in the editor)

    def _on_error(self, exc) -> None:
        if isinstance(exc, Cancelled):
            self._active_token = None
            self._set_busy(False)
            self.status.setText("Cancelled.")
            return
        self._set_busy(False)
        self.status.setText(f"Failed: {exc}")
