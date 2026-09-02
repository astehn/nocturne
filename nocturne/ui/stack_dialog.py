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

# Hint text wraps here. ~65-75 characters is the comfortable measure; the old
# inline hints ran to about 130.
_HINT_WIDTH = 560


class _Hint(QLabel):
    """Wrapped explanatory text that will not be squeezed onto one line.

    A word-wrapped QLabel reports ONE LINE as its minimumSizeHint, because it
    can always shrink — so a QFormLayout short of room gives it that, and the
    rows paint over each other. Measured on the first attempt at this: sizeHints
    of 69/54/54/90 px were served 52/37/37/73, seventeen short in every case,
    which is exactly one line.

    Reporting the real wrapped height as the MINIMUM fixes it, and doing it in
    minimumSizeHint rather than setMinimumHeight means it keeps working when the
    text changes — which it does, for the drizzle gate note.
    """

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setObjectName("stepExplainer")
        self.setWordWrap(True)
        self.setFixedWidth(_HINT_WIDTH)

    def heightForWidth(self, _width: int) -> int:
        """Always answer for the width this label ACTUALLY wraps at.

        The containing row is wider than the label, so the layout asks
        heightForWidth(1030) and a plain QLabel answers for text wrapped at
        1030 — two lines where the label, fixed at 560, needs three. Every row
        then came out exactly one line short and painted over its neighbour.
        """
        return super().heightForWidth(_HINT_WIDTH)

    def minimumSizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(_HINT_WIDTH, self.heightForWidth(_HINT_WIDTH))

    def sizeHint(self):
        return self.minimumSizeHint()
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
        self._frame_shape = None
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
        self.drizzle_check.toggled.connect(
            lambda on: self._clear_other(self.mosaic_check, on))
        self.mosaic_check = QCheckBox("Stack as mosaic")
        self.mosaic_check.toggled.connect(
            lambda on: self._clear_other(self.drizzle_check, on))
        self.mosaic_check.setEnabled(False)
        self.mosaic_check.setToolTip(
            "Available when the subs cover more than one pointing")
        self.mosaic_check.toggled.connect(lambda _on: self._auto_output_path())
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

        # Every option row is built the same way: the controls on one line, and
        # any explanation on its OWN line beneath them, dimmed and wrapped to a
        # readable measure.
        #
        # It used to append the hint to the same QHBoxLayout as the control, so
        # each hint began wherever its control's label happened to end —
        # Framing at ~460px, Mosaic at ~390, Detail at ~590 — leaving the left
        # edge of the prose ragged down the whole form, and each hint sharing a
        # baseline with its control so the two read as one run-on sentence.
        # Framing's ran about 130 characters against a comfortable 65-75.
        def option_row(*controls, hint="", extra=None) -> QWidget:
            """`hint` may be text or a QLabel, so a caller that needs to reach
            it later (a test, or code that rewrites it) can keep the handle."""
            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(2)
            line = QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            for c in controls:
                line.addWidget(c)
            line.addStretch(1)
            col.addLayout(line)
            # FIXED width, not maximum. A word-wrapped QLabel cannot compute its
            # height until it knows its width, so with only a maximum it reports
            # a one-line sizeHint and the form lays the rows on top of each
            # other — which is exactly what the first attempt at this did.
            for label in (w for w in (hint, extra) if w is not None and w != ""):
                col.addWidget(label if isinstance(label, QLabel) else _Hint(label))
            wrap = QWidget()
            wrap.setLayout(col)
            return wrap

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        form.setVerticalSpacing(12)
        form.addRow("Folder of subs", _picker_row(self.folder_edit, self._browse_folder))
        form.addRow("Strictness", option_row(
            self.strictness_box,
            hint="How picky the automatic frame selection is."))
        form.addRow("Integration", option_row(
            self.avg_radio, self.sigma_radio, QLabel("κ:"), self.kappa_box,
            hint="Sigma-clipped rejects outliers — satellites, cosmic rays — "
                 "at the cost of a second pass over the frames."))
        form.addRow("Framing", option_row(
            self.crop_check,
            hint="Off keeps the full frame. The edges are built from fewer "
                 "frames, so they are noisier, but you can always crop later."))
        self.exclusive_note = _Hint("")
        self.mosaic_hint = _Hint(
            "Several pointings assembled into one wide image — needs ASTAP, "
            "and takes considerably longer.")
        form.addRow("Mosaic", option_row(self.mosaic_check, hint=self.mosaic_hint,
                                         extra=self.exclusive_note))
        # The gate's advice and the time estimate belong to this row, not to a
        # label-less row of their own — which is where the dead vertical gap
        # above Output came from.
        self.drizzle_note = _Hint("")
        self.drizzle_hint = _Hint(
            "Rebuilds the image on a 2× grid instead of enlarging it — finer "
            "detail and more stars from well-dithered subs. Stacking takes "
            "about 10× longer, and every step afterwards works on an image "
            "four times the size.")
        form.addRow("Detail", option_row(self.drizzle_check,
                                         hint=self.drizzle_hint,
                                         extra=self.drizzle_note))
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
    @staticmethod
    def _read_frame_shape(stats):
        """Sub dimensions, for the drizzle estimate. Header only — the estimate
        is not worth decoding a frame for."""
        from astropy.io import fits
        for st in stats:
            try:
                h = fits.getheader(st.path)
                if h.get("NAXIS1") and h.get("NAXIS2"):
                    return (int(h["NAXIS2"]), int(h["NAXIS1"]))
            except Exception:                    # noqa: BLE001 - estimate only
                continue
        return None

    def _update_drizzle_note(self) -> None:
        """Say whether this particular set of subs would benefit.

        Advice, never a block: the gate shipped in 2026-07 with FWHM_MAX = 2.0
        while the S30 Pro sits at about 2.5 px, so it told every user their own
        camera was unsuitable. It is 3.0 now, and it still only advises.
        """
        from ..stacking.drizzle_gate import drizzle_advice
        from ..stacking.drizzle_stack import estimate_megabytes, estimate_seconds
        if not self._stats:
            self.drizzle_note.setText("")
            return
        advice = drizzle_advice(self._stats)
        colour = {"recommended": theme.SUCCESS,
                  "not_recommended": theme.WARNING}.get(advice.level, theme.TEXT_DIM)

        # What it will cost THIS stack, before the button is pressed — Andreas
        # after a 314-frame run: "the user can actually decide for themselves if
        # its worth it prior to actually pressing the button". A generic "10x
        # longer" does not answer "do I have time for this tonight".
        kept = [x for x in self._stats if x.included]
        text = advice.reason
        if kept:
            mins = estimate_seconds(len(kept), self._frame_shape) / 60.0
            # "At least", not "about": the constant is calibrated at 60 frames
            # and is known to under-predict at scale, because both passes read
            # every frame and a large set no longer fits the page cache. An
            # estimate that reads low is worse than one that reads honest.
            when = f"{mins:.0f} minutes" if mins >= 1.5 else "a minute"
            text += (f"  ·  At least {when} for these {len(kept)} frames, "
                     f"and a master of roughly "
                     f"{estimate_megabytes(self._frame_shape):.0f} MB.")
        self.drizzle_note.setText(text)
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
        self._sync_exclusive()

    def _clear_other(self, other, turned_on: bool) -> None:
        """Turning one on turns the other off, so the LAST click wins.

        A fixed precedence would mean the box you just pressed silently losing
        to the one you pressed a minute ago; being shown what you get is better
        than being refused.
        """
        if turned_on and other.isChecked():
            other.blockSignals(True)          # not a user decision; do not recurse
            other.setChecked(False)
            other.blockSignals(False)
        self._auto_output_path()
        self._sync_exclusive()

    def _sync_exclusive(self) -> None:
        """Mosaic and Drizzle cannot both run — measured, not assumed.

        A mosaic must trim each panel before assembly, or the ragged edges are
        baked into the seams, so it forces autocrop on. Drizzle's coverage
        estimate is far more eager than an ordinary stack's, and on a real M 31
        panel (2026-09-02) the two together produced a master of 736x112 where
        the SAME six subs stacked normally give 2112x3824 — 1.4% of the frame.
        ASTAP then has nothing to solve, and the run dies four steps later with
        "fewer than two panels could be placed on the sky", after stacking every
        panel. On a 39-panel set that is hours of work to reach an error.

        Whichever the user ticked LAST wins, rather than refusing the click:
        being told "you cannot have that" by a control you just pressed is worse
        than being shown what you get instead.

        The underlying coverage bug is separate and still open — it over-trims
        ordinary drizzle stacks too, just not fatally.
        """
        clash = self.mosaic_check.isChecked() or self.drizzle_check.isChecked()
        self.exclusive_note.setText(
            "Mosaic and Drizzle cannot be combined — a mosaic has to trim each "
            "pointing, and a drizzled stack cannot be trimmed reliably yet."
            if clash and self.mosaic_check.isEnabled() else "")

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
        self._frame_shape = self._read_frame_shape(stats)
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

    def _rename_to_true_count(self, result) -> None:
        """Rename an auto-generated master to the frames it ACTUALLY contains.

        The name is built when grading finishes, from the frames grading kept.
        Registration then drops more — three of 2,037 on a real IC 1396A run —
        so the file was called ..._2037x10s_340min.fits while its own header
        said 2034 frames and 339 minutes. A descriptive filename that
        disagrees with the data is worse than a plain one, because comparing two
        masters by name is exactly what it exists for.

        Only a name this dialog generated is touched. If the path was typed or
        browsed to, it is the user's and stays as chosen.
        """
        if self._output_user_edited or not self._stats:
            return
        target = next((s.target for s in self._stats if s.included and s.target), "")
        kept = [s for s in self._stats if s.included]
        exposures = [s.exposure for s in kept if s.exposure > 0]
        exposure = exposures[0] if exposures and max(exposures) == min(exposures) else 0.0
        want = master_filename(target, result.frame_count, exposure,
                               result.integration_seconds,
                               mosaic=self.mosaic_check.isChecked(),
                               drizzle=self.drizzle_check.isChecked())
        old_path = result.output_path
        new_path = os.path.join(os.path.dirname(old_path), want)
        if new_path == old_path or not os.path.exists(old_path):
            return
        try:
            os.replace(old_path, new_path)
        except OSError:
            return          # a rename is a nicety; never fail a finished stack
        result.output_path = new_path
        self.output_edit.setText(new_path)

    def _on_stacked(self, result) -> None:
        self._active_token = None
        self._set_busy(False)
        self._rename_to_true_count(result)
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
