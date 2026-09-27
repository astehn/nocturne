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
from ..stacking.grade import grade_frames, judge, order_best_first
from ..stacking.mosaic import (MosaicOptions, discover_panels, read_pointings,
                               run_mosaic)
from ..stacking.stacker import StackOptions, run_stack, master_filename
from . import file_dialogs, theme
from .frame_browser import FrameBrowser
from .option_band import OptionBand, WrappedNote
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
        # explanations expanded -- which is the DEFAULT, help_expanded=True,
        # settings.py:43 -- this dialog's own minimumSizeHint is 844px, and it
        # opened at 700 with a floor of 500. Qt then squeezed the QFormLayout's
        # rows onto a 46px stride while the rows are 54-72px tall, and because
        # _Hint refuses to shrink (it must, or the text clips) the explanations
        # painted straight over the controls beneath them: 11 overlaps measured
        # under cocoa, the worst 158x18px across "Trim the ragged edges".
        # Andreas never saw it because his help_expanded is False -- collapsed
        # the dialog needs 658px and fits.
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
        self._pool = QThreadPool.globalInstance()
        self._signals = _Signals()
        self._signals.progress.connect(self._on_progress)

        self.folder_edit = QLineEdit()
        self.folder_edit.textChanged.connect(self._follow_subs_folder)
        self.save_to_edit = QLineEdit()
        self.save_to_edit.setToolTip("The folder the master is written to — the "
                                     "subs folder unless you choose another")
        self.save_to_edit.textEdited.connect(self._on_save_to_typed)
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
        frames.body.addWidget(self.strictness_box)
        picky = QLabel("how picky to be about which subs to keep")
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
        result.body.addWidget(_Hint(
            "Off keeps the full frame. The edges are built from fewer frames, "
            "so they are noisier, but you can always crop later."))
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
        self.options_band.set_folded(bool(getattr(settings, "frame_options_folded", False)))
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

        # The same collapsible help the main window uses, bound to the same
        # sticky setting — so turning it off here turns it off there, and a
        # novice still gets it by default (help_expanded starts True).
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
        form.addRow("Folder of subs", _picker_row(self.folder_edit, self._browse_folder))
        form.addRow(self.options_band)
        form.addRow(self._help_link)
        form.addRow("Save to", _picker_row(self.save_to_edit, self._browse_save_to))
        form.addRow("Name", name_field)

        root = QVBoxLayout(self)
        root.addLayout(form)
        self._apply_hints_visible()
        root.addWidget(self.browser, 1)
        root.addWidget(self.progress)
        root.addWidget(self.status)
        root.addLayout(buttons_col)
        self._sync_folded_note()
        self._fitted = False       # _fit_to_content runs once, on first show
        # The screen's folds (help, then the option band) stop once the user
        # has toggled either by hand in this window: their click outranks it.
        self._user_laid_out = False
        self._hints_forced_closed = False
        self._band_forced_folded = False
        self._refit_pending = False

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
        return os.path.join(folder, name)

    def _on_name_typed(self, _text: str) -> None:
        self._name_is_manual = True
        self.auto_name_btn.show()
        self._sync_name_note()

    def _on_save_to_typed(self, _text: str) -> None:
        self._save_to_is_manual = True
        self._sync_name_note()

    def _follow_subs_folder(self, folder: str) -> None:
        if not self._save_to_is_manual:
            self.save_to_edit.setText(folder.strip())
        self._sync_name_note()

    def _restore_automatic_name(self) -> None:
        self._name_is_manual = False
        self.auto_name_btn.hide()
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

    def _toggle_hints(self) -> None:
        # An explicit click outranks the screen-height override: if the user
        # asks for the explanations on a short screen they get them, and the
        # dialog grows as far as the screen allows.
        self._hints_forced_closed = False
        self._user_laid_out = True
        if self._band_forced_folded:
            self._band_forced_folded = False
            self.options_band.blockSignals(True)     # the screen's fold, not theirs
            self.options_band.set_folded(False)
            self.options_band.blockSignals(False)
        self._settings.help_expanded = not self._settings.help_expanded
        self._persist_settings()
        self._apply_hints_visible()

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
        self._band_forced_folded = False
        self._settings.frame_options_folded = folded
        self._persist_settings()

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
        shown = (bool(getattr(self._settings, "help_expanded", True))
                 and not getattr(self, "_hints_forced_closed", False))
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
            + ("How this works ▾" if shown else "How this works ▸") + "</a>")

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
        True when it folded something. Help first, then the option band —
        both for THIS window only, never saved, and never once the user has
        toggled either here."""
        if self._user_laid_out:
            return False
        room = self._available_height()
        needed = self._settled_minimum_height()
        squeezed = False
        if (needed > room and getattr(self._settings, "help_expanded", True)
                and not self._hints_forced_closed):
            self._hints_forced_closed = True
            self._apply_hints_visible()
            needed = self._settled_minimum_height()
            squeezed = True
        # Still too tall: fold the options for THIS window too. Not saved —
        # folded_changed is blocked — for the same reason the help is not.
        if needed > room and not self.options_band.is_folded():
            self.options_band.blockSignals(True)
            self.options_band.set_folded(True)
            self.options_band.blockSignals(False)
            self._band_forced_folded = True
            needed = self._settled_minimum_height()
            squeezed = True

        if squeezed:
            # Qt already grew the window to the OLD minimum when it was shown,
            # and it does not shrink by itself: measured 2026-09-27, the
            # pre-layout-A dialog stayed 825 px tall on a 740 px screen after
            # collapsing. Bring it back down to what now fits.
            self.resize(self.width(), min(max(needed, _OPEN_HEIGHT), room))
        return squeezed

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
                    "Frames and Combine choices apply instantly afterwards.")

    def _on_graded(self, stats) -> None:
        # Strictness may have changed while the async measure was running —
        # re-judge against the knob's current value before painting anything.
        judge(stats, self.strictness_box.currentText().lower())
        self._active_token = None
        self._set_busy(False)
        self._stats = stats
        self._frame_shape = self._read_frame_shape(stats)
        self._update_drizzle_note()
        self.browser.set_frames(stats)
        self.status.setText(self._selection_summary())
        self._auto_output_path()
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

    def _rejudge(self, _text=None) -> None:
        if not self._stats:
            return
        judge(self._stats, self.strictness_box.currentText().lower())
        self.browser.refresh_verdicts()      # a frame ticked by hand keeps its tick
        self.status.setText(self._selection_summary())
        self._auto_output_path()

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
        if len(self._included_paths_best_first()) < 3:
            self.status.setText("Select at least 3 frames to stack.")
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
        if isinstance(exc, Cancelled):
            self._active_token = None
            self._set_busy(False)
            self.status.setText("Cancelled.")
            return
        self._set_busy(False)
        self.status.setText(f"Failed: {exc}")
