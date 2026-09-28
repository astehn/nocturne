from __future__ import annotations

import os

from PySide6.QtCore import QObject, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from ..core.tasks import CancelToken, Cancelled, clear_ambient, set_ambient
from ..settings import astap_valid, start_dir
from ..stacking.frames import discover_subs
from ..stacking.grade import (JUDGE_MIN, ONLY_MASTERS, STACK_MIN, grade_frames,
                              is_left_out, judge, order_best_first)
from ..stacking.mosaic import (MosaicOptions, discover_panels, read_pointings,
                               run_mosaic)
from ..stacking.reject_move import (RejectMoveError, describe_names, move_back,
                                    move_to_rejected, pending_back)
from ..stacking.stacker import StackOptions, run_stack, master_filename
from ..stacking.verdict import Verdict, build_verdict, read_pixel_scale
from . import file_dialogs, theme
from .frame_browser import FrameBrowser
from .option_band import PICKY_NOTE, TRIM_NOTE, OptionBand, WrappedNote
from .quality_chart import CHART_ROOM_MIN
from .verdict_strip import VerdictStrip
from .worker import run_async


class _Hint(WrappedNote):
    """A note in this dialog — mostly explanations "How this works" hides.

    Its own class so the help toggle finds exactly these and not the band's
    folded note, which is a plain WrappedNote. The decision notes
    (drizzle_note, exclusive_note, background_note, name_note) ARE _Hints; they
    stay on screen only because `_apply_hints_visible` names them in its
    `always` set. The old fixed 560 px width is gone with the QFormLayout rows
    it was fighting (see WrappedNote); in a group the text wraps at the group.
    """


def _line(*widgets, stretch_last: bool = True) -> QHBoxLayout:
    line = QHBoxLayout()
    line.setContentsMargins(0, 0, 0, 0)
    for w in widgets:
        line.addWidget(w)
    if stretch_last:
        line.addStretch(1)
    return line


KAPPA = {"Low": 3.0, "Medium": 2.5, "High": 2.0}
_OPEN_HEIGHT = 700      # what the dialog asks for before it knows its content


class _Signals(QObject):
    progress = Signal(int, int, str)


def _picker_row(edit: QLineEdit, on_browse) -> QWidget:
    """The field and its Browse… in one widget, so both can be disabled."""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(edit)
    btn = QPushButton("Browse…")
    btn.clicked.connect(on_browse)
    lay.addWidget(btn)
    return row


