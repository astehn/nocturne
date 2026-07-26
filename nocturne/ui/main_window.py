from __future__ import annotations

import datetime
import os

import numpy as np
from PySide6.QtCore import QEvent, QObject, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..core.auto_enhance import build_auto_plan, run_auto_plan
from ..core.provenance import build_report
from ..core.crop import CropParams, detect_content_bounds
from ..core.enhance import ENHANCE_OPS, star_colour_layers
from ..core.export import save_fits, save_png, save_tiff, _to_uint
from ..core.fits_io import format_integration, import_summary, resolve_integration
from ..history.project import Project
from ..history.project_store import NewerVersionError, load_project, save_project
from ..history.step import Step
from ..settings import (
    add_recent_project, astap_valid, graxpert_valid, load_settings, rcastro_valid,
    resolve_binary, save_settings, start_dir,
)
from ..recipe import recipe_from_entries, save_recipe, uncaptured_step_names
from ..steps.factory import make_step
from ..steps.load import load_fits
from ..tools.base import run_cli, ToolError
from ..tools.rcastro import RCAstro
from ..core.metrics import rms_delta
from ..core.update_check import DOWNLOAD_URL, is_newer, latest_release_version
from .histogram_view import HistogramView
from . import help_content
from .about_dialog import AboutDialog
from .help_dialog import HelpDialog
from .provenance_dialog import ProvenanceDialog
from .theme import ACCENT, WARNING
from .batch_dialog import BatchDialog
from .image_view import ImageView
from .log_panel import LogPanel, OutputPanel, format_log_entry
from .pipeline import ENHANCE_NAMES, GEOMETRY_NAMES, POST_STRETCH_IDS, PROCESSING_ORDER, STEP_NAME, next_enabled, path_stages, prev_enabled
from ..core.levels import apply_levels, auto_levels, clipping_masks
from ..core.saturation import nebula_saturate, saturate
from ..core.local_contrast import enhance
from ..core.hdr import recover_core
from ..core.color import remove_green, remove_green_fringe, remove_green_fringe_masked
from ..core.curves import apply_curve, gentle_s_points
from ..core.star_reduction import reduce_stars
from ..core.starless import split_stars, star_mask
from ..steps.green_fringe import FRINGE_MASK_SCALE
from ..core.stretch import apply_stretch
from ..core.image import AstroImage
from ..core.tasks import CancelToken, Cancelled, set_ambient, clear_ambient
import time as _time
from .preview import rgb_to_qimage, to_qimage
from .settings_dialog import SettingsDialog
from .share_dialog import ShareDialog
from .upscale_dialog import UpscaleDialog
from .step_panels import build_panel
from .icons import load_icon
from .stepper import Stepper
from .welcome import WelcomeScreen
from .busy_bar import BusyBar
from .worker import run_async

_ASPECT_RATIO = {"Original": None, "1:1": 1.0, "16:9": 16 / 9, "4:5": 4 / 5, "3:2": 3 / 2}
BUSY_DELAY_MS = 400   # ms before busy visuals appear; sub-threshold ops show nothing

_FREE_STAR_NOTE = (
    "Using free star detection — set RC-Astro (StarX) in Settings for cleaner separation."
)


class _PrecomputedStep(Step):
    """Records an already-computed image (from async processing) into history."""

    def __init__(self, name: str, image) -> None:
        self.name = name
        self._image = image

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img, option):
        return self._image


class _AutoEnhanceSignals(QObject):
    """Marshals run_auto_plan's on_progress callbacks (fired from the worker
    thread when async is enabled) back onto the GUI thread via a queued
    connection — mirrors batch_dialog/haoiii_dialog/stack_dialog's Signal-based
    progress plumbing."""
    progress = Signal(int, int, str)


class _SaveSignals(QObject):
    """Marshals save_project's on_progress callback (fired from the worker
    thread when async is enabled) back onto the GUI thread via a queued
    connection — mirrors _AutoEnhanceSignals."""
    progress = Signal(int, int)


