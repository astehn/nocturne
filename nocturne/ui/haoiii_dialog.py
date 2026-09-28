from __future__ import annotations

import glob
import os

from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from ..core.tasks import CancelToken, Cancelled, clear_ambient, set_ambient
from ..settings import start_dir
from ..stacking.grade import ONLY_MASTERS, grade_frames, is_left_out, judge, order_best_first
from ..stacking.haoiii import HaOIIIOptions, run_haoiii_extract
from .frame_browser import FrameBrowser
from .option_band import PICKY_NOTE, TRIM_NOTE, OptionBand, WrappedNote
from .quality_chart import CHART_ROOM_MIN
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


def _line(*widgets) -> QHBoxLayout:
    line = QHBoxLayout()
    line.setContentsMargins(0, 0, 0, 0)
    for w in widgets:
        line.addWidget(w)
    line.addStretch(1)
    return line


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
    def __init__(self, settings, parent=None, on_master=None,
                 on_settings_changed=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ha/OIII extract")
        self.setMinimumWidth(560)
        # Stack's opening size. Left to its size hint it opened 832 px wide
        # (cocoa), a 351 px list with Verdict behind a scrollbar; 700 tall
        # fits the 800 px laptop with the options open (688 px needed, cocoa).
        self.resize(1100, 700)
        self._settings = settings
        self._on_master = on_master
        self._on_settings_changed = on_settings_changed
        self._grade_runner = grade_frames       # injectable for tests
        self._extract_runner = run_haoiii_extract  # injectable for tests
        self._stats = []
        self._busy = False
        self._active_token = None
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
        # OFF by default. Trimming is NOT recoverable — the outer data is gone
        # and getting it back means re-stacking, which is hours for a large set
        # and most of a day for a drizzle. Leaving it is recoverable for the
        # price of one click, because Trim exists for exactly that.
        #
        # The counter-argument is real and loses on that asymmetry: a novice
        # opening an untrimmed master sees ragged edges and may think something
        # is broken. But the one place it actually costs them — background
        # extraction fitting its gradient over black corners — already warns and
        # says to crop first (main_window._warn_uncovered), and no warning can
        # undo a destructive default.
        self.crop_check = QCheckBox("Trim the ragged edges")
        self.crop_check.setChecked(False)
        self.crop_check.setToolTip(
            "Frames drift between exposures, so the border is covered by only some of "
            "them. Trimming cuts back to where every frame contributed; untick it to "
            "keep those thinner pixels.")
        self.channels_check = QCheckBox("Also write separate Ha and OIII files")
        self.channels_check.setToolTip(
            "Writes each gas as its own mono FITS beside the master, un-equalised "
            "— OIII stays as faint as it really is, so you choose the balance when "
            "you recombine them. For taking the channels into another tool.")
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
        # The same list + preview Stack hosts (spec 2026-09-27 §2.5).
        self.browser = FrameBrowser(self._pool)
        self.browser.view.setToolTip(
            "One row per sub: when it was taken, how many stars it showed and "
            "how sharp they were (FWHM, lower is better). Verdict says why a "
            "frame was left out; hover a row for how round its stars are and "
            "how bright its sky was. Untick a frame to leave it out yourself.")
        self.preview = self.browser.preview
        self._preview_ctl = self.browser.preview_controller

        # The chart's fold, shared with Stack (quality_chart_folded).
        self.browser.chart_panel.set_folded(
            bool(getattr(settings, "quality_chart_folded", False)))
        self.browser.chart_panel.folded_changed.connect(self._on_chart_folded)

        self.progress = QProgressBar()
        self.status = QLabel("")
        self.status.setWordWrap(True)

        # Layout A, in Stack's style: one band of groups that folds, and the
        # fold is the same remembered setting (spec §2.2, §2.5).
        self.options_band = OptionBand(self._options_summary)
        frames = self.options_band.add_group("Frames")
        frames.body.addLayout(_line(QLabel("strictness:"), self.strictness_box))
        picky = QLabel(PICKY_NOTE)
        picky.setWordWrap(True)
        frames.body.addWidget(picky)
        combine = self.options_band.add_group("Combine")
        combine.body.addLayout(_line(self.avg_radio, self.sigma_radio))
        combine.body.addLayout(_line(QLabel("rejection:"), self.kappa_box))
        result = self.options_band.add_group("Result", stretch=2)
        result.body.addWidget(self.crop_check)
        result.body.addWidget(WrappedNote(TRIM_NOTE))
        result.body.addWidget(self.channels_check)
        for sig in (self.strictness_box.currentTextChanged,
                    self.kappa_box.currentTextChanged, self.sigma_radio.toggled,
                    self.crop_check.toggled, self.channels_check.toggled):
            sig.connect(lambda *_: self.options_band.refresh_summary())
        self.options_band.set_folded(bool(getattr(settings, "frame_options_folded", True)))
        self.options_band.folded_changed.connect(self._on_options_folded)

        form = QFormLayout()
        # As in Stack: the macOS style keeps fields at their size hint, which
        # cut the Output path short at every width. Fill the row.
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow("Folder of raw subs", _picker_row(self.folder_edit, self._browse_folder))
        form.addRow(self.options_band)
        form.addRow("Output", _picker_row(self.output_edit, self._browse_output))

        self._stack_btn = QPushButton("Extract")
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

        root = QVBoxLayout(self)
        root.addWidget(self.blurb)
        root.addLayout(form)
        root.addWidget(self.browser, 1)    # the frame list and preview take the height
        root.addWidget(self.progress)
        root.addWidget(self.status)
        root.addLayout(buttons)

    # --- the option band's and the chart's folds ---
    def _on_options_folded(self, folded: bool) -> None:
        self._settings.frame_options_folded = folded
        self._persist_settings()

    def _on_chart_folded(self, folded: bool) -> None:
        self._settings.quality_chart_folded = folded
        self._persist_settings()

    def _persist_settings(self) -> None:
        if self._on_settings_changed is not None:
            try:
                self._on_settings_changed()
            except OSError:
                pass      # a preference that will not save is not worth a dialog

    # --- the screen ---
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_chart()

    def _fit_chart(self) -> None:
        """Ha/OIII's one screen fold: the chart, on Stack's terms (spec
        2026-09-28 §2.4) — below CHART_ROOM_MIN, or when the dialog would not
        fit, and never once he has clicked the fold here. For this window
        only: nothing is saved."""
        panel = self.browser.chart_panel
        if panel.is_folded() or panel.user_set():
            return
        room = self._available_height()
        if room < CHART_ROOM_MIN or self.minimumSizeHint().height() > room:
            panel.set_folded(True)

    def _available_height(self) -> int:
        """Usable screen height, as Stack measures it; its own method so a
        test can shrink the screen."""
        from PySide6.QtGui import QGuiApplication

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return 1 << 20
        return screen.availableGeometry().height() - 60

    def _options_summary(self) -> str:
        parts = [f"{self.strictness_box.currentText()} selection",
                 (f"Sigma-clipped, {self.kappa_box.currentText().lower()} rejection"
                  if self.sigma_radio.isChecked() else "Average"),
                 "trim edges" if self.crop_check.isChecked() else "full frame"]
        if self.channels_check.isChecked():
            parts.append("separate Ha and OIII files")
        return " · ".join(parts)

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
        self._cancel_btn.setEnabled(busy)
        self._cancel_btn.setVisible(busy)

    # --- cancellable async dispatch ---
    def _start(self, work, on_done, status: str) -> None:
        """Every long job goes through here so it can be stopped. Grading a
        folder and extracting from it are both minutes of work; neither was
        interruptible, and the token was ambient the whole time."""
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

    # --- grade ---
    def grade(self) -> None:
        if self._busy:
            return
        paths = self._discover()
        if not paths:
            # Forget the last folder's frames, as Stack does: they stayed
            # listed and extractable after choosing a folder with none.
            self._stats = []
            self.browser.set_frames([])
            self.status.setText("No .fit subs found in that folder.")
            return
        runner = self._grade_runner
        strictness = self.strictness_box.currentText().lower()

        def work():
            return runner(paths, on_progress=lambda i, n, name:
                          self._signals.progress.emit(i, n, "grading"),
                          strictness=strictness)

        self._start(work, self._on_graded, "Grading frames…")

    def _on_graded(self, stats) -> None:
        self._set_busy(False)
        self._stats = stats
        # grade() captured Strictness when it started; if it moved while the folder
        # was being measured, the box is what the user meant.
        judge(stats, self.strictness_box.currentText().lower())
        self.browser.set_frames(stats)
        self.status.setText(self._graded_line())
        if self.isVisible():
            self._fit_chart()        # the grade is what makes the chart appear

    def _rejudge(self, _text=None) -> None:
        """Strictness is a threshold on statistics already measured, so it costs
        nothing to move — re-grading a folder for a dropdown would be minutes."""
        if not self._stats:
            return
        judge(self._stats, self.strictness_box.currentText().lower())
        self.browser.refresh_verdicts()      # a frame ticked by hand keeps its tick
        self.status.setText(self._graded_line())

    def _graded_line(self) -> str:
        """Masters and unmeasured frames are in no count (spec 2026-09-28 §3;
        Ruling R1), here as in Stack."""
        counted = [s for s in self._stats if not is_left_out(s)]
        if not counted:
            return ONLY_MASTERS
        kept = sum(1 for s in counted if s.included)
        return f"Graded {len(counted)} frames — {kept} kept."

    # --- run ---
    def _included_best_first(self) -> list:
        return order_best_first(self.browser.checked_frames())

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
                             autocrop=self.crop_check.isChecked(),
                             write_channels=self.channels_check.isChecked())
        runner = self._extract_runner

        def work():
            return runner(opts, on_progress=lambda i, n, label:
                          self._signals.progress.emit(i, n, label))

        self._start(work, self._on_done, "Extracting…")

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
        self._active_token = None
        self._set_busy(False)
        if isinstance(exc, Cancelled):
            self.status.setText("Cancelled.")
            return
        self.status.setText(f"Failed: {exc}")