class StackDialog(QDialog):
    def __init__(self, settings, parent=None, on_master=None,
                 on_settings_changed=None, on_background=None,
                 queue_busy=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Stack subframes")
        # Height is NOT hard-coded any more, and 500 was the bug. With the
        # explanations expanded -- which was then the DEFAULT, help_expanded
        # -- this dialog's own minimumSizeHint is 844px, and it opened at 700
        # with a floor of 500. Qt then squeezed the QFormLayout's rows onto a
        # 46px stride while the rows are 54-72px tall, and because _Hint
        # refuses to shrink (it must, or the text clips) the explanations
        # painted straight over the controls beneath them: 11 overlaps
        # measured under cocoa, the worst 158x18px across "Trim the ragged
        # edges". Andreas never saw it because his help_expanded was False at
        # the time -- collapsed the dialog needs 658px and fits.
        #
        # Stack has had its own stack_help_expanded, off by default, since
        # 2026-09-28 (spec §6a); the main window's help_expanded above is a
        # separate setting, untouched by anything in this dialog.
        self.setMinimumWidth(800)
        self.resize(1100, _OPEN_HEIGHT)
        self._settings = settings
        self._on_settings_changed = on_settings_changed
        self._on_master = on_master
        self._on_background = on_background
        # Zero-arg predicate: True while ANY background job is queued or
        # running. A FRESH StackDialog starts with _busy = False and knows
        # nothing about the job queue on its own — a background stack, then a
        # second StackDialog on the same folder pressing plain Stack, resolved
        # to the SAME auto-generated output path with no guard at all. None in
        # standalone use (and most tests): nothing to check against.
        self._queue_busy = queue_busy
        self._grade_runner = grade_frames  # injectable for tests
        self._stack_runner = run_stack      # injectable for tests
        self._mosaic_runner = run_mosaic    # injectable for tests
        self._stats = []
        self._frame_shape = None
        self._busy = False
        self._active_token: CancelToken | None = None
        # The output is a folder and a name (spec 2026-09-27 §4). Both follow
        # the dialog until the user sets them, and then they are the user's.
        self._name_is_manual = False
        self._save_to_is_manual = False
        self._fitted = False       # _fit_to_content runs once, on first show
        # The screen's folds (help, then the option band) stop once the user
        # has toggled either by hand in this window: their click outranks it.
        self._user_laid_out = False
        self._hints_forced_closed = False
        self._refit_pending = False
        self._pool = QThreadPool.globalInstance()
        self._signals = _Signals()
        self._signals.progress.connect(self._on_progress)

        self.folder_edit = QLineEdit()
        self.folder_edit.textChanged.connect(self._follow_subs_folder)
        self.save_to_edit = QLineEdit()
        self.save_to_edit.setToolTip("The folder the master is written to — the "
                                     "subs folder unless you choose another")
        self.save_to_edit.textEdited.connect(self._on_save_to_typed)
        self.save_to_edit.editingFinished.connect(self._refill_save_to)
        self.name_edit = QLineEdit()
        self.name_edit.setToolTip("Named from the frames you keep, and kept up to "
                                  "date as you tick. Type your own and it stays.")
        self.name_edit.textEdited.connect(self._on_name_typed)
        self.auto_name_btn = QPushButton("↺ automatic")
        self.auto_name_btn.setObjectName("linkButton")
        self.auto_name_btn.setToolTip("Go back to the name made from your frames")
        self.auto_name_btn.clicked.connect(self._restore_automatic_name)
        self.auto_name_btn.hide()

        self.avg_radio = QRadioButton("Average")
        self.sigma_radio = QRadioButton("Sigma-clipped")
        self.sigma_radio.setChecked(True)
        self.kappa_box = QComboBox()
        self.kappa_box.addItems(list(KAPPA.keys()))
        self.kappa_box.setCurrentText("Medium")
        self.drizzle_check = QCheckBox("Drizzle ×2 — more detail, much bigger")
        self.drizzle_check.toggled.connect(lambda *_: self._auto_output_path())
        self.drizzle_check.toggled.connect(lambda *_: self._sync_exclusive())
        self.mosaic_check = QCheckBox("Stack as mosaic")
        self.mosaic_check.toggled.connect(lambda *_: self._auto_output_path())
        self.mosaic_check.toggled.connect(lambda *_: self._sync_exclusive())
        self.mosaic_check.setEnabled(False)
        self.mosaic_check.setToolTip(
            "Available when the subs cover more than one pointing")
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
        self.progress = QProgressBar()
        self.status = QLabel("")
        self.status.setWordWrap(True)

        # The frame list and its preview: the SAME component Ha/OIII hosts
        # (spec 2026-09-27 §2.5), so the two cannot drift apart again.
        self.browser = FrameBrowser(self._pool)
        self.browser.selection_changed.connect(self._on_ticks_changed)
        self.preview = self.browser.preview
        self._preview_ctl = self.browser.preview_controller

        # The chart's fold: his saved choice (quality_chart_folded, shared
        # with Ha/OIII), and one more step of _keep_on_screen's.
        self.browser.chart_panel.set_folded(
            bool(getattr(settings, "quality_chart_folded", False)))
        self.browser.chart_panel.folded_changed.connect(self._on_chart_folded)

        # The night's verdict, over the chart across the full width (spec
        # 2026-09-28 §2.4, layout C). Stack only: Ha/OIII has none.
        self.verdict_strip = VerdictStrip()
        self.browser.add_above_chart(self.verdict_strip)
        self.verdict_strip.expanded.connect(
            lambda: self._keep_on_screen() if self._fitted else None)
        self._pixel_scale: float | None = None
        # The folder the LISTED frames came from — not whatever the Folder
        # field says now: it can be retyped after grading, and anything that
        # acts on the frames' files must act on their own folder.
        self._grading_folder = ""
        self._graded_folder = ""

        # Moving the unticked frames into <folder>/rejected/ and back (spec
        # decision 7, §5). Never automatic: only these two buttons, and the
        # move only after a yes. `_confirm` is injectable so tests answer
        # without a modal, which would hang the headless suite.
        self.verdict_strip.move_requested.connect(self._move_rejected)
        self.verdict_strip.back_requested.connect(self._move_back)
        self._confirm = self._ask_yes_no
        # True once a disk check has reported the record damaged, so the NEXT
        # successful check knows to clear that specific complaint rather than
        # blindly wiping every message a disk check might run alongside —
        # "Moved N frames back" must NOT disappear the moment the routine
        # back-count check that follows it happens to succeed.
        self._damaged_folder = False
        # The names a re-grade started by "Move them back" is currently
        # measuring, or None — set for BOTH the partial re-grade
        # (_grade_restored, only the newly-restored names) and the full
        # grade a was-empty reopen falls back to (_move_back), since either
        # one leaves "Measuring N frames that came back…" standing as an
        # unresolved promise until it finishes. On success, _on_restored_graded
        # / _on_graded replace it with the move's own outcome (_move_back_result);
        # on failure or cancellation, _on_error replaces it with something
        # actionable instead of a promise the run broke.
        self._restoring_names: list[str] | None = None
        self._move_back_result = None

        # Layout A: ONE band of three groups between Folder and the output —
        # Frames · Combine · Result (spec §2.1). Each control still says what
        # it IS in its own label, so the folded summary and a collapsed help
        # both read on their own: "k:" is jargon to the person this is for.
        self.exclusive_note = _Hint("")
        self.mosaic_hint = _Hint(
            "Several pointings assembled into one wide image — needs ASTAP, "
            "and takes considerably longer.")
        self.drizzle_note = _Hint("")
        self.drizzle_hint = _Hint(
            "Rebuilds the image on a 2× grid instead of enlarging it — finer "
            "detail and more stars from well-dithered subs. Stacking takes "
            "about 10× longer, and every step afterwards works on an image "
            "four times the size.")
        self.options_band = OptionBand(self._options_summary)
        frames = self.options_band.add_group("Frames")
        frames.body.addLayout(_line(QLabel("strictness:"), self.strictness_box))
        picky = QLabel(PICKY_NOTE)
        picky.setWordWrap(True)
        frames.body.addWidget(picky)
        frames.body.addWidget(_Hint(
            "Stricter drops more frames for soft or trailed stars. Every "
            "frame's verdict is in the list below, and you can overrule it."))
        combine = self.options_band.add_group("Combine")
        combine.body.addLayout(_line(self.avg_radio, self.sigma_radio))
        combine.body.addLayout(_line(QLabel("rejection:"), self.kappa_box))
        combine.body.addWidget(_Hint(
            "Sigma-clipped rejects outliers — satellites, cosmic rays — "
            "at the cost of a second pass over the frames."))
        # Result gets the most room: three choices, and the drizzle
        # recommendation lives here (spec §2.1), not in a row of its own.
        result = self.options_band.add_group("Result", stretch=2)
        result.body.addWidget(self.crop_check)
        result.body.addWidget(_Hint(TRIM_NOTE))
        result.body.addWidget(self.mosaic_check)
        result.body.addWidget(self.mosaic_hint)
        result.body.addWidget(self.exclusive_note)
        result.body.addWidget(self.drizzle_check)
        result.body.addWidget(self.drizzle_hint)
        result.body.addWidget(self.drizzle_note)
        for sig in (self.strictness_box.currentTextChanged,
                    self.kappa_box.currentTextChanged, self.sigma_radio.toggled,
                    self.crop_check.toggled, self.mosaic_check.toggled,
                    self.drizzle_check.toggled):
            sig.connect(lambda *_: self.options_band.refresh_summary())
        self.drizzle_check.toggled.connect(lambda *_: self._sync_folded_note())
        self.options_band.set_folded(bool(getattr(settings, "frame_options_folded", True)))
        self.options_band.folded_changed.connect(self._on_options_folded)

        # The Save panel used to say "already exists — replace?"; choosing a
        # folder instead does not, so the dialog says it. Informs, never blocks:
        # replacing a master by re-stacking is a normal thing to do.
        self.name_note = _Hint("")
        name_field = QWidget()
        name_col = QVBoxLayout(name_field)
        name_col.setContentsMargins(0, 0, 0, 0)
        name_col.setSpacing(2)
        name_col.addLayout(_line(self.name_edit, self.auto_name_btn, stretch_last=False))
        name_col.addWidget(self.name_note)

        self._stack_btn = QPushButton("Stack")
        self._stack_btn.setObjectName("primary")
        self._stack_btn.clicked.connect(self.run)
        self.background_btn = QPushButton("Stack in background")
        self.background_btn.setToolTip(
            "Start the stack and close this window. It keeps running while "
            "you work; progress appears below and the master is written "
            "to disk.")
        self.background_btn.clicked.connect(self._stack_in_background)
        # Standalone (and in tests) there is nowhere to send it, so it is not
        # offered rather than offered and broken.
        self.background_btn.setVisible(on_background is not None)
        # Why it may be greyed even when offered: THIS dialog's own foreground
        # run (same output-path race _set_busy exists to prevent — see
        # _stack_in_background) or "Stack as mosaic" (the background job
        # protocol carries a plain StackOptions, see nocturne/stacking/job.py;
        # a mosaic is a different options type it cannot express, so
        # backgrounding one would silently drop the checkbox and run a flat
        # stack instead of the mosaic asked for). The mosaic reason gets a
        # visible note below the row, exclusive_note's pattern, rather than
        # living only in a tooltip.
        self.background_note = _Hint("")
        self.mosaic_check.toggled.connect(lambda *_: self._sync_background_availability())
        self._sync_background_availability()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._cancel_active)
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.hide()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons_row = QHBoxLayout()
        buttons_row.addWidget(self._stack_btn)
        buttons_row.addWidget(self.background_btn)
        buttons_row.addWidget(self._cancel_btn)
        buttons_row.addWidget(close_btn)
        buttons_col = QVBoxLayout()
        buttons_col.setContentsMargins(0, 0, 0, 0)
        buttons_col.setSpacing(2)
        buttons_col.addLayout(buttons_row)
        buttons_col.addWidget(self.background_note)

        # The same collapsible help the main window uses, with a sticky
        # setting of its own, stack_help_expanded, folded until asked for:
        # Andreas, 2026-09-28, the dialog "reads as way too busy; for a new
        # user it might be quite overwhelming" (spec 2026-09-28 §6a). The
        # main window's help_expanded, and its novice-first default, are
        # untouched by anything here.
        #
        # Not icons-with-popups: that optimises for the person who already
        # knows, at the cost of the person who does not. An explanation you
        # must know to go looking for is close to no explanation, and this app
        # is for someone who has not met sigma-clipping before.
        self._help_link = QLabel()
        self._help_link.setObjectName("stepExplainer")
        self._help_link.setTextFormat(Qt.TextFormat.RichText)
        self._help_link.linkActivated.connect(self._toggle_hints)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        form.setVerticalSpacing(8)
        # The macOS style keeps form fields at their size hint (~225 px under
        # cocoa) whatever the dialog's width, which cut an automatic name like
        # "SH2-108_204x10s_34min.fits" at the left even at 1920. Fill the row.
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow("Folder of subs", _picker_row(self.folder_edit, self._browse_folder))
        form.addRow(self.options_band)
        form.addRow(self._help_link)
        self._save_to_row = _picker_row(self.save_to_edit, self._browse_save_to)
        self._name_field = name_field
        form.addRow("Save to", self._save_to_row)
        form.addRow("Name", name_field)

        root = QVBoxLayout(self)
        root.addLayout(form)
        self._apply_hints_visible()
        root.addWidget(self.browser, 1)
        root.addWidget(self.progress)
        root.addWidget(self.status)
        root.addLayout(buttons_col)
        self._sync_folded_note()

    # --- output: a folder and a name ---
    def output_path(self) -> str:
        """Where the master will be written, or "" while there is no name.
        A name typed without an extension gets .fits — the stacker writes FITS,
        and a file with no extension is one Open will not list."""
        name = self.name_edit.text().strip()
        if not name:
            return ""
        if os.path.splitext(name)[1].lower() not in (".fit", ".fits", ".fts"):
            name += ".fits"
        folder = self.save_to_edit.text().strip() or self.folder_edit.text().strip()
        if not folder:
            return ""      # never a path relative to wherever the app was started
        # "~/Astro" is a folder to the person typing it, not to save_fits.
        return os.path.join(os.path.expanduser(folder), name)

    def _on_name_typed(self, _text: str) -> None:
        self._name_is_manual = True
        self.auto_name_btn.show()
        self._sync_name_note()

    def _on_save_to_typed(self, text: str) -> None:
        # Cleared by hand: back to following the subs folder. An empty
        # "manual" field quietly used a folder it did not display, and missed
        # every later change of subs folder.
        self._save_to_is_manual = bool(text.strip())
        self._sync_name_note()

    def _refill_save_to(self) -> None:
        # Not on every keystroke: that would refill the field the moment
        # backspace emptied it, before the user could type a new folder.
        if not self._save_to_is_manual and not self.save_to_edit.text().strip():
            self.save_to_edit.setText(self.folder_edit.text().strip())

    def _follow_subs_folder(self, folder: str) -> None:
        if not self._save_to_is_manual:
            self.save_to_edit.setText(folder.strip())
        self._sync_name_note()

    def _restore_automatic_name(self) -> None:
        self._name_is_manual = False
        self.auto_name_btn.hide()
        if not self._stats:
            # Nothing graded, nothing to name it from: a typed name left in
            # the field would pass for the automatic one.
            self.name_edit.setText("")
            self._sync_name_note()
            return
        self._auto_output_path()

    def _sync_name_note(self) -> None:
        path = self.output_path()
        self.name_note.setText(
            "A file with this name is already there — stacking will replace it."
            if path and os.path.exists(path) else "")

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
            self._sync_folded_note()
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
        self._sync_folded_note()

    def _browse_folder(self) -> None:
        path = file_dialogs.choose_folder(self, "Folder of subs", start_dir(self._settings.base_dir))
        if path:
            self.folder_edit.setText(path)
            self.grade()

    def _browse_save_to(self) -> None:
        """A folder only. The name is left exactly as it was — automatic stays
        automatic — which is the bug this replaced: Browse… used to hand back a
        whole path and the automatic name was gone (Andreas, 2026-09-27)."""
        start = self.save_to_edit.text().strip() or start_dir(self._settings.base_dir)
        path = file_dialogs.choose_folder(self, "Save the master to", start)
        if path:
            self.save_to_edit.setText(path)
            self._save_to_is_manual = True
            self._sync_name_note()

    # --- busy state ---
    def _set_busy(self, busy: bool) -> None:
        """Block the Stack button (and re-entrant runs) while async work runs, so
        two workers can't stack to the same output path at once. The
        background button gets the same guard — see _stack_in_background —
        composed with the mosaic gate in _sync_background_availability, so
        re-enabling on finish does not light it up while mosaic is checked."""
        self._busy = busy
        self._stack_btn.setEnabled(not busy)
        self._cancel_btn.setEnabled(busy)
        self._cancel_btn.setVisible(busy)
        # main_window reads output_path() when the master arrives, so an edit
        # made mid-stack would record a path the file is not at.
        self._save_to_row.setEnabled(not busy)
        self._name_field.setEnabled(not busy)
        self.verdict_strip.set_actions_enabled(not busy)
        self._sync_background_availability()

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

    def scan_pointings(self, folder: str | None = None) -> None:
        """Notice a mosaic and say so.

        Nothing in this dialog distinguished 400 subs of one field from 400
        across twenty pointings, so a user who shot a mosaic got a stack of the
        whole lot registered to one frame — which cannot work. Reading the
        pointings is header-only and costs about 0.2 s for 400 subs.

        `folder` is optional for the same reason grade()'s is: a caller that
        already knows which folder it means must pass it, so this never
        silently reads the Folder field's CURRENT text when that has nothing
        to do with the frames actually being graded.
        """
        if folder is None:
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

    def _hints_showing(self) -> bool:
        """What the link's arrow claims: explanations actually on screen.
        The preference alone is not that — the screen may have folded them
        (_keep_on_screen), and every one lives inside the option band, so a
        folded band shows none of them whatever the preference says."""
        return (bool(getattr(self._settings, "stack_help_expanded", False))
                and not self._hints_forced_closed
                and not self.options_band.is_folded())

    def _toggle_hints(self) -> None:
        # The click acts on what the link SHOWS, never on the bare preference:
        # opened folded with help on, the link read ▾ over nothing and the
        # first click saved help off and changed nothing on screen. "▸"
        # always means show. An explicit click outranks the screen's FOLD,
        # never its EDGE: the frame list gives up the height (_clamp_to_screen).
        self._user_laid_out = True
        if self._hints_showing():
            self._settings.stack_help_expanded = False
            self._persist_settings()
        else:
            self._hints_forced_closed = False
            self._settings.stack_help_expanded = True
            if self.options_band.is_folded():
                # Through the band's own signal, so it is saved like any
                # unfold the user makes — once, help included
                # (_on_options_folded). Hiding the help never folds it back.
                self.options_band.set_folded(False)
            else:
                self._persist_settings()
        self._apply_hints_visible()
        if self._fitted:
            self._keep_on_screen()

    def _persist_settings(self) -> None:
        # Persisted by whoever OWNS the settings, through the path the app was
        # actually given. Resolving the default path here wrote the whole object
        # to the real ~/.nocturne/settings.json whatever file was in use — which
        # in the test suite meant an empty Settings() landing on the developer's
        # own and wiping their configured tool paths.
        if self._on_settings_changed is not None:
            try:
                self._on_settings_changed()
            except OSError:
                pass      # a preference that will not save is not worth a dialog

    # --- the option band's fold ---
    def _on_options_folded(self, folded: bool) -> None:
        # Only the user's fold reaches here: the screen's is signal-blocked.
        self._user_laid_out = True
        self._settings.frame_options_folded = folded
        self._persist_settings()
        self._apply_hints_visible()        # the link's arrow follows the fold
        if self._fitted:
            self._keep_on_screen()

    # --- the chart's fold ---
    def _on_chart_folded(self, folded: bool) -> None:
        # Only his click reaches here; the screen's fold emits nothing.
        self._settings.quality_chart_folded = folded
        self._persist_settings()
        if self._fitted:
            self._keep_on_screen()

    def _options_summary(self) -> str:
        """The folded band in one line, e.g. "Normal selection · Sigma-clipped,
        medium rejection · full frame · Drizzle ×2"."""
        parts = [f"{self.strictness_box.currentText()} selection",
                 (f"Sigma-clipped, {self.kappa_box.currentText().lower()} rejection"
                  if self.sigma_radio.isChecked() else "Average"),
                 "trim edges" if self.crop_check.isChecked() else "full frame"]
        if self.mosaic_check.isChecked():
            parts.append("mosaic")
        if self.drizzle_check.isChecked():
            parts.append("Drizzle ×2")
        return " · ".join(parts)

    def _sync_folded_note(self) -> None:
        """Folding hides the groups, never what they warn about: the combined
        mosaic+drizzle cost, and — once Drizzle is ticked — its time and size
        estimate. The same rule `_apply_hints_visible` follows."""
        notes = [self.exclusive_note.text()]
        if self.drizzle_check.isChecked():
            notes.append(self.drizzle_note.text())
        self.options_band.set_folded_note("  ".join(n for n in notes if n))

    def _apply_hints_visible(self) -> None:
        """Show or hide every explanation, and say which state you are in.

        Measured at 1180x820: collapsing them gives the frame list — the thing
        you actually work in — 63% more height. That matters most on the small
        screens where the explanations were being clipped anyway.
        """
        # Per hint, the preference: a hint inside a folded band is invisible
        # anyway, and _natural_minimum_height needs it counted once the band
        # opens. The link says what is actually on screen.
        shown = (bool(getattr(self._settings, "stack_help_expanded", False))
                 and not self._hints_forced_closed)
        # NOT every _Hint. `drizzle_note` carries the gate's advice and the
        # "this will take N hours and write M MB" estimate, `exclusive_note`
        # says why a box you just ticked untucked another, and
        # `background_note` says why a button beside it has gone dead. Those
        # are what you decide ON, not what explains the control — hiding them
        # with the help would mean collapsing the explanations quietly removed
        # the numbers you needed to choose, or left a disabled control with no
        # reason anywhere on screen.
        always = {self.drizzle_note, self.exclusive_note, self.background_note,
                  self.name_note}
        for hint in self.findChildren(_Hint):
            if hint not in always:
                hint.setVisible(shown)
        self._help_link.setText(
            '<a href="#" style="color:#7fb2e5;text-decoration:none">'
            + ("How this works ▾" if self._hints_showing()
               else "How this works ▸") + "</a>")

    def showEvent(self, event) -> None:
        # Sizing happens HERE, not in __init__. An un-shown window does not have
        # reliable size hints -- the same trap that made the main window open at
        # 640x480 for three releases, where every measurement taken before show()
        # agreed with the code and disagreed with the screen.
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            self._fit_to_content()

    def _fit_to_content(self) -> None:
        """Open tall enough for what is actually in the dialog.

        Two things can go wrong and both are handled here. If the content needs
        more height than the dialog was given, grow it. If it needs more than
        the SCREEN has -- 844px of content against an 800px laptop, which is the
        floor this app targets -- growing is not available, so collapse the
        explanations instead of overlapping them. That is the same trade the
        collapse control already offers, and _apply_hints_visible's own note
        says it "matters most on the small screens where the explanations were
        being clipped anyway". The saved preference is left alone: this is what
        THIS window can show, not a change to what the user asked for. If the
        explanations folded away are still not enough, the option band folds
        for this window as well, on the same terms.
        """
        room = self._available_height()
        if self._keep_on_screen():
            return
        needed = self._settled_minimum_height()
        if needed > self.height():
            self.resize(self.width(), min(needed, room))

    def _keep_on_screen(self) -> bool:
        """Fold what the screen cannot hold and bring the window back down;
        True when it folded something. Help first, then the option band, then
        the chart, then the verdict's details — each for THIS window only,
        never saved, and never once the user has toggled it here. The height
        clamp after them always runs."""
        squeezed = False
        if not self._user_laid_out:
            room = self._available_height()
            needed = self._natural_minimum_height()
            if (needed > room and getattr(self._settings, "stack_help_expanded", False)
                    and not self._hints_forced_closed):
                self._hints_forced_closed = True
                self._apply_hints_visible()
                needed = self._natural_minimum_height()
                squeezed = True
            # Still too tall: fold the options for THIS window too. Not saved —
            # folded_changed is blocked — for the same reason the help is not.
            if needed > room and not self.options_band.is_folded():
                self.options_band.blockSignals(True)
                self.options_band.set_folded(True)
                self.options_band.blockSignals(False)
                self._apply_hints_visible()    # blocked, so the link is told here
                needed = self._natural_minimum_height()
                squeezed = True
            # Still too tall — or a laptop-height screen, where the list and the
            # preview need the rows more (CHART_ROOM_MIN; spec 2026-09-28 §8:
            # it starts folded at 740 px): the chart, for this window only.
            # "▸ Show chart" brings it back, and then the screen leaves it be.
            panel = self.browser.chart_panel
            if ((needed > room or room < CHART_ROOM_MIN)
                    and not panel.is_folded() and not panel.user_set()):
                panel.set_folded(True)
                needed = self._natural_minimum_height()
                squeezed = True
            # Still too tall: the verdict down to its headline, for this window
            # only. Last, because it is what the grade just told you; "details ▸"
            # brings it straight back, and then the screen leaves it alone.
            if (needed > room and not self.verdict_strip.isHidden()
                    and not self.verdict_strip.is_compact()
                    and not self.verdict_strip.user_expanded()):
                self.verdict_strip.set_compact(True)
                needed = self._natural_minimum_height()
                squeezed = True
            if squeezed:
                # Qt already grew the window to the OLD minimum when it was
                # shown, and it does not shrink by itself: measured 2026-09-27,
                # the pre-layout-A dialog stayed 825 px tall on a 740 px screen
                # after collapsing. Bring it back down to what now fits.
                self.resize(self.width(), min(max(needed, _OPEN_HEIGHT), room))
        self._clamp_to_screen()
        return squeezed

    def _natural_minimum_height(self) -> int:
        """The minimum with the frame list at its OWN floor, not the one
        _clamp_to_screen may have lowered — what the content really asks for."""
        needed = self._settled_minimum_height()
        floor = self.browser.minimumHeight()
        if floor > 0:
            needed += self.browser.minimumSizeHint().height() - floor
        return needed

    def _clamp_to_screen(self) -> None:
        """The screen's edge, which nothing outranks. The user's click can
        overrule the screen's folds, and then the content needs more than the
        screen has (842 px on a 642 px screen, measured offscreen 2026-09-27);
        the frame list is the stretch area, so it is what gives up height, and
        gets its own floor back as soon as there is room for it."""
        room = self._available_height()
        natural = self._natural_minimum_height()
        own = self.browser.minimumSizeHint().height()
        floor = 0 if natural <= room else max(1, own - (natural - room))
        if floor != self.browser.minimumHeight():
            self.browser.setMinimumHeight(floor)
            self._settled_minimum_height()
        if self.height() > room:
            self.resize(self.width(), room)

    def _settled_minimum_height(self) -> int:
        """The dialog's minimum once a show/hide has reached every nested
        layout. activate() on the top layout alone read the groups' CACHED
        minimum — 858 px with the explanations already hidden, where 567 was
        true (measured 2026-09-27) — and folded the band on a screen that had
        room for it. Innermost layouts first, so each parent sees fresh
        children."""
        for w in reversed(self.findChildren(QWidget)):
            if w.layout() is not None:
                w.layout().activate()
        self.layout().activate()
        return self.minimumSizeHint().height()

    def resizeEvent(self, event) -> None:
        # Content that arrives after opening — a grade's status line and
        # drizzle advice, a name or mosaic note — grows the window through its
        # minimum, and on the 800 px laptop past the bottom of the screen
        # (measured cocoa: 688 px empty, 766 graded with the help folded).
        # Re-fit once the layout has settled.
        super().resizeEvent(event)
        if (self._fitted and not self._refit_pending
                and self.height() > self._available_height()):
            self._refit_pending = True
            QTimer.singleShot(0, self._refit)

    def _refit(self) -> None:
        self._refit_pending = False
        self._keep_on_screen()

    def _available_height(self) -> int:
        """Usable screen height. Its own method so a test can shrink the screen —
        the small-screen branch is unreachable otherwise, and it is the branch
        that matters on the 1280x800 laptop this app targets."""
        from PySide6.QtGui import QGuiApplication

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return 1 << 20                      # no screen: never force a collapse
        return screen.availableGeometry().height() - 60   # title bar, dock, menu bar

    def _sync_exclusive(self) -> None:
        """Mosaic AND Drizzle together: allowed, and expensive.

        These two were mutually exclusive from 2026-09-02 to 2026-09-04, because
        together they produced an unusable master — a real M 31 panel came out
        736x112 where the same subs stacked normally gave 2112x3824, ASTAP had
        nothing to solve, and the run died four steps later after stacking every
        panel.

        That was drizzle's auto-crop rejecting its own interior as noise
        (`coverage.full_coverage_bounds` rounded its threshold up, which is a
        no-op for an integer coverage map and fatal for drizzle's continuous
        one). With the cause fixed the combination works: the three-panel M 31
        mosaic that failed now assembles in 88 s. So the gate is gone — it
        existed because the pair was broken, not because it is expensive.

        The cost is real and stays stated. Drizzle is roughly 10x an ordinary
        stack and a mosaic runs one stack PER POINTING, so on a 39-panel set the
        two multiply into something worth knowing before pressing Stack.
        """
        both = self.mosaic_check.isChecked() and self.drizzle_check.isChecked()
        self.exclusive_note.setText(
            "Drizzle runs on every pointing, so a mosaic multiplies its cost — "
            "expect this to take a very long time."
            if both and self.mosaic_check.isEnabled() else "")
        self._sync_folded_note()

    def _sync_background_availability(self) -> None:
        """Disabled while THIS dialog's own foreground stack is running (the
        same output-path race `_set_busy` exists to prevent) or while "Stack
        as mosaic" is checked (see the comment where the button is created).
        Busy is transient and self-evident from the status text and progress
        bar already on screen; mosaic gets its own visible note so the reason
        doesn't require a hover to find — the note explains, the disable
        enforces."""
        if self._on_background is None:
            return
        mosaic = self.mosaic_check.isChecked()
        self.background_btn.setEnabled(not (self._busy or mosaic))
        self.background_note.setText(
            "Mosaics can't run in the background yet — use Stack."
            if mosaic else "")

    # --- grade ---
    def grade(self, folder: str | None = None) -> None:
        """Measure every sub in `folder`, or in the Folder field's text when
        `folder` is omitted. A caller that already knows which folder it
        means — Move them back re-measuring frames that came back from an
        earlier session — must pass it: the field can have been retyped
        since grading, and reading it here silently measured whatever the
        user happened to be typing instead of the folder the frames actually
        live in."""
        if self._busy:
            # A grade that never starts must not leave a stale promise
            # behind — a "Move them back" fallback that finds this busy would
            # otherwise leave `_restoring_names` set with nothing running to
            # ever clear it, so a later, unrelated grade or failure reads its
            # message as if it were still about the move.
            self._restoring_names = None
            return
        if folder is None:
            folder = self.folder_edit.text().strip()
        paths = discover_subs(folder) if folder else []
        if not paths:
            # Forget the last folder's grade. Its frames stayed listed and
            # stackable while Save to followed the NEW folder, so Stack wrote
            # folder A's master into B under A's name.
            self._restoring_names = None    # same reason as the busy branch above
            self._stats = []
            self._frame_shape = None
            if folder != self._graded_folder:
                self.verdict_strip.set_message("")      # the last folder's move report
            self._graded_folder = folder
            self._pixel_scale = None
            self._update_verdict()
            # Everything moved into rejected/ leaves no subs at the top — and
            # that is exactly when "Move them back" must still be offered.
            self._sync_reject_buttons(check_disk=True)
            # The SAME list object as self._stats (empty here, but a later
            # Move them back extends it in place — see _on_restored_graded —
            # and that only reaches this dialog's own `_stats` if the two
            # were never allowed to become two different empty lists here).
            self.browser.set_frames(self._stats)
            self._update_drizzle_note()
            self.scan_pointings(folder)    # no paths: mosaic off and disabled
            if not self._name_is_manual:
                self.name_edit.setText("")
            self._sync_name_note()
            self.status.setText("No .fit subs found in that folder.")
            return
        self._grading_folder = folder
        self.scan_pointings(folder)
        runner = self._grade_runner
        strictness = self.strictness_box.currentText().lower()

        def work():
            return runner(paths, on_progress=lambda i, n, name:
                          self._signals.progress.emit(i, n, "grading"),
                          strictness=strictness)

        self._start(work, self._on_graded,
                    "Measuring every frame — this is the slow part, and your "
                    "Frames and Combine choices apply instantly afterwards.")

    def _on_graded(self, stats) -> None:
        # Strictness may have changed while the async measure was running —
        # re-judge against the knob's current value before painting anything.
        judge(stats, self.strictness_box.currentText().lower())
        self._active_token = None
        self._set_busy(False)
        self._stats = stats
        self._frame_shape = self._read_frame_shape(stats)
        folder = self._grading_folder or self.folder_edit.text().strip()
        if folder != self._graded_folder:
            self.verdict_strip.set_message("")          # the last folder's move report
        self._graded_folder = folder
        self._pixel_scale = read_pixel_scale([s.path for s in stats if not s.error])
        self._update_drizzle_note()
        self.browser.set_frames(stats)
        self._update_verdict()
        self._sync_reject_buttons(check_disk=True)
        self.status.setText(self._selection_summary())
        self._auto_output_path()
        self._clear_restoring_message()      # the full-grade path of a move back
        if self._fitted:
            # The grade is what grows the dialog most (status line, drizzle
            # advice): fit now, not a frame later from resizeEvent.
            self._keep_on_screen()

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

    def _on_ticks_changed(self) -> None:
        if self._stats:
            self.status.setText(self._selection_summary())
            self._auto_output_path()
            self._sync_reject_buttons()

    def _rejudge(self, _text=None) -> None:
        if not self._stats:
            return
        judge(self._stats, self.strictness_box.currentText().lower())
        self.browser.refresh_verdicts()      # a frame ticked by hand keeps its tick
        self._update_verdict()
        self._sync_reject_buttons()
        self.status.setText(self._selection_summary())
        self._auto_output_path()

    def _update_verdict(self) -> None:
        """Rebuilt when the GRADER's decisions change — a grade or a
        Strictness move — never on a hand tick: it describes the night, and
        the status line already counts the ticks.

        A folder reopened with some of its frames still parked in rejected/
        from an earlier session is graded on only what is left at the top —
        build_verdict never sees the missing ones — so its headline's share
        and kept count describe an easier night than the one he actually
        shot, and nothing on screen says why. One more detail line, read
        straight off the same disk check "Move them back" already offers
        from, says how many are missing from the count; it updates itself
        away once those frames are back, the next time this runs.

        A name the manifest lists is not necessarily missing from the
        count — a frame moved THIS session is still a row in `self._stats`
        (moved=True) and build_verdict counts it, since it counts the
        grader's decision, not the move. Only a pending name with no such row
        is actually uncounted; without this filter the line claimed frames
        "kept" one line above were also "not counted here"."""
        verdict = build_verdict(self._stats, self._pixel_scale) if self._stats else None
        if verdict is not None and self._graded_folder:
            try:
                pending = pending_back(self._graded_folder)
            except (RejectMoveError, OSError):
                pending = []
            listed_moved = {os.path.basename(s.path) for s in self._stats if s.moved}
            back = len([n for n in pending if n not in listed_moved])
            if back:
                note = (f"{back} more frame is in rejected/ and is not counted here."
                        if back == 1 else
                        f"{back} more frames are in rejected/ and are not counted here.")
                verdict = Verdict(verdict.headline, verdict.details + (note,))
        self.verdict_strip.set_verdict(verdict)

    # --- the rejected folder (spec decision 7, §5) ---
    def _frames_to_move(self) -> list:
        """Not ticked right now, not unreadable, not moved already. What he
        ticked back in stays; a kept frame he unticked goes. Error frames stay
        put: an unreadable file or a stacked master has no verdict to act on."""
        return [s for s in self._stats
                if not s.included and not s.error and not s.moved]

    def _sync_reject_buttons(self, check_disk: bool = False) -> None:
        """The move count follows the ticks. The back count reads the folder,
        so only after a grade or a move — never on every tick. A successful
        check clears a stale "damaged" message — but ONLY that one: the
        folder never changes when he fixes the record by hand
        and measures again, so the "folder changed" clear in
        grade()/_on_graded never fires, and the complaint used to sit there
        forever after the thing it complained about was gone. Clearing every
        message a successful check happened to run alongside would be worse —
        it would erase "Moved N frames back" the moment the routine back-count
        check right after it succeeds, which is every time."""
        self.verdict_strip.set_move_count(len(self._frames_to_move()))
        if not check_disk:
            return
        back = 0
        if self._graded_folder:
            try:
                back = len(pending_back(self._graded_folder))
            except RejectMoveError as exc:
                self.verdict_strip.set_message(str(exc))
                self._damaged_folder = True
            except OSError:
                back = 0            # an unreadable folder: nothing to offer
            else:
                if self._damaged_folder:
                    self.verdict_strip.set_message("")
                self._damaged_folder = False
        self.verdict_strip.set_back_count(back)

    def _ask_yes_no(self, title: str, text: str) -> bool:
        answer = QMessageBox.question(
            self, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return answer == QMessageBox.StandardButton.Yes

    def _say(self, text: str) -> None:
        """A move's outcome: in the strip, where it stays until the next one,
        and in the status line."""
        self.verdict_strip.set_message(text)
        self.status.setText(text)

    def _queue_is_reading(self) -> bool:
        return self._queue_busy is not None and bool(self._queue_busy())

    def _move_rejected(self) -> None:
        # Only one move (or move-back) may run at a time (two moves at once
        # on one folder can lose manifest entries). This is what makes that
        # safe WITHOUT a lock file: the rename itself runs on
        # the GUI thread — see `move_to_rejected`, called straight from here
        # rather than through `_start`/the thread pool — and `self._confirm`'s
        # modal dialog blocks the whole event loop while it is up, so nothing
        # else on this thread can start a second move while the first is
        # still being asked about or still renaming. Moving the rename
        # off-thread (to keep a big folder from freezing the UI) would break
        # this guarantee and reopen the entries-lost bug the busy/queue
        # checks below cannot catch by themselves — a real fix would need an
        # actual lock, not just "the callbacks happen to be serialised".
        if self._busy or not self._stats or not self._graded_folder:
            return
        if self._queue_is_reading():
            self._say("A background stack is running and may be reading these "
                      "frames — move them once it has finished.")
            return
        try:
            pending_back(self._graded_folder)
        except RejectMoveError as exc:
            # A known-damaged record: refuse before asking, not after he has
            # already said yes to a move that cannot happen.
            self._say(str(exc))
            self._damaged_folder = True
            return
        except OSError:
            pass
        frames = self._frames_to_move()
        if not frames:
            return
        folder = self._graded_folder            # the frames' own folder, not the field
        n = len(frames)
        where = os.path.basename(os.path.normpath(folder))
        question = (f"Move {n} rejected {'frame' if n == 1 else 'frames'} into "
                    f"{where}/rejected? Nothing is deleted; you can move them back.")
        if not self._confirm("Move rejected frames", question):
            return
        try:
            moved = move_to_rejected(folder, [s.path for s in frames],
                                     [s.path for s in self._stats])
        except RejectMoveError as exc:
            self._say(str(exc))
            return
        for s in frames:
            new = moved.get(os.path.abspath(s.path))
            if new:
                s.path, s.moved, s.included = new, True, False
        self.browser.frames_moved()
        self._sync_reject_buttons(check_disk=True)
        k = len(moved)
        self._say(f"Moved {k} {'frame' if k == 1 else 'frames'} into {where}/rejected. "
                  "Nothing was deleted.")

    def _move_back(self) -> None:
        # See the comment in _move_rejected: the same "one move at a time"
        # guarantee applies here, for the same reason.
        if self._busy or not self._graded_folder:
            return
        if self._queue_is_reading():
            self._say("A background stack is running — move the frames back once it "
                      "has finished.")
            return
        folder = self._graded_folder
        # Nothing listed yet means nothing to lose. Captured BEFORE the
        # bookkeeping below touches self._stats.
        was_empty = not self._stats
        try:
            result = move_back(folder)
        except RejectMoveError as exc:
            self._say(str(exc))
            return
        home = set(result.restored) | set(result.already_back)
        missing = set(result.missing)
        listed = set()
        for s in self._stats:
            name = os.path.basename(s.path)
            listed.add(name)
            if s.moved and name in home:
                s.path, s.moved = os.path.join(folder, name), False
        # A name move_back could not find anywhere — not in rejected/, not
        # at home, deleted by hand — must stop being listed as a moved frame
        # pointing at a file that no longer exists anywhere.
        self.browser.remove_frames(lambda s: s.moved and os.path.basename(s.path) in missing)
        self.browser.frames_moved()
        self._stats = self.browser.frames()   # keep in sync — see grade()'s no-paths branch
        # A frame remove_frames just dropped (deleted from rejected/ by
        # hand) can no longer be counted anywhere — the strip must forget it
        # along with the row.
        self._update_verdict()
        unlisted = [n for n in result.restored if n not in listed]
        self._sync_reject_buttons(check_disk=True)
        self._say(self._back_message(result, unlisted))
        if not unlisted:
            return
        # Whichever path re-measures the restored frames, "Measuring…"
        # must not outlive the measure — on success as much as on failure.
        # _on_graded/_on_restored_graded replace it with the move's own
        # outcome once the grade actually finishes; _on_error replaces it
        # with something actionable if the grade fails or is cancelled.
        self._move_back_result = result
        if was_empty:
            # Nothing was listed before this move, so there is no hand tick
            # to protect — a FULL grade of the graded folder is not just
            # safe here, it is REQUIRED. The partial grade below exists to
            # protect hand ticks on rows already listed; it never runs
            # scan_pointings/read_pixel_scale/_read_frame_shape/
            # _update_drizzle_note (_on_restored_graded does none of that),
            # so a folder opened with everything already moved out, then
            # moved back in one go, left Mosaic disabled and the pixel scale
            # and drizzle note missing — exactly the state a normal grade()
            # of that same folder would never leave it in. Set the SAME flag
            # _grade_restored sets for the partial path, so a failure here
            # gets the same "still back in the folder" message instead of a
            # generic "Failed: …".
            self._restoring_names = unlisted
            self.grade(folder)
            return
        # Frames restored from an earlier session: never graded in THIS
        # window. This used to call self.grade() with no folder, which read
        # the FOLDER FIELD (wrong once retyped) and re-measured the WHOLE
        # folder, silently resetting every hand tick already made on what
        # was already listed. Grade only the names that are actually new,
        # off-thread like any other grade, and merge them in without
        # touching an existing row.
        self._grade_restored(folder, unlisted)

    def _grade_restored(self, folder: str, names: list[str]) -> None:
        """Off-thread, exactly like grade(), but for just the frames
        `_move_back` found restored and not already listed — see the comment
        there for why this replaced a full self.grade()."""
        self._restoring_names = names       # read by _on_error if this fails
        paths = [os.path.join(folder, n) for n in names]
        runner = self._grade_runner
        strictness = self.strictness_box.currentText().lower()

        def work():
            return runner(paths, on_progress=lambda i, n, name:
                          self._signals.progress.emit(i, n, "grading"),
                          strictness=strictness)

        self._start(work, self._on_restored_graded,
                    "Measuring the frames that came back…")

    def _on_restored_graded(self, new_stats) -> None:
        self._clear_restoring_message()      # the partial-grade path of a move back
        self._active_token = None
        self._set_busy(False)
        self.browser.add_frames(new_stats)
        self._stats = self.browser.frames()    # keep in sync — see _move_back
        # Re-judge the MERGED list — a session-relative gate needs the whole
        # set — then restore every hand tick judge() just overwrote:
        # reapply_ticks() is the exact mechanism _rejudge already relies on
        # for a Strictness move, and it works here for the same reason: the
        # newly-added rows were never hand-touched, so judge()'s fresh
        # verdict is simply what stands for them.
        judge(self._stats, self.strictness_box.currentText().lower())
        self.browser.refresh_verdicts()
        self._update_verdict()
        self._sync_reject_buttons(check_disk=True)
        self.status.setText(self._selection_summary())
        self._auto_output_path()
        if self._fitted:
            self._keep_on_screen()

    def _clear_restoring_message(self) -> None:
        """The "Measuring N frames that came back…" message is a promise;
        replace it with the move's own outcome once the grade it was waiting
        on actually finishes, on both the partial re-grade
        (_on_restored_graded) and the full re-grade an all-moved reopen falls
        back to (_on_graded) — a no-op for any other grade, since
        `_restoring_names` is only set by `_move_back`."""
        if self._restoring_names is None:
            return
        self._restoring_names = None
        if self._move_back_result is not None:
            self.verdict_strip.set_message(self._back_message(self._move_back_result))

    @staticmethod
    def _back_message(result, unlisted: list[str] = ()) -> str:
        def count(n):
            return f"{n} {'frame' if n == 1 else 'frames'}"

        parts = []
        if result.restored:
            parts.append(f"Moved {count(len(result.restored))} back.")
        if result.already_back:
            n = len(result.already_back)
            parts.append(f"{count(n)} had already been moved back by hand.")
        if result.taken:
            parts.append(f"{describe_names(result.taken)} stayed in rejected: a file "
                         "with the same name is in the folder again.")
        if result.refused:
            parts.append(f"{describe_names(result.refused)} stayed in rejected: not an "
                         "ordinary file.")
        if result.missing:
            one = len(result.missing) == 1
            parts.append(f"{describe_names(result.missing)} {'is' if one else 'are'} no "
                         "longer in rejected.")
        if result.failed:
            parts.append(result.failed)
        if unlisted:
            parts.append(f"Measuring {count(len(unlisted))} that came back so "
                         "they are listed.")
        return " ".join(parts) or "Nothing to move back."

    def _auto_output_path(self) -> None:
        if self._name_is_manual or not self._stats:
            return
        kept = [s for s in self._stats if s.included]
        exposures = [s.exposure for s in kept if s.exposure > 0]
        exposure = exposures[0] if exposures and max(exposures) == min(exposures) else 0.0
        target = next((s.target for s in kept if s.target), "")
        name = master_filename(target, len(kept), exposure,
                               sum(s.exposure for s in kept),
                               mosaic=self.mosaic_check.isChecked(),
                               drizzle=self.drizzle_check.isChecked())
        self.name_edit.setText(name)
        self._sync_name_note()

    def _selection_summary(self) -> str:
        # Masters and unmeasured frames are in no count (spec 2026-09-28 §3;
        # Ruling R1): the same total as Show All and the verdict.
        counted = [s for s in self._stats if not is_left_out(s)]
        if not counted:
            return ONLY_MASTERS
        total = len(counted)
        kept = [s for s in counted if s.included]
        text = f"Keeping {len(kept)} of {total} frames"
        kept_s = sum(s.exposure for s in kept)
        all_s = sum(s.exposure for s in counted)
        if all_s > 0:
            unit = "minute" if round(all_s / 60) == 1 else "minutes"
            text += (f" — {max(1, round(kept_s / 60))} of "
                     f"{max(1, round(all_s / 60))} {unit} of light")
        if total < JUDGE_MIN:
            text += " (too few frames to grade reliably — keeping all)"
        return text + "."

    # --- run ---
    def _included_paths_best_first(self) -> list:
        return order_best_first(self.browser.checked_frames())

    def _method(self) -> str:
        if self.drizzle_check.isChecked():
            return "drizzle"      # drizzle does its own sigma-clip rejection
        return "sigma_clip" if self.sigma_radio.isChecked() else "average"

    def _options(self):
        """The one place a StackOptions is built. Two buttons now start the
        same stack; building it twice is how they would come to mean
        different things."""
        return StackOptions(self._method(), KAPPA[self.kappa_box.currentText()],
                            self._included_paths_best_first(),
                            self.output_path(),
                            autocrop=self.crop_check.isChecked())

    def _target_label(self) -> str:
        """The same name _auto_output_path already derives for the output
        filename, so the log and the file agree on what this was."""
        target = next((s.target for s in self._stats
                       if s.included and s.target), "")
        return target or "stacked master"

    def _validate_ready_to_run(self) -> bool:
        """Shared by both buttons: Stack and Stack in background start the
        SAME job, so they must refuse under the same conditions with the
        same message rather than drift into checking different things — see
        the bug this closed, where the background button skipped both of
        these and enqueued StackOptions(include=[], output_path='', ...)."""
        if not self.output_path():
            self.status.setText("Pick an output path — a folder and a name.")
            return False
        if "/" in self.name_edit.text() or os.sep in self.name_edit.text():
            self.status.setText("The name cannot contain a folder — choose the "
                                "folder with Save to.")
            return False
        if len(self._included_paths_best_first()) < STACK_MIN:
            self.status.setText(f"Select at least {STACK_MIN} frames to stack.")
            return False
        # save_fits creates no folders, so a typo here used to fail only
        # AFTER the stack — hours, for a drizzle or a mosaic.
        folder = os.path.dirname(self.output_path())
        if not os.path.isdir(folder):
            self.status.setText(f"The folder {folder} does not exist — "
                                "choose one with Browse….")
            return False
        return True

    def run(self) -> None:
        if self._busy:
            self.status.setText("Please wait — still working…")
            return
        # Refuses rather than warns-then-allows: a silent OR a dismissable
        # start both let a background job and this dialog's foreground run
        # write the SAME auto-generated output path at once — ~17 GB
        # resident and a corrupted master, discovered only after the fact.
        # A fresh StackDialog starts with _busy = False and cannot see the
        # job queue any other way (`_set_busy` only guards THIS dialog
        # against itself). `_stack_in_background` does not need this check:
        # the queue itself serialises background jobs one at a time, so a
        # second one just waits instead of racing.
        if self._queue_busy is not None and self._queue_busy():
            self.status.setText(
                "A background stack is already running — wait for it to "
                "finish before starting another (they could write the same "
                "file).")
            return
        if not self._validate_ready_to_run():
            return
        include = self._included_paths_best_first()
        method = self._method()

        if self.mosaic_check.isChecked():
            mosaic_opts = MosaicOptions(
                include=include, output_path=self.output_path(),
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

        opts = self._options()
        runner = self._stack_runner

        def work():
            return runner(opts, on_progress=lambda i, n, label:
                          self._signals.progress.emit(i, n, label))

        self._start(work, self._on_stacked, "Stacking…")

    def _stack_in_background(self) -> None:
        if self._on_background is None:
            return
        if self._busy:
            self.status.setText("Please wait — still working…")
            return
        if not self._validate_ready_to_run():
            return
        if self.mosaic_check.isChecked():
            self.status.setText("Mosaics can't run in the background yet — use Stack.")
            return
        self._on_background(self._options(), self._target_label())
        self.accept()

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
        if self._name_is_manual or not self._stats:
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
        if os.path.exists(new_path):
            # Another master already has the honest name. The dialog only
            # warns about replacing the name the user SAW; this one they never
            # did, so keep the old name rather than destroy a file.
            return
        try:
            os.replace(old_path, new_path)
        except OSError:
            return          # a rename is a nicety; never fail a finished stack
        result.output_path = new_path
        self.name_edit.setText(os.path.basename(new_path))

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
        if self._restoring_names is not None:
            # A re-grade started by "Move them back" — partial
            # (_grade_restored) or the full grade an all-moved reopen falls
            # back to — that failed OR was cancelled leaves the frames
            # genuinely back in the folder: move_back's rename already
            # happened, synchronously, before this async measure even
            # started — but not yet LISTED. "Measuring N frames that came
            # back…" was a promise this run broke; replace it with what is
            # actually true and actionable, for either reason it cannot
            # finish. A Cancel is his own choice and needs no reason echoed
            # back at him; any other failure gets the exception appended so
            # a bug report carries the cause.
            names = self._restoring_names
            self._restoring_names = None
            self._active_token = None
            self._set_busy(False)
            n = len(names)
            text = (f"{n} {'frame is' if n == 1 else 'frames are'} back in the "
                    "folder; grade again to list "
                    f"{'it' if n == 1 else 'them'}.")
            if not isinstance(exc, Cancelled):
                text += f" ({exc})"
            self._say(text)
            return
        if isinstance(exc, Cancelled):
            self._active_token = None
            self._set_busy(False)
            self.status.setText("Cancelled.")
            return
        self._set_busy(False)
        self.status.setText(f"Failed: {exc}")