class MainWindow(QMainWindow):
    def __init__(self, settings_path: str, check_updates: bool = True) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self._settings_path = settings_path
        self.settings = load_settings(settings_path)
        self.project: Project | None = None
        self._project_path: str | None = None   # current .nocturne bundle path, if saved/opened
        self._dirty = False   # True once the project has un-saved edits
        self._solve = None  # (sig, SolveResult, objects) once a plate-solve lands
        self._cache_dir = os.path.join(os.path.dirname(settings_path), "cache")
        self._stages = path_stages()
        self._stage = 0
        self._bg_runner = run_cli
        self._rc_runner = run_cli
        self._busy = False
        self._async_enabled = True  # tests set False for deterministic apply
        self._active_token = None       # CancelToken for the running op, if any
        self._busy_start = 0.0          # time.monotonic() when the current op started
        self._pool = QThreadPool.globalInstance()
        self._auto_signals = _AutoEnhanceSignals()
        self._auto_signals.progress.connect(self._on_auto_progress)
        self._save_signals = _SaveSignals()
        self._save_signals.progress.connect(
            lambda d, t: self._set_progress("Saving project", d, t))
        # Spacebar before/after peek: toggles the main image between the current
        # state and the previous one (the last applied step). App-wide event
        # filter so Space works regardless of focus (except in text inputs).
        self._peek_active = False
        self._displayed = None   # the AstroImage currently on the canvas (peek 'after')
        QApplication.instance().installEventFilter(self)
        self._busy_bar = BusyBar()
        self._busy_shown = False        # whether the delayed visuals are currently up
        self._cursor_active = False     # whether an override cursor is currently set
        self._busy_label_text = ""      # base label text (ellipsis animation appends)
        self._ellipsis_n = 0
        self._busy_timer = QTimer(self)
        self._busy_timer.setSingleShot(True)
        self._busy_timer.timeout.connect(self._show_busy_visuals)
        self._ellipsis_timer = QTimer(self)
        self._ellipsis_timer.setInterval(BUSY_DELAY_MS)
        self._ellipsis_timer.timeout.connect(self._tick_ellipsis)
        self._progress_state = ("", 0, 0)   # last (phase, done, total) from _set_progress
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)   # 1s tick while busy visuals are shown
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        # Levels live-preview: a debounced (90 ms) non-committing render.
        self._levels_show_clipping = False
        self._levels_pending = None
        self._levels_timer = QTimer(self)
        self._levels_timer.setSingleShot(True)
        self._levels_timer.timeout.connect(self._render_levels_preview)
        # Stretch live-preview: a debounced (90 ms) non-committing render.
        self._stretch_pending = None
        self._stretch_timer = QTimer(self)
        self._stretch_timer.setSingleShot(True)
        self._stretch_timer.timeout.connect(self._render_stretch_preview)
        # Saturation live-preview: a debounced (90 ms) non-committing render.
        self._sat_pending = None
        self._sat_timer = QTimer(self)
        self._sat_timer.setSingleShot(True)
        self._sat_timer.timeout.connect(self._render_saturation_preview)
        self._sat_layers = None   # (sig, starless, stars) once a split lands
        # Local-contrast live-preview: a debounced (90 ms) non-committing render.
        self._lc_pending = None
        self._lc_timer = QTimer(self)
        self._lc_timer.setSingleShot(True)
        self._lc_timer.timeout.connect(self._render_lc_preview)
        # Recover-core live-preview: a debounced (90 ms) non-committing render.
        self._recover_pending = None
        self._recover_timer = QTimer(self)
        self._recover_timer.setSingleShot(True)
        self._recover_timer.timeout.connect(self._render_recover_preview)
        # Curves live-preview: a debounced (90 ms) non-committing render.
        self._curve_pending = None
        self._curve_timer = QTimer(self)
        self._curve_timer.setSingleShot(True)
        self._curve_timer.timeout.connect(self._render_curve_preview)
        # Green-fringe live-preview: the (slow) StarX split runs once on entering
        # the step (async, cached in _fringe_layers); the slider then previews the
        # instant de-green + recombine via a debounced (90 ms) render.
        self._fringe_layers = None    # (sig, starless, stars) once the split lands
        self._fringe_pending = None
        self._fringe_ready = False
        self._fringe_timer = QTimer(self)
        self._fringe_timer.setSingleShot(True)
        self._fringe_timer.timeout.connect(self._render_fringe_preview)
        # Remove-Green (SCNR) live preview: a pure per-pixel op, debounced 90 ms.
        self._rg_pending = None
        self._rg_timer = QTimer(self)
        self._rg_timer.setSingleShot(True)
        self._rg_timer.timeout.connect(self._render_removegreen_preview)
        # Star-reduction live-preview: the (slow) StarX split runs once on entering
        # the step (async, cached in _sr_layers); the slider then previews the fast
        # wing-curve reduce_stars instantly via a debounced (90 ms) render.
        self._sr_layers = None    # (sig, starless, stars) once the split lands
        self._sr_pending = None
        self._sr_ready = False
        self._sr_timer = QTimer(self)
        self._sr_timer.setSingleShot(True)
        self._sr_timer.timeout.connect(self._render_sr_preview)

        central = QWidget()
        outer = QVBoxLayout(central)
        root = QHBoxLayout()
        outer.addLayout(root, 1)

        self.stepper = Stepper()
        self.stepper.setMaximumWidth(200)
        self.stepper.set_stages(self._stages)
        self.stepper.stageSelected.connect(self._go_to)
        root.addWidget(self.stepper)

        self.image_view = ImageView()
        self.image_view.cropBoxShown.connect(self._on_crop_box_shown)
        self.image_view.cropBoxChanged.connect(self._update_crop_readout)
        self.image_view.cropDismissRequested.connect(self._on_crop_dismiss)
        self._center_stack = QStackedWidget()
        self._welcome = WelcomeScreen(self._choose_fits, self._open_stack)
        self._center_stack.addWidget(self._welcome)   # page 0
        self._center_stack.addWidget(self.image_view)  # page 1
        root.addWidget(self._center_stack, 1)

        right = QWidget()
        self._right_panel = right
        right.setMinimumWidth(260)
        self._right_layout = QVBoxLayout(right)
        self.histogram_view = HistogramView()
        self._right_layout.addWidget(self.histogram_view)
        self._info_strip = QLabel("")               # resolution · integration · object, under the histogram
        self._info_strip.setObjectName("importMeta")   # readable style
        self._info_strip.setWordWrap(True)
        self._right_layout.addWidget(self._info_strip)
        self._panel = QWidget()
        self._right_layout.addWidget(self._panel)
        self._right_layout.addStretch(1)
        # Bottom-anchored explainer: describes the current step. Owned by the
        # column (not the panel builders) so it stays put as panels gain toggles.
        self._current_topic_id = None
        self._explainer = QLabel("")
        self._explainer.setObjectName("stepExplainer")
        self._explainer.setWordWrap(True)
        self._explainer.setTextFormat(Qt.TextFormat.RichText)
        self._explainer.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._explainer_scroll = QScrollArea()
        self._explainer_scroll.setWidgetResizable(True)
        self._explainer_scroll.setWidget(self._explainer)
        self._explainer_scroll.setMaximumHeight(240)   # never crowd the nav row
        self._help_header = QLabel("")
        self._help_header.setObjectName("helpHeader")
        self._help_header.setOpenExternalLinks(False)
        self._help_header.linkActivated.connect(lambda _: self._toggle_help())
        self._right_layout.addWidget(self._help_header)
        self._right_layout.addWidget(self._explainer_scroll)
        self._full_help_link = QLabel('<a href="#">Full help →</a>')
        self._full_help_link.setObjectName("fullHelpLink")
        self._full_help_link.setOpenExternalLinks(False)
        self._full_help_link.linkActivated.connect(
            lambda _: self._open_help(self._current_topic_id))
        self._right_layout.addWidget(self._full_help_link)
        # peek + busy + warning sit above the nav, inside the stretch's grow-upward
        # zone, so the nav row stays pinned flush to the pane bottom and never moves.
        self._peek_label = QLabel("")                         # transient before/after cue
        self._peek_label.setStyleSheet("color: #9aa0a6;")
        self._peek_label.setWordWrap(True)                    # don't let changing text drive panel width
        self._right_layout.addWidget(self._peek_label)
        self._busy_label = QLabel("")
        self._busy_label.setStyleSheet("color: #9aa0a6;")     # neutral grey progress
        self._busy_label.setWordWrap(True)                    # rapid status updates must not resize the pane
        self._right_layout.addWidget(self._busy_label)
        self._progress = QProgressBar()
        self._progress.hide()
        self._right_layout.addWidget(self._progress)
        busy_row = QHBoxLayout()
        self._elapsed_label = QLabel("")
        self._elapsed_label.setStyleSheet("color: #9aa0a6;")
        self._elapsed_label.hide()
        busy_row.addWidget(self._elapsed_label)
        busy_row.addStretch(1)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._cancel_active)
        self._cancel_btn.hide()
        busy_row.addWidget(self._cancel_btn)
        self._right_layout.addLayout(busy_row)
        self._warning = QLabel("")
        self._warning.setObjectName("warning")
        self._warning.setWordWrap(True)
        self._warning.setStyleSheet("color: #ff6b6b;")        # blocking guidance / errors
        self._right_layout.addWidget(self._warning)
        diag_row = QHBoxLayout()
        self._show_details_btn = QPushButton("Show details")
        self._show_details_btn.setFlat(True)
        self._show_details_btn.clicked.connect(self._toggle_diagnostic_details)
        self._show_details_btn.hide()
        self._copy_log_btn = QPushButton("Copy log")
        self._copy_log_btn.setFlat(True)
        self._copy_log_btn.clicked.connect(self._copy_diagnostic_to_clipboard)
        self._copy_log_btn.hide()
        diag_row.addWidget(self._show_details_btn)
        diag_row.addWidget(self._copy_log_btn)
        diag_row.addStretch(1)
        self._right_layout.addLayout(diag_row)
        self._diagnostic_label = QLabel("")
        self._diagnostic_label.setWordWrap(True)
        self._diagnostic_label.setStyleSheet("color: #9aa0a6; font-family: monospace;")
        self._diagnostic_label.hide()
        self._right_layout.addWidget(self._diagnostic_label)
        self._last_diagnostic = ""
        nav = QHBoxLayout()
        self._back_btn = QPushButton("← Back")
        self._next_btn = QPushButton("Next →")
        self._next_btn.setObjectName("nav")   # blue "advance" — distinct from green Apply
        self._back_btn.clicked.connect(self.go_back)
        self._next_btn.clicked.connect(self.go_next)
        nav.addWidget(self._back_btn)
        nav.addWidget(self._next_btn)
        self._right_layout.addLayout(nav)                     # LAST widget — flush bottom
        root.addWidget(right)

        self.log_panel = LogPanel()
        self.output_panel = OutputPanel()
        self._bottom_bar = QWidget()
        bottom = QHBoxLayout(self._bottom_bar)
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.addWidget(self.log_panel, 3)      # history gets the wider share
        bottom.addWidget(self.output_panel, 2)   # results/progress, copyable
        outer.addWidget(self._bottom_bar)

        self.setCentralWidget(central)
        self._build_toolbar()
        self._build_menu()
        self._show_chrome(False)  # full-bleed welcome until an image is loaded

        if check_updates:
            run_async(self._pool, latest_release_version, self._on_update_check)

    def _show_chrome(self, visible: bool) -> None:
        """Show/hide the stepper + right panel so the welcome screen is a clean
        full-bleed empty state (no redundant Import panel/stepper before load)."""
        self.stepper.setVisible(visible)
        self._right_panel.setVisible(visible)
        self._rebuild_panel()
        self._refresh()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Offer to save before discarding an edited (un-saved) project on quit."""
        if not self._confirm_save_if_dirty():
            event.ignore()
            return
        for t in self.findChildren(QTimer):
            t.stop()   # cancel any pending debounced preview before deleting its snapshots
        self._clear_cache()   # leave nothing behind on quit
        event.accept()

    # --- dirty-state tracking + window title ---
    def _mark_dirty(self) -> None:
        self._dirty = True
        self._update_title()

    def _update_title(self) -> None:
        name = (os.path.splitext(os.path.basename(self._project_path))[0]
                if self._project_path else (self._source_label or None))
        if name is None:
            self.setWindowTitle(APP_NAME)
        else:
            self.setWindowTitle(f"{APP_NAME} — {name}{' •' if self._dirty else ''}")

    def _confirm_save_if_dirty(self) -> bool:
        """Guard for actions that discard the current project (open/close). Returns
        True when it's safe to proceed. If dirty, offers Save / Discard / Cancel."""
        if not self._dirty or self.project is None:
            return True
        resp = QMessageBox.question(
            self, f"{APP_NAME} — Unsaved Changes",
            "This project has unsaved edits. Save before continuing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if resp == QMessageBox.StandardButton.Save:
            self._save_project()
            return not self._dirty   # False if the Save/Save-As was itself cancelled
        return resp == QMessageBox.StandardButton.Discard

    def _build_menu(self) -> None:
        project_menu = self.menuBar().addMenu("Project")
        project_menu.addAction("Open Project…", lambda: self._open_project())
        self._save_project_menu_act = project_menu.addAction(
            "Save Project", self._save_project)
        project_menu.addAction("Save Project As…", self._save_project_as)
        self._recent_menu = project_menu.addMenu("Recent Projects")
        self._recent_menu.aboutToShow.connect(self._populate_recent_menu)
        project_menu.addSeparator()
        self._close_project_act = project_menu.addAction(
            "Close Project", self._close_project)   # back to the welcome screen
        self._provenance_act = project_menu.addAction(
            "Provenance report…", self._show_provenance)   # readable record of the edit pipeline

        help_menu = self.menuBar().addMenu("Help")
        self._help_act = help_menu.addAction("Help…", self._show_help)
        self._about_act = help_menu.addAction(f"About {APP_NAME}…", self._show_about)

    def _populate_recent_menu(self) -> None:
        self._recent_menu.clear()
        recent = self.settings.recent_projects
        if not recent:
            act = self._recent_menu.addAction("(no recent projects)")
            act.setEnabled(False)
            return
        for path in recent:
            self._recent_menu.addAction(os.path.basename(path), lambda p=path: self._open_project(p))

    def _show_help(self) -> None:
        self._open_help("getting-started")

    def _open_help(self, topic_id: str | None = None) -> HelpDialog:
        dlg = HelpDialog(self)
        if topic_id:
            dlg.show_topic(topic_id)
        dlg.show()
        return dlg

    def _update_explainer(self) -> None:
        tid = help_content.stage_topic_id(self.current_stage_id()) if self.project else None
        t = help_content.topic(tid) if tid else None
        self._current_topic_id = tid
        if t is not None:
            self._explainer.setText(f"<b>{t.summary}</b>{t.body}")
        self._apply_help_expanded()

    def _toggle_help(self) -> None:
        self.settings.help_expanded = not self.settings.help_expanded
        save_settings(self.settings, self._settings_path)
        self._apply_help_expanded()

    def _apply_help_expanded(self) -> None:
        """Show/hide the detailed help body per the global sticky flag. The one-line
        step description (in the panel) is always visible regardless."""
        expanded = self.settings.help_expanded
        has_topic = self._current_topic_id is not None
        self._help_header.setText(
            '<a href="#">How this works ▾</a>' if expanded
            else '<a href="#">How this works ▸</a>')
        self._help_header.setVisible(has_topic)
        self._explainer_scroll.setVisible(has_topic and expanded)
        self._full_help_link.setVisible(has_topic and expanded)

    def _show_output(self, text: str) -> None:
        """Routine results & progress → the copyable Output box."""
        self.output_panel.show_line(text)

    def _show_warning(self, text: str) -> None:
        """Blocking guidance / errors → prominent right-pane label near the buttons."""
        self._warning.setText(text)

    def _clear_warning(self) -> None:
        self._warning.setText("")
        self._show_details_btn.hide()
        self._copy_log_btn.hide()
        self._diagnostic_label.hide()
        self._diagnostic_label.setText("")

    def _report_tool_error(self, prefix: str, exc) -> None:
        """Surface a `ToolError` as a concise warning plus an expandable
        diagnostic (command + stderr + elapsed) with a Copy-log affordance."""
        command = " ".join(str(part) for part in exc.command)
        self._last_diagnostic = (
            f"Command: {command}\n"
            f"Elapsed: {exc.elapsed:.1f}s\n"
            f"stderr:\n{exc.stderr}"
        )
        self._show_warning(prefix)
        self._show_details_btn.show()
        self._copy_log_btn.show()
        self._diagnostic_label.hide()
        self._diagnostic_label.setText("")
        self._show_details_btn.setText("Show details")

    def _last_diagnostic_text(self) -> str:
        return self._last_diagnostic

    def _toggle_diagnostic_details(self) -> None:
        showing = self._diagnostic_label.isVisible()
        if showing:
            self._diagnostic_label.hide()
            self._show_details_btn.setText("Show details")
        else:
            self._diagnostic_label.setText(self._last_diagnostic)
            self._diagnostic_label.show()
            self._show_details_btn.setText("Hide details")

    def _copy_diagnostic_to_clipboard(self) -> None:
        QApplication.clipboard().setText(self._last_diagnostic)

    def _make_about_dialog(self) -> AboutDialog:
        return AboutDialog(self)

    def _show_about(self) -> None:
        self._make_about_dialog().exec()

    def _on_update_check(self, latest) -> None:
        """Worker result (UI thread): reveal the toolbar item if a newer release
        is out. Never raises — `latest` is None on any check failure."""
        if latest and is_newer(latest, __version__):
            self._update_act.setToolTip(
                f"Nocturne {latest.lstrip('vV')} is available — click to download")
            self._update_act.setVisible(True)

    def _open_download(self) -> None:
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(DOWNLOAD_URL))

    # --- recipes / batch ---
    def _save_recipe(self) -> None:
        if self.project is None:
            return
        uncaptured = uncaptured_step_names(self.project.entries())
        if uncaptured:
            resp = QMessageBox.warning(
                self, f"{APP_NAME} — Save Recipe",
                "This recipe can't include: " + ", ".join(uncaptured) + ".\n"
                "Those steps will be left out. Save the rest anyway?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if resp != QMessageBox.StandardButton.Save:
                return
        path, _ = QFileDialog.getSaveFileName(self, "Save Recipe", start_dir(self.settings.base_dir), "Recipe (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        save_recipe(recipe_from_entries(self.project.entries()), path)
        self._show_output(f"Saved recipe: {os.path.basename(path)}")

    def _open_batch(self) -> None:
        BatchDialog(self.settings, self).exec()

    def _open_stack(self) -> None:
        try:
            from .stack_dialog import StackDialog
        except ImportError:
            self._show_warning("Stacking unavailable — install astroalign and sep.")
            return
        StackDialog(self.settings, self,
                    on_master=lambda img: self.open_image(img, "stacked master")).exec()

    def _open_haoiii(self) -> None:
        try:
            from .haoiii_dialog import HaOIIIDialog
        except ImportError:
            self._show_warning("Ha/OIII extract unavailable — install astroalign and sep.")
            return
        HaOIIIDialog(self.settings, self,
                     on_master=lambda img: self.open_image(img, "Ha/OIII master")).exec()

    def _open_star_spikes(self) -> None:
        if self.project is None:
            return
        if self.project.current().is_linear:
            self._show_warning("Stretch the image first — Star Spikes works on the "
                                 "stretched image.")
            return
        from .star_spikes_dialog import StarSpikesDialog
        StarSpikesDialog(self.project.current(), parent=self,
                         on_apply=self._apply_star_spikes).exec()

    def _apply_star_spikes(self, result) -> None:
        if self.project is None or self._busy:
            return
        self.project.run_step(_PrecomputedStep("Star Spikes", result), "")
        self._mark_dirty()
        self.log_panel.append_entry(format_log_entry("Star Spikes", "", None))
        self._clear_warning()
        self._refresh()

    def _open_narrowband(self) -> None:
        if self.project is None:
            return
        if self.project.current().is_linear:
            self._show_warning("Stretch the image first — Narrowband works on the "
                                 "stretched image.")
            return
        if not self.project.current().is_color:
            self._show_warning("Narrowband needs a colour image.")
            return
        from .narrowband_dialog import NarrowbandDialog
        NarrowbandDialog(self.settings, self.project.current(), parent=self,
                         on_apply=self._apply_narrowband).exec()

    def _apply_narrowband(self, result, params) -> None:
        if self.project is None or self._busy:
            return
        self.project.run_step(_PrecomputedStep("Narrowband", result), params)
        self._mark_dirty()
        self.log_panel.append_entry(format_log_entry("Narrowband", params.palette, None))
        self._clear_warning()
        self._refresh()

    def _on_auto_progress(self, i: int, n: int, name: str) -> None:
        self._busy_label_text = f"Auto-enhancing — {name} ({i}/{n})…"
        if self._busy_shown:
            self._busy_label.setText(self._busy_label_text)
        self._set_progress(name, i, n)

    def _auto_enhance(self) -> None:
        if self.project is None:
            self._choose_fits()      # open the file dialog; loads synchronously if a file is picked
            if self.project is None:  # cancelled, or load failed (warning already shown)
                return
        if self._busy:
            return
        if self.project.entries():   # only confirm when there are edits to discard (not a fresh import)
            resp = QMessageBox.question(
                self, "Auto Enhance",
                "This discards your current edits and runs Auto Enhance from the "
                "original image. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if resp != QMessageBox.StandardButton.Yes:
                return
        self.project.jump_back(0)   # reset to the linear base (import state)
        base = self.project.current()
        plan = build_auto_plan(base, self.settings)
        self._clear_warning()

        def work():
            return run_auto_plan(
                base, plan, self.settings,
                bg_runner=self._bg_runner, rc_runner=self._rc_runner,
                on_progress=lambda i, n, name: self._auto_signals.progress.emit(i, n, name),
            )

        def on_result(results) -> None:
            for name, option, img in results:
                self.project.record_precomputed(name, option, img)
            if results:
                self._mark_dirty()
            self._rebuild_panel()
            self._refresh()
            msg = f"Auto-enhanced — {len(results)} steps"
            if not graxpert_valid(self.settings):
                msg += ". Install GraXpert (free) for better background & noise."
            if not rcastro_valid(self.settings):
                msg += " RC-Astro (StarX/NoiseX) gives cleaner stars & denoise, if you have it."
            self._show_output(msg)

        self._run_busy(work, on_result, "Auto-enhancing…", "Auto Enhance failed")

    def _solve_current(self, img):
        """Blocking solve of a snapshotted display image; returns (SolveResult, objects)."""
        from ..tools.astap import ASTAP, hint_from_metadata
        from ..core.catalog import objects_in_field
        meta = img.metadata
        h, w = img.data.shape[:2]
        # FOV from focal length + pixel size if known.
        fov = None
        fl, px = meta.get("focal_length"), meta.get("pixel_size")
        if fl and px:
            fov = (206.265 * float(px) / float(fl)) * h / 3600.0
        hint = hint_from_metadata(meta)
        ra_h, dec_d = hint if hint else (None, None)
        res = ASTAP(resolve_binary(self.settings.astap_path)).solve(
            img, fov_deg=fov, ra_hours=ra_h, dec_deg=dec_d,
            header_cards=meta.get("solve_cards"))
        objs = objects_in_field(res.wcs, (h, w)) if res.solved else []
        return res, objs

    def _open_plate_solve(self):
        """Toggle the annotation overlay. If it's showing, hide it. Otherwise
        show it — reusing the cached solution for this framing, or solving once
        if there isn't one. The toolbar action's checked state mirrors whether
        the overlay is visible."""
        if self.image_view._annotations is not None:        # currently shown -> hide
            self.image_view.set_annotations(None)
            self._solve_act.setChecked(False)
            return
        if self.project is None or not astap_valid(self.settings):
            self._solve_act.setChecked(False)
            if self.project is not None:
                self._show_warning("Set the ASTAP path in Settings to plate-solve.")
            return
        sig = self._solve_sig()
        if self._solve and self._solve[0] == sig:           # cached solution: just show it
            self._show_annotations(*self._solve[1:])
            self._solve_act.setChecked(True)
            return
        self._show_output("Plate-solving…")
        self._run_busy(lambda: self._solve_current(self.project.current()),
                       lambda r: self._on_solved(sig, *r),
                       "Plate-solving…", "Plate-solve failed")

    def _on_solved(self, sig, res, objs):
        if not res.solved:
            hint = f" (ASTAP: {res.message.splitlines()[-1]})" if res.message else ""
            self._show_warning("Couldn't plate-solve this image — try after Stretch, "
                                 "or check the field isn't mostly empty." + hint)
            self._solve_act.setChecked(False)
            return
        if self._solve_sig() != sig:
            self._solve_act.setChecked(False)
            return   # framing changed (crop/rotate/flip) while solving — discard
        self._solve = (sig, res, objs)
        from ..core.catalog import identify_target
        h, w = self.project.current().data.shape[:2]
        name = identify_target(objs, (h, w))
        if name:
            # Project.current() returns a fresh copy each call (loaded from the
            # on-disk cache), so a mutation on it is lost immediately; write
            # through to the project's cached metadata for the current position.
            self.project.set_current_metadata("target_solved", name)
        self._clear_warning()
        self._show_annotations(res, objs)
        self._solve_act.setChecked(True)
        self._rebuild_panel()                               # refresh Target line

    def _show_annotations(self, res, objs):
        from ..core.annotate import compass_angles, scale_bar
        from ..core.catalog import named_stars_in_field
        from .annotation_overlay import build_annotation_group
        h, w = self.project.current().data.shape[:2]
        north, _east = compass_angles(res.wcs, (h, w))
        length, label = scale_bar(res.pixscale_arcsec, w)
        stars = named_stars_in_field(res.wcs, (h, w))
        self.image_view.set_annotations(
            build_annotation_group(objs, north, length, label, (h, w), "dark", stars=stars))

    def _remove_stars(self, img):
        if rcastro_valid(self.settings):
            rc = RCAstro(resolve_binary(self.settings.rcastro_path))
            return rc.remove_stars(img, runner=self._rc_runner)
        return split_stars(img)

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Main")
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        # File
        tb.addAction(load_icon("open"), "Open FITS", self._choose_fits)
        # Projects (a saved bundle: image + full edit history + solve state) — a
        # distinct concept from Open FITS (a source) and Save Recipe (steps only),
        # tinted with the accent so the two project actions read as a pair.
        self._open_project_act = tb.addAction(
            load_icon("open", ACCENT), "Open Project", lambda: self._open_project())
        self._open_project_act.setToolTip("Open a saved .nocturne project")
        self._save_project_act = tb.addAction(
            load_icon("save-recipe", ACCENT), "Save Project", self._save_project)
        self._save_project_act.setToolTip("Save the current project (image + full edit history)")
        self._save_project_act.setEnabled(False)  # enabled by _refresh once an image is loaded
        tb.addAction(load_icon("settings"), "Settings", self._open_settings)
        tb.addSeparator()
        # Tools (primary features tinted with the accent)
        self._save_recipe_act = tb.addAction(load_icon("save-recipe"), "Save Recipe", self._save_recipe)
        tb.addAction(load_icon("batch"), "Batch…", self._open_batch)
        tb.addAction(load_icon("stack", ACCENT), "Stack…", self._open_stack)
        # Distinct glyph + a muted per-tool tint so these tools are easy to tell
        # apart (the shared icon caused mis-clicks). Colours are a gentle secondary
        # cue — the glyphs do the work — and easy to tweak later.
        tint = {
            "haoiii": "#5b93d1",       # blue
            "star-spikes": "#7d8ed6",  # indigo
            "narrowband": "#a284c9",   # violet
            "auto-enhance": "#c99a5b",  # warm gold
            "plate-solve": "#5faa8c",  # teal-green
            "share": "#5aa9c9",        # cyan
            "upscale": "#cf8f9b",      # muted rose
        }
        tb.addAction(load_icon("haoiii", tint["haoiii"]), "Ha/OIII…", self._open_haoiii)
        tb.addAction(load_icon("star-spikes", tint["star-spikes"]), "Star Spikes…", self._open_star_spikes)
        tb.addAction(load_icon("narrowband", tint["narrowband"]), "Narrowband…", self._open_narrowband)
        self._auto_enhance_act = tb.addAction(load_icon("auto-enhance", tint["auto-enhance"]), "Auto Enhance",
                                              self._auto_enhance)
        self._solve_act = tb.addAction(load_icon("plate-solve", tint["plate-solve"]), "Plate Solve",
                                       self._open_plate_solve)
        self._solve_act.setCheckable(True)   # checked = annotations shown; click toggles
        self._solve_act.setToolTip("Plate-solve and show/hide the annotation overlay")
        self._share_act = tb.addAction(load_icon("share", tint["share"]), "Share", self._share)
        self._share_act.setEnabled(False)
        self._upscale_act = tb.addAction(load_icon("upscale", tint["upscale"]), "Upscale Crop", self._upscale)
        self._upscale_act.setEnabled(False)
        tb.addSeparator()
        # Edit / compare
        self._undo_act = tb.addAction(load_icon("undo"), "Undo", self._undo)
        self._redo_act = tb.addAction(load_icon("redo"), "Redo", self._redo)
        self._reset_act = tb.addAction(load_icon("reset"), "Reset", self._reset_image)
        self._reset_act.setEnabled(False)  # enabled by _refresh once an image is loaded
        self._ba_act = tb.addAction(load_icon("before-after"), "Before/After", self._toggle_before_after)
        self._ba_act.setCheckable(True)
        self._log_act = tb.addAction(load_icon("log"), "Log", self._toggle_log)
        self._log_act.setCheckable(True)
        self._log_act.setChecked(True)
        tb.addSeparator()
        # View
        tb.addAction(load_icon("fit"), "Fit", self.image_view.fit)
        tb.addAction(load_icon("actual-size"), "100%", self.image_view.actual_size)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        self._about_btn_act = tb.addAction(load_icon("about"), "About", self._show_about)
        self._update_act = tb.addAction(load_icon("update", WARNING),
                                        "Update available", self._open_download)
        self._update_act.setVisible(False)   # revealed only when a newer release exists
        self._tools_label = QLabel("")
        tb.addWidget(self._tools_label)
        self._update_tools_label()

    def _update_tools_label(self) -> None:
        def chip(name: str, ok: bool) -> str:
            color = "#3fb950" if ok else "#f85149"  # green / red
            mark = "✓" if ok else "✗"
            # Label in the normal interface colour; only the mark is coloured.
            return f'{name} <span style="color:{color}">{mark}</span>'

        self._tools_label.setText(
            chip("GraXpert", graxpert_valid(self.settings))
            + '  <span style="color:#6b6f76">·</span>  '
            + chip("RC-Astro", rcastro_valid(self.settings))
            + '  <span style="color:#6b6f76">·</span>  '
            + chip("ASTAP", astap_valid(self.settings))
        )

    # --- navigation ---
    def current_stage_id(self) -> str:
        return self._stages[self._stage].id

    def go_next(self) -> None:
        self._go_to(next_enabled(self._stages, self._stage))

    def go_back(self) -> None:
        self._go_to(prev_enabled(self._stages, self._stage))

    def _ensure_stretched(self) -> None:
        """Commit a default Stretch (amount 0.5) at the stretch position so the
        post-stretch finishing steps have real stretched data. The caller invokes
        this only when the current image is still linear."""
        preceding = set(GEOMETRY_NAMES) | {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index("stretch")]
        }
        self.project.jump_back(self._leading_kept(self.project.entries(), preceding))
        base = self.project.current()
        result = self._step_for("stretch").apply(base, "")   # "" -> default amount 0.5
        self.project.run_step(_PrecomputedStep("Stretch", result), "")
        self._mark_dirty()
        self.log_panel.append_entry(
            format_log_entry("Stretch", "auto", rms_delta(base, result)))

    def _go_to(self, index: int) -> None:
        if not (0 <= index < len(self._stages)) or not self._stages[index].enabled:
            return
        if (self.project is not None
                and self._stages[index].id in POST_STRETCH_IDS
                and self.project.current().is_linear):
            self._ensure_stretched()
        self._stage = index
        self._clear_warning()  # clear any stale error when changing steps
        if self.image_view.compare_active():  # before/after is per-image; reset on nav
            self._ba_act.setChecked(False)
            self.image_view.set_compare(None)
        self._rebuild_panel()
        self._refresh()

    def _go_to_id(self, stage_id: str) -> None:
        for i, s in enumerate(self._stages):
            if s.id == stage_id:
                self._go_to(i)
                return

    # --- file / project ---
    def _choose_fits(self) -> None:
        path = QFileDialog.getOpenFileName(self, "Open FITS", start_dir(self.settings.base_dir), "FITS (*.fit *.fits)")[0]
        if path:
            self.open_fits(path)

    def open_fits(self, path: str) -> None:
        if not self._confirm_save_if_dirty():
            return
        try:
            base = load_fits(path)
        except Exception as exc:
            self._show_warning(f"Could not open file: {exc}")
            return
        self._project_path = None  # a freshly-opened FITS is not tied to any prior bundle
        self.open_image(base, os.path.basename(path))

    def open_image(self, base, label: str) -> None:
        self._source_base = base
        self._source_label = label
        self._clear_cache()   # drop a prior session's stale snapshots before the new project writes its own
        os.makedirs(self._cache_dir, exist_ok=True)
        self.project = Project(base, self._cache_dir)
        self._center_stack.setCurrentWidget(self.image_view)
        self._show_chrome(True)  # reveal stepper + panel now there's an image
        self._clear_warning()
        self.log_panel.clear_log()   # fresh image → fresh message channels
        self.output_panel.clear()
        h, w = base.data.shape[:2]
        self.log_panel.append_entry(
            format_log_entry(f"Opened {label}", "", None, dims=(w, h))
        )
        self._go_to_id("load")  # stay on Import & assess so the user sees metadata
        self._rebuild_panel()
        self._dirty = False
        self._update_title()
        self._refresh()

    # --- saved projects (.nocturne bundles: image + full edit history + solve state) ---
    def _save_project(self) -> None:
        if self.project is None:
            return
        if self._project_path is None:
            self._save_project_as()
            return
        self._do_save_project(self._project_path)

    def _save_project_as(self) -> None:
        if self.project is None:
            return
        start = start_dir(self.settings.last_project_dir) or start_dir(self.settings.base_dir)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", start, "Nocturne project (*.nocturne)")
        if not path:
            return
        if not path.lower().endswith(".nocturne"):
            path += ".nocturne"
        self.settings.last_project_dir = os.path.dirname(path)
        self._do_save_project(path)

    def _do_save_project(self, path: str) -> None:
        """Write the project to `path` off the UI thread (busy panel + cancel),
        atomically (temp file + rename — a slow/cancelled save can't corrupt an
        existing bundle at `path`). Solve state and source label are captured
        here, on the UI thread, before the worker starts."""
        solve_state = self._solve_state_dict()
        source_label = self._source_label

        def work():
            save_project(self.project, path, solve_state=solve_state, source_label=source_label,
                         on_progress=lambda d, t: self._save_signals.progress.emit(d, t))

        def on_result(_result) -> None:
            self._project_path = path
            self._dirty = False
            self._update_title()
            add_recent_project(self.settings, path)
            save_settings(self.settings, self._settings_path)
            self._show_output(f"Saved project: {os.path.basename(path)}")

        self._run_busy(work, on_result, "Saving project…", "Save failed")

    def _open_project(self, path: str | None = None) -> None:
        if self._busy:
            return
        if not self._confirm_save_if_dirty():
            return
        if path is None:
            start = start_dir(self.settings.last_project_dir) or start_dir(self.settings.base_dir)
            path, _ = QFileDialog.getOpenFileName(
                self, "Open Project", start, "Nocturne project (*.nocturne)")
            if not path:
                return
        try:
            loaded = load_project(path, self._cache_dir)
        except NewerVersionError:
            self._show_warning(
                "This project was made by a newer version of Nocturne — update the app to open it.")
            return
        except Exception as exc:
            self._show_warning(f"Could not open project: {exc}")
            return
        self.project = loaded.project
        self._source_label = loaded.source_label
        self._project_path = path
        self._dirty = False
        self._update_title()
        self._restore_solve_state(loaded.solve_state)
        self._center_stack.setCurrentWidget(self.image_view)
        self._show_chrome(True)  # reveal stepper + panel now there's an image
        self._clear_warning()
        self.log_panel.clear_log()   # fresh project → fresh message channels
        self.output_panel.clear()
        h, w = self.project.current().data.shape[:2]
        self.log_panel.append_entry(
            format_log_entry(f"Opened project {os.path.basename(path)}", "", None, dims=(w, h))
        )
        entries = self.project.entries()
        self._navigate_to_step(entries[-1][0] if entries else None)   # land on the restored step
        self._rebuild_panel()
        self._refresh()
        self.settings.last_project_dir = os.path.dirname(path)
        add_recent_project(self.settings, path)
        save_settings(self.settings, self._settings_path)

    def _solve_state_dict(self) -> dict | None:
        """Serialize the current plate-solve (if any) to JSON-safe data: the WCS
        header as a plain dict, plus the catalogue objects found in-frame. None
        if unsolved — nothing to persist."""
        if not self._solve:
            return None
        _sig, res, objs = self._solve
        from dataclasses import asdict
        return {
            "wcs": dict(res.wcs.to_header()) if res.wcs is not None else None,
            "objects": [asdict(o) for o in objs],
        }

    def _restore_solve_state(self, d: dict | None) -> None:
        """Best-effort rebuild of self._solve from a saved solve-state dict. Kept
        deliberately contained: any failure here just leaves the project without
        a live solve (re-solve to re-annotate) — it must never break opening the
        project's image itself."""
        self._solve = None
        if not d or not d.get("wcs"):
            return
        try:
            from astropy.io import fits
            from ..core.catalog import CatalogObject
            from ..tools.astap import ASTAP
            header = fits.Header(d["wcs"])
            res = ASTAP._build(header)   # rebuilds WCS + solved fields from the header
            if res is None:
                return
            objs = [CatalogObject(**o) for o in (d.get("objects") or [])]
            self._solve = (self._solve_sig(), res, objs)
        except Exception:
            self._solve = None   # degrade to "re-solve to re-annotate" — never raise

    # --- apply a processing stage ---
    def _step_for(self, stage_id: str):
        return make_step(stage_id, self.settings,
                         bg_runner=self._bg_runner, rc_runner=self._rc_runner)

    @staticmethod
    def _leading_kept(entries, keep_names) -> int:
        """Length of the leading contiguous run of entries whose name is in
        keep_names. Prefix-safe: jump_back keeps a prefix, so we must count a
        prefix, not a total (geometry ops can append after processing ops)."""
        n = 0
        for name, _ in entries:
            if name in keep_names:
                n += 1
            else:
                break
        return n

    def _stretch_preceding(self) -> set:
        """Names of the steps that precede the reveal (stretch) position — the
        predecessors an Apply-Stretch preserves."""
        return set(GEOMETRY_NAMES) | {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index("stretch")]
        }

    def apply_current(self, option) -> None:
        if self.project is None or self._busy:
            return
        stage_id = self._stages[self._stage].id
        if stage_id not in PROCESSING_ORDER:
            return
        if stage_id == "levels" and self.project.current().is_linear:
            # Levels remaps [black, white] in display space; on a still-linear
            # image (values ~0.003) any black point clips the whole frame to
            # black. Require a stretch first instead of producing a black image.
            self._show_warning(
                "Apply Stretch first — Levels works on the stretched image.")
            return
        # Truncate history to this stage's applied predecessors (synchronous).
        preceding = set(GEOMETRY_NAMES) | {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index(stage_id)]
        }
        target = self._leading_kept(self.project.entries(), preceding)
        self.project.jump_back(target)
        if stage_id == "background" and option == "off":
            # "off" = no background extraction: drop any prior result, record nothing
            self._clear_warning()
            self.log_panel.append_entry(format_log_entry("Background", "off", None) + " — skipped")
            self._refresh()
            return
        step = self._step_for(stage_id)
        base = self.project.current()
        self._clear_warning()

        def on_result(result):
            self.project.run_step(_PrecomputedStep(STEP_NAME[stage_id], result), option)
            self._mark_dirty()
            self._log_step(stage_id, option, base, result)
            self._refresh()  # stay on this step; user clicks Next to advance
            msg = getattr(step, "last_message", "")
            if msg:
                self._show_output(msg)

        self._run_busy(lambda: step.apply(base, option), on_result,
                       self._busy_label_for(stage_id, option), "Failed")

    def _busy_label_for(self, stage_id: str, option) -> str:
        """Busy message for an apply. GraXpert AI denoise takes minutes (inherent
        to the model, confirmed vs Siril), so warn when it's the engine running."""
        if (stage_id == "noise_sharpen" and isinstance(option, dict)
                and option.get("engine") == "graxpert" and graxpert_valid(self.settings)):
            return "Denoising with GraXpert — this can take a few minutes…"
        if stage_id == "color" and getattr(option, "method", "sky") == "photometric":
            return "Calibrating colour…"
        return f"Applying {STEP_NAME[stage_id]}…"

    def _log_step(self, stage_id: str, option, base, result) -> None:
        name = STEP_NAME[stage_id]
        if stage_id in ("color", "levels", "curves"):
            label = ""  # option is a settings object/tuple, not user-facing text
        elif stage_id == "saturation" and isinstance(option, (tuple, list)):
            label = f"{float(option[0]):.2f} / neb {float(option[1]):.2f}"
        elif stage_id == "noise_sharpen" and isinstance(option, dict):
            label = f"{option.get('level', 'medium')} ({option.get('engine') or 'auto'})"
        elif isinstance(option, float):
            label = f"{option:.2f}"
        else:
            label = option
        self.log_panel.append_entry(format_log_entry(name, label, rms_delta(base, result)))

    def _run_busy(self, work, on_result, label: str, err_prefix: str) -> None:
        """Run `work` off the UI thread with busy indication; `on_result(result)`
        on success, `f"{err_prefix}: {exc}"` in the status label on failure.
        Busy is always cleared in a finally (even if `on_result` raises).

        Publishes a `CancelToken` (`self._active_token`) so `_cancel_active()` can
        request a clean stop; the token is set as the AMBIENT token on the worker
        thread itself (inside `wrapped`, not here on the UI thread) so `run_cli`
        and friends can see it via `nocturne.core.tasks.current()`. A `Cancelled`
        raised by `work` is treated as a clean stop, not an error."""
        token = CancelToken()
        self._active_token = token
        self._busy_start = _time.monotonic()
        self._set_busy(True, label)

        def wrapped():
            set_ambient(token)
            try:
                return work()
            finally:
                clear_ambient()

        def done(result):
            try:
                on_result(result)
            finally:
                self._active_token = None
                self._set_busy(False)

        def err(exc):
            try:
                if isinstance(exc, Cancelled):
                    self._show_output("Cancelled.")     # neutral channel, not a warning
                elif isinstance(exc, ToolError):
                    self._report_tool_error(err_prefix, exc)
                else:
                    self._show_warning(f"{err_prefix}: {exc}")
            finally:
                self._active_token = None
                self._set_busy(False)

        if self._async_enabled:
            run_async(self._pool, wrapped, done, err)
        else:
            try:
                result = wrapped()
            except Exception as exc:  # mirror the async error path
                err(exc)
            else:
                done(result)          # an on_result throw propagates after the finally

    def _cancel_active(self) -> None:
        """Request a clean stop of the currently-running busy op, if any."""
        tok = self._active_token
        if tok is not None:
            tok.cancel()

    def elapsed_seconds(self) -> float:
        """Seconds since the current busy op started; 0.0 when idle."""
        return _time.monotonic() - self._busy_start if self._busy else 0.0

    def _set_busy(self, busy: bool, label: str = "Working…") -> None:
        self._busy = busy
        if busy:
            self._busy_label_text = label
            self._busy_timer.start(BUSY_DELAY_MS)   # visuals only if op outlasts it
        else:
            self._busy_timer.stop()
            self._hide_busy_visuals()               # no-op if visuals never showed
        self._back_btn.setDisabled(busy)            # gating stays immediate
        self._next_btn.setDisabled(busy)
        if hasattr(self._panel, "apply_btn"):
            self._panel.apply_btn.setDisabled(busy)

    def _show_busy_visuals(self) -> None:
        self._busy_bar.show_over(self.image_view)
        self._ellipsis_n = 0
        self._busy_label.setText(self._busy_label_text)
        self._ellipsis_timer.start()
        if not self._cursor_active:
            QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
            self._cursor_active = True
        self._busy_shown = True
        self._cancel_btn.show()
        self._elapsed_label.show()
        self._tick_elapsed()            # paint "0s" immediately, don't wait for the first tick
        self._elapsed_timer.start()
        self._apply_progress_state()    # reflect any progress reported before visuals appeared

    def _hide_busy_visuals(self) -> None:
        self._ellipsis_timer.stop()
        self._elapsed_timer.stop()
        if self._busy_shown:
            self._busy_bar.hide_bar()
            self._busy_label.setText("")
        if self._cursor_active:
            QApplication.restoreOverrideCursor()
            self._cursor_active = False
        self._busy_shown = False
        self._cancel_btn.hide()
        self._elapsed_label.hide()
        self._elapsed_label.setText("")
        self._progress_state = ("", 0, 0)
        self._progress.reset()
        self._progress.hide()

    def _tick_ellipsis(self) -> None:
        self._ellipsis_n = (self._ellipsis_n + 1) % 4
        self._busy_label.setText(self._busy_label_text + "." * self._ellipsis_n)

    def _tick_elapsed(self) -> None:
        self._elapsed_label.setText(f"{self.elapsed_seconds():.0f}s")

    def _set_progress(self, phase: str, done: int, total: int) -> None:
        """Drive the determinate progress bar; `total == 0` falls back to the
        indeterminate BusyBar sweep (the bar itself is simply hidden)."""
        self._progress_state = (phase, done, total)
        if self._busy_shown:
            self._apply_progress_state()

    def _apply_progress_state(self) -> None:
        phase, done, total = self._progress_state
        if total > 0:
            self._progress.setMaximum(total)
            self._progress.setValue(done)
            self._progress.setFormat(f"{phase} — %v/%m" if phase else "%v/%m")
            self._progress.show()
        else:
            self._progress.hide()

    # --- crop overlay ---
    def _setup_crop_overlay(self) -> None:
        if self.project is not None and self.current_stage_id() == "crop":
            bounds = detect_content_bounds(self.project.current())
            aspect_text = "Original"
            if hasattr(self._panel, "aspect_box"):
                aspect_text = self._panel.aspect_box.currentText()
            # Crop mode on, box hidden until the first image click shows it.
            self.image_view.set_crop_overlay(
                True, content_bounds=bounds, aspect_ratio=_ASPECT_RATIO.get(aspect_text)
            )
            if hasattr(self._panel, "apply_btn"):
                self._panel.apply_btn.setEnabled(False)
            if hasattr(self._panel, "crop_size_label"):
                self._panel.crop_size_label.setText("—")
        else:
            self.image_view.set_crop_overlay(False)

    def _on_crop_box_shown(self) -> None:
        """Crop box became visible (first click) — enable Apply Crop."""
        if self.current_stage_id() == "crop" and hasattr(self._panel, "apply_btn"):
            self._panel.apply_btn.setEnabled(True)
        if self.current_stage_id() == "crop" and hasattr(self._panel, "crop_size_label"):
            self._update_crop_readout(*self.image_view.crop_bounds())

    def _update_crop_readout(self, t: int, b: int, l: int, r: int) -> None:
        if (self.current_stage_id() == "crop" and self.image_view.crop_box_visible()
                and hasattr(self._panel, "crop_size_label")):
            self._panel.crop_size_label.setText(f"{r - l} × {b - t} px")

    def _on_crop_dismiss(self) -> None:
        """Clicking the dimmed area (or Esc) hides the box without applying. Only
        confirm if the user actually adjusted it — a fresh, untouched box has no
        work to lose, so it dismisses silently."""
        if not self.image_view.crop_box_visible():
            return
        if self.image_view.crop_box_modified():
            resp = QMessageBox.question(
                self, "Discard crop?",
                "Discard your crop selection?",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Discard,
                QMessageBox.StandardButton.Cancel,
            )
            if resp != QMessageBox.StandardButton.Discard:
                return
        self.image_view.hide_crop_box()
        if hasattr(self._panel, "apply_btn"):
            self._panel.apply_btn.setEnabled(False)
        if hasattr(self._panel, "crop_size_label"):
            self._panel.crop_size_label.setText("—")

    def _on_crop_change(self, aspect_text: str) -> None:
        # Snap the visible box to the chosen ratio (and lock future resizes).
        self.image_view.apply_aspect(_ASPECT_RATIO.get(aspect_text))

    def _on_guides_change(self, kind: str) -> None:
        self.image_view.set_guides(kind)

    def _enhance(self, op: str) -> None:
        if self.project is None or self._busy:
            return
        if op == "Star Colour":
            self._enhance_star_colour()
            return
        result = ENHANCE_OPS[op](self.project.current())
        self.project.run_step(_PrecomputedStep(op, result), "")
        self._mark_dirty()
        self.log_panel.append_entry(format_log_entry(op, "", None))
        self._clear_warning()
        self._refresh()

    def _enhance_star_colour(self) -> None:
        """Star Colour boosts saturation on the STARS layer of a proper
        star/starless split (StarXTerminator when RC-Astro is set, else the free
        sep-based split — same `_remove_stars` the rest of the app uses), then
        screens the untouched starless back, so nebulosity and sky are never
        affected. The split is slow, so it runs off the UI thread with a busy
        panel; recomputed each tap."""
        base = self.project.current()

        def work():
            starless, stars = self._remove_stars(base)
            return star_colour_layers(starless, stars)

        def on_result(result) -> None:
            self.project.run_step(_PrecomputedStep("Star Colour", result), "")
            self._mark_dirty()
            self.log_panel.append_entry(format_log_entry("Star Colour", "", None))
            self._clear_warning()
            self._refresh()

        self._run_busy(work, on_result, "Enhancing star colour…", "Star colour failed")

    def _apply_geometry(self, name: str, params) -> None:
        if self.project is None or self._busy:
            return
        self.project.jump_back(self._leading_kept(self.project.entries(), set(GEOMETRY_NAMES)))
        result = self._step_for("crop").apply(self.project.current(), params)
        self.project.run_step(_PrecomputedStep(name, result), "")
        self._mark_dirty()
        self.log_panel.append_entry(format_log_entry(name, "", None))
        self._clear_warning()
        self._refresh()
        self._setup_crop_overlay()

    def _rotate(self) -> None:
        self._apply_geometry("Rotate", CropParams(rotate=90))

    def _flip_h(self) -> None:
        self._apply_geometry("Flip H", CropParams(flip_h=True))

    def _flip_v(self) -> None:
        self._apply_geometry("Flip V", CropParams(flip_v=True))

    def _remove_green(self, strength: float = 1.0) -> None:
        if self.project is None or self._busy:
            return
        strength = float(strength)
        idx = PROCESSING_ORDER.index("remove_green")
        preceding = set(GEOMETRY_NAMES) | {
            STEP_NAME[sid] for sid in PROCESSING_ORDER[:idx]
        }
        self.project.jump_back(self._leading_kept(self.project.entries(), preceding))
        base = self.project.current()
        result = self._step_for("remove_green").apply(base, strength)
        self.project.run_step(_PrecomputedStep("Remove Green", result), strength)
        self._mark_dirty()
        self.log_panel.append_entry(
            format_log_entry("Remove Green", f"{strength:.2f}", rms_delta(base, result)))
        self._clear_warning()
        self._refresh()

    def _on_removegreen_change(self, strength: float) -> None:
        """Live-preview SCNR at the slider strength on the pre-remove-green base
        (== what the commit operates on, so preview == apply)."""
        self._rg_pending = float(strength)
        self._rg_timer.start(90)

    def _render_removegreen_preview(self) -> None:
        if self.project is None or self.current_stage_id() != "color" or self._rg_pending is None:
            return
        # Color is a PRE-stretch step, so the image is linear — display it through
        # to_qimage (which auto-stretches), not _show_preview (which assumes
        # display-space data and would render linear values as near-black).
        result = remove_green(self._preview_base("remove_green"), self._rg_pending)
        self._set_peek(False)
        self._displayed = result
        self.image_view.set_image(to_qimage(result))
        self.histogram_view.set_image(result)

    def _apply_crop(self) -> None:
        if self.project is None or self._busy:
            return
        top, bottom, left, right = self.image_view.crop_bounds()
        h, w = self.project.current().data.shape[:2]
        if (top, bottom, left, right) == (0, h, 0, w):
            return  # box is the full frame -> no real crop
        self._apply_geometry("Crop", CropParams(bounds=(top, bottom, left, right)))
        # Committed: hide the box; the next click re-shows it at the new edges.
        self.image_view.hide_crop_box()
        if hasattr(self._panel, "crop_size_label"):
            self._panel.crop_size_label.setText("—")

    # --- levels live preview ---
    def _on_levels_change(self, black: float, gamma: float, white: float) -> None:
        """A Levels slider moved: stash the values and (re)start the debounce."""
        self._levels_pending = (black, gamma, white)
        self._levels_timer.start(90)

    def _on_levels_auto(self) -> None:
        if self.project is None or self.current_stage_id() != "levels":
            return
        b, g, w = auto_levels(self.project.current().data)
        # Setting the sliders fires _on_levels_change (which debounces a render).
        self._panel.black_slider.setValue(round(b * 100))
        self._panel.gamma_slider.setValue(round(g * 100))
        self._panel.white_slider.setValue(round(w * 100))
        self._render_levels_preview()

    def _on_levels_clipping(self, checked: bool) -> None:
        self._levels_show_clipping = bool(checked)
        self._render_levels_preview()

    def _preview_base(self, stage_id: str):
        """The pre-<stage> image the commit also operates on, so a live preview
        equals what Apply will produce (WYSIWYG)."""
        preceding = set(GEOMETRY_NAMES) | {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index(stage_id)]
        }
        return self.project.state_at(
            self._leading_kept(self.project.entries(), preceding))

    def _show_preview(self, out, rgb=None) -> None:
        """Push a previewed float array to BOTH the canvas and the histogram, so
        the histogram tracks the slider live. `rgb` overrides the canvas pixels
        (e.g. the Levels clipping overlay); the histogram always uses clean `out`."""
        out = np.clip(out, 0.0, 1.0).astype(np.float32)
        if rgb is None:
            rgb = (out * 255 + 0.5).astype(np.uint8)
            if rgb.ndim == 2:
                rgb = np.repeat(rgb[:, :, None], 3, axis=2)
        self._set_peek(False)   # a fresh preview repaint always shows the 'after'
        self._displayed = AstroImage(out, is_linear=False)
        self.image_view.set_image(rgb_to_qimage(np.ascontiguousarray(rgb)))
        self.histogram_view.set_image(self._displayed)

    def _render_levels_preview(self) -> None:
        """Non-committing live preview of the current Levels settings, with an
        optional shadow/highlight clipping overlay."""
        if self.project is None or self.current_stage_id() != "levels":
            return
        if self._levels_pending is not None:
            b, g, w = self._levels_pending
        else:
            b = self._panel.black_slider.value() / 100.0
            g = self._panel.gamma_slider.value() / 100.0
            w = self._panel.white_slider.value() / 100.0
        img = self._preview_base("levels")
        out = np.clip(apply_levels(img, b, g, w).data, 0, 1)
        rgb = (out * 255 + 0.5).astype(np.uint8)
        if rgb.ndim == 2:
            rgb = np.repeat(rgb[:, :, None], 3, axis=2)
        rgb = np.ascontiguousarray(rgb)
        if self._levels_show_clipping:
            sh, hi = clipping_masks(img.data, b, w)
            rgb[sh] = (40, 120, 255)
            rgb[hi] = (255, 60, 40)
        self._show_preview(out, rgb)

    # --- stretch live preview ---
    def _on_stretch_change(self, amount: float) -> None:
        """The Stretch aggressiveness slider moved: stash + (re)start the debounce."""
        self._stretch_pending = amount
        self._stretch_timer.start(90)

    def _render_stretch_preview(self) -> None:
        """Non-committing live preview of the Stretch aggressiveness."""
        if self.project is None or self.current_stage_id() != "stretch":
            return
        img = self._preview_base("stretch")
        amount = (self._stretch_pending if self._stretch_pending is not None
                  else self._panel.stretch_slider.value() / 100.0)
        self._show_preview(apply_stretch(img, amount).data)

    # --- saturation live preview (global + lazy cached-split nebula boost) ---
    def _sat_preceding(self) -> set:
        return set(GEOMETRY_NAMES) | {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index("saturation")]
        }

    def _setup_saturation(self) -> None:
        """On entering Saturation: the Nebula slider is always enabled. The global
        slider always works; the split (StarX or the free fallback) is deferred
        until the Nebula slider is first raised (lazy)."""
        self._sat_pending = None
        if self.project is None or not hasattr(self._panel, "neb_slider"):
            return
        self._panel.neb_slider.setEnabled(True)
        self._panel.neb_status.setText("" if rcastro_valid(self.settings) else _FREE_STAR_NOTE)

    def _on_sat_change(self, amount: float, nebula: float) -> None:
        """A Saturation slider moved: stash both values; lazily split for the
        nebula boost; (re)start the debounce."""
        self._sat_pending = (amount, nebula)
        if nebula > 0.0 and not self._busy:
            base = self._preview_base("saturation")
            sig = self._sr_sig(base)
            if not (self._sat_layers and self._sat_layers[0] == sig):
                self._panel.neb_status.setText("Separating stars…")
                self._run_busy(lambda: self._remove_stars(base),
                               lambda layers: self._on_sat_split(sig, layers),
                               "Separating stars…", "Star separation failed")
        self._sat_timer.start(90)

    def _on_sat_split(self, sig, layers) -> None:
        if self.current_stage_id() != "saturation":
            return
        self._sat_layers = (sig, layers[0], layers[1])
        if hasattr(self._panel, "neb_status"):
            self._panel.neb_status.setText(
                "" if rcastro_valid(self.settings) else _FREE_STAR_NOTE)
        self._render_saturation_preview()

    def _sat_result(self, base, amount, nebula):
        """The Saturation output for the given base: nebula boost (from the cached
        split, when available) then the global saturate. Falls back to global-only
        when the split isn't ready."""
        img = base
        if nebula > 0.0 and self._sat_layers and self._sat_layers[0] == self._sr_sig(base):
            _, starless, stars = self._sat_layers
            img = nebula_saturate(starless, stars, nebula)
        return saturate(img, amount)

    def _render_saturation_preview(self) -> None:
        """Non-committing live preview of Saturation + Nebula boost."""
        if self.project is None or self.current_stage_id() != "saturation":
            return
        if self._sat_pending is not None:
            amount, nebula = self._sat_pending
        else:
            amount = self._panel.sat_slider.value() / 100.0
            nebula = self._panel.neb_slider.value() / 100.0
        base = self._preview_base("saturation")
        self._show_preview(self._sat_result(base, amount, nebula).data)

    def _apply_saturation(self, amount: float, nebula: float) -> None:
        """Commit Saturation (+ Nebula boost) using the cached split — instant."""
        if self.project is None or self._busy:
            return
        self.project.jump_back(
            self._leading_kept(self.project.entries(), self._sat_preceding()))
        base = self.project.current()
        result = self._sat_result(base, amount, nebula)
        self.project.run_step(_PrecomputedStep("Saturation", result), (amount, nebula))
        self._mark_dirty()
        self.log_panel.append_entry(
            format_log_entry("Saturation", f"{amount:.2f} / neb {nebula:.2f}", None))
        self._clear_warning()
        self._refresh()

    # --- local contrast live preview ---
    def _on_lc_change(self, amount: float) -> None:
        """The Local Contrast slider moved: stash the value and (re)start debounce."""
        self._lc_pending = amount
        self._lc_timer.start(90)

    def _render_lc_preview(self) -> None:
        """Non-committing live preview of the current Local Contrast setting."""
        if self.project is None or self.current_stage_id() != "local_contrast":
            return
        img = self._preview_base("local_contrast")
        amount = (self._lc_pending if self._lc_pending is not None
                  else self._panel.lc_slider.value() / 100.0)
        self._show_preview(enhance(img, amount).data)

    # --- recover core live preview ---
    def _on_recover_change(self, amount: float) -> None:
        """The Recover Core slider moved: stash the value and (re)start debounce."""
        self._recover_pending = amount
        self._recover_timer.start(90)

    def _render_recover_preview(self) -> None:
        """Non-committing live preview of the current Recover Core setting."""
        if self.project is None or self.current_stage_id() != "recover_core":
            return
        img = self._preview_base("recover_core")
        amount = (self._recover_pending if self._recover_pending is not None
                  else self._panel.recover_slider.value() / 100.0)
        self._show_preview(recover_core(img, amount).data)

    # --- curves live preview ---
    def _on_curve_change(self, points) -> None:
        """The curve was edited: stash the points and (re)start debounce."""
        self._curve_pending = list(points)
        self._curve_timer.start(90)

    def _render_curve_preview(self) -> None:
        """Non-committing live preview of the current curve."""
        if self.project is None or self.current_stage_id() != "curves":
            return
        img = self._preview_base("curves")
        points = (self._curve_pending if self._curve_pending is not None
                  else self._panel.curve_editor.points())
        self._show_preview(apply_curve(img, points).data)

    def _on_curve_preset(self, kind: str) -> None:
        """Reset or Add-contrast preset button: seed the editor's points."""
        if self.project is None or self.current_stage_id() != "curves":
            return
        if kind == "add_contrast":
            pts = gentle_s_points(self._preview_base("curves").data)
        else:
            pts = [(0.0, 0.0), (1.0, 1.0)]
        self._panel.curve_editor.set_points(pts)   # emits curveChanged -> preview

    # --- green fringe live preview (cached StarX split) ---
    def _fringe_preceding(self) -> set:
        """Names of the steps that precede Remove Green Fringe — the predecessors
        a commit preserves (and whose state the split runs on)."""
        return set(GEOMETRY_NAMES) | {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index("green_fringe")]
        }

    def _fringe_base(self):
        """The pre-Remove-Green-Fringe image the split + commit both operate on."""
        return self.project.state_at(
            self._leading_kept(self.project.entries(), self._fringe_preceding()))

    def _setup_green_fringe(self) -> None:
        """On entering Remove Green Fringe: run the split (StarX, or the free
        fallback without RC-Astro) once, off-thread, and cache it. The slider
        then previews the instant de-green recombine. A cached split for the
        same base is reused; without RC-Astro a note is shown but the
        slider/Apply stay enabled."""
        self._fringe_pending = None
        if self.project is None:
            return
        panel = self._panel
        if not rcastro_valid(self.settings) and hasattr(panel, "fringe_status"):
            panel.fringe_status.setText(_FREE_STAR_NOTE)
        # (fall through — the split runs via _remove_stars, free or StarX)
        base = self._fringe_base()
        sig = self._sr_sig(base)
        if self._fringe_layers and self._fringe_layers[0] == sig:
            self._fringe_ready = True
            if hasattr(panel, "fringe_slider"):
                panel.fringe_slider.setEnabled(True)
                panel.apply_btn.setEnabled(True)
                panel.fringe_status.setText(
                    "" if rcastro_valid(self.settings) else _FREE_STAR_NOTE)
            self._render_fringe_preview()
            return
        self._fringe_ready = False
        if hasattr(panel, "fringe_slider"):
            panel.fringe_slider.setEnabled(False)
            panel.apply_btn.setEnabled(False)
            panel.fringe_status.setText("Separating stars…")
        self._run_busy(lambda: self._fringe_prepare(base),
                       lambda payload: self._on_fringe_split(sig, payload),
                       "Separating stars…", "Star separation failed")

    def _fringe_prepare(self, base):
        """Off-thread: build what the fringe preview de-greens. StarX gives a
        clean (starless, stars) split we can de-green cleanly; without RC-Astro
        the split can't isolate a broad chromatic halo, so we cache a widened
        star-neighbourhood mask and de-green the image in place inside it."""
        if rcastro_valid(self.settings):
            starless, stars = self._remove_stars(base)
            return ("split", starless, stars)
        return ("mask", base, star_mask(base, FRINGE_MASK_SCALE))

    def _fringe_result(self, strength) -> AstroImage:
        _, kind, a, b = self._fringe_layers
        if kind == "split":
            return remove_green_fringe(a, b, float(strength))
        return remove_green_fringe_masked(a, b, float(strength))

    def _on_fringe_split(self, sig, payload) -> None:
        if self.current_stage_id() != "green_fringe":
            return
        self._fringe_layers = (sig,) + tuple(payload)
        self._fringe_ready = True
        if hasattr(self._panel, "fringe_slider"):
            self._panel.fringe_slider.setEnabled(True)
            self._panel.apply_btn.setEnabled(True)
            self._panel.fringe_status.setText(
                "" if rcastro_valid(self.settings) else _FREE_STAR_NOTE)
        self._render_fringe_preview()

    def _on_fringe_change(self, strength: float) -> None:
        self._fringe_pending = strength
        if self._fringe_ready:
            self._fringe_timer.start(90)

    def _render_fringe_preview(self) -> None:
        if (self.project is None or self.current_stage_id() != "green_fringe"
                or not self._fringe_ready or not self._fringe_layers):
            return
        strength = (self._fringe_pending if self._fringe_pending is not None
                    else self._panel.fringe_slider.value() / 100.0)
        self._show_preview(self._fringe_result(strength).data)

    def _apply_green_fringe(self, strength) -> None:
        if self.project is None or not self._fringe_ready or self._busy or not self._fringe_layers:
            return
        self.project.jump_back(
            self._leading_kept(self.project.entries(), self._fringe_preceding()))
        result = self._fringe_result(strength)
        self.project.run_step(_PrecomputedStep("Remove Green Fringe", result), float(strength))
        self._mark_dirty()
        self.log_panel.append_entry(
            format_log_entry("Remove Green Fringe", f"{float(strength):.2f}", None))
        self._clear_warning()
        self._refresh()

    # --- star reduction live preview (cached StarX split) ---
    def _sr_preceding(self) -> set:
        """Names of the steps that precede Star Reduction — the predecessors an
        Apply-Star-Reduction preserves (and whose state the split runs on)."""
        return set(GEOMETRY_NAMES) | {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index("star_reduction")]
        }

    def _sr_base(self):
        """The pre-Star-Reduction image the split + commit both operate on."""
        return self.project.state_at(
            self._leading_kept(self.project.entries(), self._sr_preceding()))

    @staticmethod
    def _sr_sig(img):
        """A cheap fingerprint of the base image so a cached split can be reused
        when the user re-enters the step without changing the upstream pipeline."""
        return (img.data.shape,
                round(float(img.data.mean()), 6),
                round(float(img.data.std()), 6))

    def _solve_sig(self):
        """Framing fingerprint for the plate-solve cache: image shape + the
        geometry ops (Crop/Rotate/Flip) in history. The WCS is invariant under
        every TONAL step — background, colour, deconvolution, stretch, denoise,
        star reduction, … don't move stars, they only change pixel values — so a
        solve stays valid until the FRAMING changes. Keying on geometry (not
        pixel content) means we solve ONCE while the stars are still crisp and
        reuse that solution through the star-degrading steps, instead of
        re-solving a heavily-processed image that ASTAP may no longer solve. Only
        Crop/Rotate/Flip change this signature and force a re-solve."""
        if self.project is None:
            return None
        h, w = self.project.current().data.shape[:2]
        geo = tuple((n, repr(o)) for n, o in self.project.entries() if n in GEOMETRY_NAMES)
        return (h, w, geo)

    def _setup_star_reduction(self) -> None:
        """On entering Star Reduction: run the split (StarX, or the free
        fallback without RC-Astro) once, off-thread, and cache it. The slider
        then previews the fast wing-curve instantly. A cached split for the
        same base is reused; without RC-Astro a note is shown but the
        slider/Apply stay enabled."""
        self._sr_pending = None
        if self.project is None:
            return
        panel = self._panel
        if not rcastro_valid(self.settings) and hasattr(panel, "sr_status"):
            panel.sr_status.setText(_FREE_STAR_NOTE)
        base = self._sr_base()
        sig = self._sr_sig(base)
        if self._sr_layers and self._sr_layers[0] == sig:
            # Already split for this exact base — reuse it, no rerun.
            self._sr_ready = True
            if hasattr(panel, "sr_slider"):
                panel.sr_slider.setEnabled(True)
                panel.apply_btn.setEnabled(True)
                panel.sr_status.setText(
                    "" if rcastro_valid(self.settings) else _FREE_STAR_NOTE)
            self._render_sr_preview()
            return
        self._sr_ready = False
        if hasattr(panel, "sr_slider"):
            panel.sr_slider.setEnabled(False)
            panel.apply_btn.setEnabled(False)
            panel.sr_status.setText("Separating stars…")
        self._run_busy(lambda: self._remove_stars(base),
                       lambda layers: self._on_sr_split(sig, layers),
                       "Separating stars…", "Star separation failed")

    def _on_sr_split(self, sig, layers) -> None:
        """The split finished: cache it and enable the slider — unless the
        user has already navigated away from Star Reduction."""
        if self.current_stage_id() != "star_reduction":
            return
        self._sr_layers = (sig, layers[0], layers[1])
        self._sr_ready = True
        if hasattr(self._panel, "sr_slider"):
            self._panel.sr_slider.setEnabled(True)
            self._panel.apply_btn.setEnabled(True)
            self._panel.sr_status.setText(
                "" if rcastro_valid(self.settings) else _FREE_STAR_NOTE)
        self._render_sr_preview()

    def _on_sr_change(self, amount: float) -> None:
        """The Star Reduction slider moved: stash the value and (re)start debounce."""
        self._sr_pending = amount
        if self._sr_ready:
            self._sr_timer.start(90)

    def _render_sr_preview(self) -> None:
        """Non-committing live preview of the current reduction against the cached
        split — the fast wing-curve, so it tracks the slider instantly."""
        if (self.project is None or self.current_stage_id() != "star_reduction"
                or not self._sr_ready or not self._sr_layers):
            return
        amount = (self._sr_pending if self._sr_pending is not None
                  else self._panel.sr_slider.value() / 100.0)
        _, starless, stars = self._sr_layers
        self._show_preview(reduce_stars(starless, stars, amount).data)

    def _apply_star_reduction(self, amount) -> None:
        """Commit the reduction at the current amount using the cached split — no
        StarX rerun, so Apply is instant."""
        if self.project is None or not self._sr_ready or self._busy or not self._sr_layers:
            return
        self.project.jump_back(
            self._leading_kept(self.project.entries(), self._sr_preceding()))
        _, starless, stars = self._sr_layers
        result = reduce_stars(starless, stars, float(amount))
        self.project.run_step(_PrecomputedStep("Star Reduction", result), float(amount))
        self._mark_dirty()
        self.log_panel.append_entry(
            format_log_entry("Star Reduction", f"{float(amount):.2f}", None))
        self._clear_warning()
        self._refresh()

    # --- history ---
    def _reset_image(self) -> None:
        if self.project is None:
            return
        resp = QMessageBox.question(
            self, f"{APP_NAME} — Reset",
            "Discard all edits and start over from the loaded image?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        self.open_image(self._source_base, self._source_label)

    def _stage_for_step_name(self, name):
        """Map a history step name to the stepper stage that produced it, for
        undo/redo navigation. Geometry -> Crop, Enhancements taps -> Enhancements,
        Remove Green (a Color-step button, no own stage) -> Color. Toolbar-tool
        steps (Narrowband, Star Spikes) have no stepper stage -> None (stay put)."""
        if not name:
            return None
        if name in GEOMETRY_NAMES:
            return "crop"
        if name in ENHANCE_NAMES:
            return "enhancements"
        sid = {sname: s for s, sname in STEP_NAME.items()}.get(name)
        if sid == "remove_green":          # applied on the Color step
            return "color"
        return sid

    def _navigate_to_step(self, name) -> None:
        """Jump the stepper to the stage that owns `name`, if it is a reachable
        (enabled) stage; otherwise just refresh in place (toolbar tools, unknown)."""
        sid = self._stage_for_step_name(name)
        target = next((i for i, s in enumerate(self._stages)
                       if s.id == sid and s.enabled), None) if sid else None
        if target is not None:
            self._go_to(target)
        else:
            self._refresh()

    def _undo(self) -> None:
        if not (self.project and self.project.can_undo()):
            return
        entries = self.project.entries()
        affected = entries[-1][0] if entries else None   # step being reverted
        self.project.undo()
        self._mark_dirty()
        self.log_panel.append_entry("Undo")
        self._navigate_to_step(affected)

    def _redo(self) -> None:
        if not (self.project and self.project.can_redo()):
            return
        self.project.redo()
        self._mark_dirty()
        entries = self.project.entries()
        affected = entries[-1][0] if entries else None   # step just re-applied
        self.log_panel.append_entry("Redo")
        self._navigate_to_step(affected)

    def _share(self) -> None:
        if self.project is None or self._busy:
            return
        data = self.project.current().data
        rgb8 = _to_uint(data, 8)
        if rgb8.ndim == 2:
            rgb8 = np.stack([rgb8] * 3, axis=2)
        meta = dict(self.project.current().metadata)
        meta["source_label"] = self._source_label
        ShareDialog(rgb8, meta, self.settings, parent=self).exec()

    def _upscale(self) -> None:
        if self.project is None or self._busy:
            return
        snap = self.project.current()
        meta = dict(snap.metadata)
        meta["source_label"] = self._source_label
        img = AstroImage(snap.data.copy(), is_linear=snap.is_linear, metadata=meta)
        rc = RCAstro(resolve_binary(self.settings.rcastro_path))
        UpscaleDialog(img, meta, self.settings, rc=rc,
                      on_open_copy=self._open_upscaled, parent=self).exec()

    def _open_upscaled(self, result) -> None:
        self.open_image(result, f"{os.path.splitext(self._source_label or 'image')[0]}_2x")

    def eventFilter(self, obj, event) -> bool:
        """Space anywhere (except in a text field or while a modal dialog is up)
        toggles the before/after peek."""
        if (event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Space
                and not event.isAutoRepeat()
                and event.modifiers() == Qt.KeyboardModifier.NoModifier
                and QApplication.activeModalWidget() is None):
            from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QTextEdit
            if not isinstance(QApplication.focusWidget(),
                              (QLineEdit, QPlainTextEdit, QTextEdit)):
                self._toggle_peek()
                return True
        return super().eventFilter(obj, event)

    def _set_peek(self, active: bool) -> None:
        """Single source of truth for peek state + its cue label, so every path that
        exits peek (nav, apply, preview repaint) clears the 'Before' cue too."""
        self._peek_active = active
        self._peek_label.setText("Before — press Space to compare" if active else "")

    def _toggle_peek(self) -> None:
        """Flip the main image between the *current step's* entry state (its before)
        and whatever is on the canvas now (its after — a live preview or the
        committed result), swapping the histogram too. Scoped to the current step,
        so peeking never reveals an earlier step's effect. The only thing Space does."""
        if self.project is None or self._displayed is None:
            return
        self._set_peek(not self._peek_active)
        img = self._peek_before() if self._peek_active else self._displayed
        self.image_view.set_image(to_qimage(img))
        self.histogram_view.set_image(img)

    def _peek_before(self):
        """The image entering the current step — the same pre-step base a commit
        operates on (WYSIWYG), so Space compares only THIS step's effect. For
        non-processing stages (import/crop/export/enhancements) fall back to the
        previous history state."""
        stage_id = self.current_stage_id()
        if stage_id in PROCESSING_ORDER:
            return self._preview_base(stage_id)
        before, _ = self.project.before_after()
        return before

    def _toggle_before_after(self) -> None:
        if self.project is None:
            self._ba_act.setChecked(False)
            return
        if self._ba_act.isChecked():
            before, _ = self.project.before_after()
            self.image_view.set_compare(to_qimage(before))
        else:
            self.image_view.set_compare(None)

    def _toggle_log(self) -> None:
        self._bottom_bar.setVisible(self._log_act.isChecked())

    # --- exports ---
    def export_final(self, fmt: str) -> None:
        if self.project is None or self._busy:
            return
        img = self.project.current()
        self._clear_warning()   # clear any stale error before exporting (parity with apply_current)
        if fmt == "Starless + Stars (two TIFFs)":
            if not rcastro_valid(self.settings):
                self._show_warning("Starless + stars split needs RC-Astro (see Settings).")
                return
            folder = QFileDialog.getExistingDirectory(self, "Export starless + stars to…", start_dir(self.settings.base_dir))
            if not folder:
                return

            def _split():
                rc = RCAstro(resolve_binary(self.settings.rcastro_path))
                starless, stars = rc.remove_stars(img, runner=self._rc_runner)
                save_tiff(starless, os.path.join(folder, "starless.tif"))
                save_tiff(stars, os.path.join(folder, "stars.tif"))

            self._run_busy(_split,
                           lambda _: self.log_panel.append_entry("Exported starless.tif + stars.tif"),
                           "Exporting…", "Export failed")
            return
        # Open the dialog on the format the user picked in the app (respect their
        # choice) and suggest a filename from the opened file's stem.
        filters = "TIFF (*.tiff);;PNG (*.png);;FITS (*.fits)"
        selected = {"PNG": "PNG (*.png)", "FITS": "FITS (*.fits)"}.get(
            fmt, "TIFF (*.tiff)")
        ext = {"PNG": ".png", "FITS": ".fits"}.get(fmt, ".tiff")
        stem = os.path.splitext(self._source_label or "export")[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", os.path.join(start_dir(self.settings.base_dir), stem + ext),
            filters, selected
        )
        if not path:
            return
        sig = self._solve_sig()
        solved = self._solve is not None and self._solve[0] == sig
        if fmt == "PNG":
            if not path.lower().endswith(".png"):
                path += ".png"
            name = os.path.basename(path)
            panel = self._panel
            burn = solved and hasattr(panel, "burn_annotations") and panel.burn_annotations.isChecked()
            if burn:
                save = lambda img, path: self._save_png_with_annotations(img, path, self._solve[1])
            else:
                save = save_png
        elif fmt == "FITS":
            if not path.lower().endswith((".fits", ".fit")):
                path += ".fits"
            name = os.path.basename(path)
            header = dict(self._solve[1].wcs.to_header()) if solved else None
            save = lambda img, path: save_fits(img, path, header=header)
        else:
            if not path.lower().endswith((".tiff", ".tif")):
                path += ".tiff"
            save, name = save_tiff, os.path.basename(path)
        self._run_busy(lambda: save(img, path),
                       lambda _: self.log_panel.append_entry(f"Exported {name}"),
                       "Exporting…", "Export failed")

    def _save_png_with_annotations(self, img, path, res) -> None:
        from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem
        from PySide6.QtGui import QImage, QPixmap, QPainter
        from ..core.annotate import compass_angles, scale_bar
        from .annotation_overlay import build_annotation_group
        h, w = img.data.shape[:2]
        north, _east = compass_angles(res.wcs, (h, w))
        length, label = scale_bar(res.pixscale_arcsec, w)
        _sig, _res, objs = self._solve
        group = build_annotation_group(objs, north, length, label, (h, w), "dark")
        base = to_qimage(img)
        scene = QGraphicsScene()
        scene.addItem(QGraphicsPixmapItem(QPixmap.fromImage(base)))
        scene.addItem(group)
        out = QImage(base.size(), QImage.Format.Format_ARGB32)
        painter = QPainter(out)
        scene.render(painter, target=out.rect(), source=scene.itemsBoundingRect())
        painter.end()
        out.save(path)

    # --- settings ---
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.result_settings()
            save_settings(self.settings, self._settings_path)
            self._update_tools_label()
            self._rebuild_panel()
            self._refresh()

    # --- rendering ---
    def _rebuild_panel(self) -> None:
        stage = self._stages[self._stage]
        loaded = self.project is not None
        if stage.id == "stretch":
            self._stretch_pending = None
        if stage.id == "levels":
            self._levels_show_clipping = False  # each visit starts with clipping off
            self._levels_pending = None
        if stage.id == "saturation":
            self._sat_pending = None
        if stage.id == "local_contrast":
            self._lc_pending = None
        if stage.id == "recover_core":
            self._recover_pending = None
        if stage.id == "curves":
            self._curve_pending = None
        if stage.id == "green_fringe":
            self._fringe_pending = None
        if stage.id == "star_reduction":
            self._sr_pending = None
        if stage.id == "color":
            self._rg_pending = None
        apply_enabled = loaded
        if stage.id == "background":
            apply_enabled = loaded and graxpert_valid(self.settings)
        split_enabled = loaded and rcastro_valid(self.settings)
        both_denoise = graxpert_valid(self.settings) and rcastro_valid(self.settings)
        denoise_choices = ["Default", "RC-Astro", "GraXpert"] if both_denoise else None
        new_panel = build_panel(
            stage,
            on_open=self._choose_fits,
            on_apply=self.apply_current,
            on_crop_apply=self._apply_crop,
            on_crop_change=self._on_crop_change,
            on_guides_change=self._on_guides_change,
            on_rotate=self._rotate,
            on_flip_h=self._flip_h,
            on_flip_v=self._flip_v,
            on_export=self.export_final,
            on_remove_green=self._remove_green,
            on_removegreen_change=self._on_removegreen_change,
            on_enhance=self._enhance,
            on_stretch_change=self._on_stretch_change,
            on_levels_change=self._on_levels_change,
            on_levels_auto=self._on_levels_auto,
            on_levels_clipping=self._on_levels_clipping,
            on_sat_change=self._on_sat_change,
            on_sat_apply=self._apply_saturation,
            on_lc_change=self._on_lc_change,
            on_fringe_change=self._on_fringe_change,
            on_fringe_apply=self._apply_green_fringe,
            on_curve_change=self._on_curve_change,
            on_curve_preset=self._on_curve_preset,
            on_recover_change=self._on_recover_change,
            on_sr_change=self._on_sr_change,
            on_sr_apply=self._apply_star_reduction,
            apply_enabled=apply_enabled,
            split_enabled=split_enabled,
            option_default=(self._step_for(stage.id).default_option()
                            if stage.kind == "process" else None),
            denoise_engine_choices=denoise_choices,
            denoise_default_engine=self.settings.denoise_engine,
        )
        if stage.kind == "import" and loaded and hasattr(new_panel, "meta_label"):
            new_panel.meta_label.setText(
                import_summary(self.project.current().metadata, filename=self._source_label))
        if stage.id == "curves" and loaded:
            new_panel.curve_editor.set_histogram(self._preview_base("curves").data)
        if stage.id == "export" and hasattr(new_panel, "burn_annotations"):
            sig = self._solve_sig() if loaded else None
            solved = loaded and self._solve is not None and self._solve[0] == sig
            new_panel.burn_annotations.setEnabled(solved)
        self._right_layout.replaceWidget(self._panel, new_panel)
        self._panel.deleteLater()
        self._panel = new_panel
        self._setup_crop_overlay()  # enable on crop stage, disable elsewhere
        if stage.id == "star_reduction":
            self._setup_star_reduction()  # kick off the cached StarX split on entry
        if stage.id == "green_fringe":
            self._setup_green_fringe()
        if stage.id == "saturation":
            self._setup_saturation()
        self._update_explainer()

    def _update_info_strip(self) -> None:
        """One-line capture readout under the histogram: resolution · total
        integration · target. Resolution reflects the *current* image (so a
        crop updates it); integration/target come from stable capture
        metadata. Cleared when no project is open."""
        if self.project is None:
            self._info_strip.setText("")
            return
        img = self.project.current()
        meta = img.metadata
        parts: list[str] = []
        h, w = img.data.shape[:2]
        parts.append(f"{w} × {h}")
        integ = resolve_integration(meta)
        if integ is not None and integ.total_s is not None:
            parts.append(format_integration(integ.total_s))
        target = meta.get("target") or meta.get("target_solved")
        if target:
            parts.append(str(target))
        self._info_strip.setText("  ·  ".join(parts))

    def _close_project(self) -> None:
        """Return to the welcome screen, discarding the current workspace (after
        the standard save-if-dirty guard). Gives the user a clean 'start over'
        that matches the first-launch state — nothing lingering from the old
        image."""
        if not self._confirm_save_if_dirty():
            return
        self.project = None
        self._project_path = None
        self._source_label = None
        self._solve = None
        self._dirty = False
        self._center_stack.setCurrentWidget(self._welcome)
        self._show_chrome(False)
        self._update_title()
        self._update_info_strip()
        self._clear_cache()   # the undo history is gone — reclaim the disk

    def _clear_cache(self) -> None:
        """Delete this session's transient undo snapshots (state_*.npy) from the
        shared cache dir. Best-effort — a locked or missing file never blocks the
        app. Saved .nocturne bundles are self-contained, so saved work is untouched."""
        d = self._cache_dir
        try:
            names = os.listdir(d)      # raises if the dir is missing/unreadable — caught: never blocks the app
        except OSError:
            return
        for name in names:
            if name.startswith("state_") and name.endswith(".npy"):
                try:
                    os.remove(os.path.join(d, name))
                except OSError:
                    pass

    def _show_provenance(self) -> None:
        if self.project is None:
            return
        report = build_report(self.project.entries(), self.project.current().metadata,
                              app_version=__version__, date=datetime.date.today())
        ProvenanceDialog(report, self.settings, source_label=self._source_label, parent=self).exec()

    def _refresh(self) -> None:
        self._set_peek(False)   # a rebuilt view always shows the current image
        self.stepper.set_current(self._stage)
        self.stepper.mark_done(self._done_ids())
        if self.project is not None:
            img = self.project.current()
            self.image_view.set_image(to_qimage(img))
            self.histogram_view.set_image(img)
            self._displayed = img
        self._update_info_strip()
        self._back_btn.setEnabled(prev_enabled(self._stages, self._stage) != self._stage)
        self._next_btn.setEnabled(next_enabled(self._stages, self._stage) != self._stage)
        self._undo_act.setEnabled(bool(self.project and self.project.can_undo()))
        self._redo_act.setEnabled(bool(self.project and self.project.can_redo()))
        self._reset_act.setEnabled(self.project is not None)
        self._share_act.setEnabled(self.project is not None)
        self._upscale_act.setEnabled(self.project is not None)
        self._save_project_act.setEnabled(self.project is not None)
        if self.image_view._annotations is not None:
            sig = self._solve_sig() if self.project is not None else None
            if not self._solve or self._solve[0] != sig:
                self.image_view.set_annotations(None)
                self._solve_act.setChecked(False)

    def _done_ids(self) -> set:
        done = set()
        if self.project is None:
            return done
        done.add("load")
        applied = {n for n, _ in self.project.entries()}
        for sid, name in STEP_NAME.items():
            if name in applied:
                done.add(sid)
        if any(g in applied for g in GEOMETRY_NAMES):
            done.add("crop")
        if any(e in applied for e in ENHANCE_NAMES):
            done.add("enhancements")
        return done
