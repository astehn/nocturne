from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import APP_NAME
from ..core.crop import CropParams, detect_content_bounds
from ..core.enhance import boost_hue, darken_sky, lighten_sky
from ..core.export import save_fits, save_png, save_tiff
from ..core.fits_io import import_summary
from ..history.project import Project
from ..history.step import Step
from ..settings import (
    graxpert_valid, load_settings, rcastro_valid, resolve_binary, save_settings,
)
from ..recipe import recipe_from_entries, save_recipe, uncaptured_step_names
from ..steps.factory import make_step
from ..steps.load import load_fits
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro
from ..core.metrics import rms_delta
from .histogram_view import HistogramView
from . import help_content
from .about_dialog import AboutDialog
from .help_dialog import HelpDialog
from .theme import ACCENT
from .batch_dialog import BatchDialog
from .image_view import ImageView
from .log_panel import LogPanel, format_log_entry
from .pipeline import ENHANCE_NAMES, GEOMETRY_NAMES, POST_STRETCH_IDS, PROCESSING_ORDER, STEP_NAME, next_enabled, path_stages, prev_enabled
from ..core.levels import apply_levels, auto_levels, clipping_masks
from ..core.saturation import saturate
from ..core.local_contrast import enhance
from ..core.star_reduction import reduce_stars
from .preview import rgb_to_qimage, to_qimage
from .settings_dialog import SettingsDialog
from .step_panels import build_panel
from .icons import load_icon
from .stepper import Stepper
from .welcome import WelcomeScreen
from .busy_bar import BusyBar
from .worker import run_async

_ASPECT_RATIO = {"Original": None, "1:1": 1.0, "16:9": 16 / 9, "4:5": 4 / 5, "3:2": 3 / 2}
BUSY_DELAY_MS = 400   # ms before busy visuals appear; sub-threshold ops show nothing

_ENHANCE_FN = {
    "Boost Red": lambda i: boost_hue(i, 0.0),
    "Boost Cyan": lambda i: boost_hue(i, 0.5),
    "Boost Blue": lambda i: boost_hue(i, 0.667),
    "Darken Sky": darken_sky,
    "Lighten Sky": lighten_sky,
}


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


class MainWindow(QMainWindow):
    def __init__(self, settings_path: str) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self._settings_path = settings_path
        self.settings = load_settings(settings_path)
        self.project: Project | None = None
        self._cache_dir = os.path.join(os.path.dirname(settings_path), "cache")
        self._stages = path_stages()
        self._stage = 0
        self._bg_runner = run_cli
        self._rc_runner = run_cli
        self._busy = False
        self._async_enabled = True  # tests set False for deterministic apply
        self._pool = QThreadPool.globalInstance()
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
        # Levels live-preview: a debounced (90 ms) non-committing render.
        self._levels_show_clipping = False
        self._levels_pending = None
        self._levels_timer = QTimer(self)
        self._levels_timer.setSingleShot(True)
        self._levels_timer.timeout.connect(self._render_levels_preview)
        # Saturation live-preview: a debounced (90 ms) non-committing render.
        self._sat_pending = None
        self._sat_timer = QTimer(self)
        self._sat_timer.setSingleShot(True)
        self._sat_timer.timeout.connect(self._render_saturation_preview)
        # Local-contrast live-preview: a debounced (90 ms) non-committing render.
        self._lc_pending = None
        self._lc_timer = QTimer(self)
        self._lc_timer.setSingleShot(True)
        self._lc_timer.timeout.connect(self._render_lc_preview)
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
        self._right_layout.addWidget(self._explainer_scroll)
        self._full_help_link = QLabel('<a href="#">Full help →</a>')
        self._full_help_link.setObjectName("fullHelpLink")
        self._full_help_link.setOpenExternalLinks(False)
        self._full_help_link.linkActivated.connect(
            lambda _: self._open_help(self._current_topic_id))
        self._right_layout.addWidget(self._full_help_link)
        nav = QHBoxLayout()
        self._back_btn = QPushButton("← Back")
        self._next_btn = QPushButton("Next →")
        self._next_btn.setObjectName("primary")
        self._back_btn.clicked.connect(self.go_back)
        self._next_btn.clicked.connect(self.go_next)
        nav.addWidget(self._back_btn)
        nav.addWidget(self._next_btn)
        self._right_layout.addLayout(nav)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #ff6b6b;")
        self._right_layout.addWidget(self._status)
        self._busy_label = QLabel("")
        self._busy_label.setStyleSheet("color: #9aa0a6;")   # neutral grey, not error-red
        self._right_layout.addWidget(self._busy_label)
        root.addWidget(right)

        self.log_panel = LogPanel()
        outer.addWidget(self.log_panel)

        self.setCentralWidget(central)
        self._build_toolbar()
        self._build_menu()
        self._show_chrome(False)  # full-bleed welcome until an image is loaded

    def _show_chrome(self, visible: bool) -> None:
        """Show/hide the stepper + right panel so the welcome screen is a clean
        full-bleed empty state (no redundant Import panel/stepper before load)."""
        self.stepper.setVisible(visible)
        self._right_panel.setVisible(visible)
        self._rebuild_panel()
        self._refresh()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Warn before discarding an edited (un-exported) project on quit."""
        if self.project is not None and self.project.entries():
            resp = QMessageBox.question(
                self, "Quit Nocturne",
                "You have unsaved edits — quit anyway? Your work will be lost.",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Discard,
                QMessageBox.StandardButton.Cancel,
            )
            if resp != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
        event.accept()

    def _build_menu(self) -> None:
        help_menu = self.menuBar().addMenu("Help")
        self._help_act = help_menu.addAction("Help…", self._show_help)
        self._about_act = help_menu.addAction(f"About {APP_NAME}…", self._show_about)

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
        if t is None:
            self._explainer_scroll.setVisible(False)
            self._full_help_link.setVisible(False)
            return
        self._explainer.setText(f"<b>{t.summary}</b>{t.body}")
        self._explainer_scroll.setVisible(True)
        self._full_help_link.setVisible(True)

    def _make_about_dialog(self) -> AboutDialog:
        return AboutDialog(self)

    def _show_about(self) -> None:
        self._make_about_dialog().exec()

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
        path, _ = QFileDialog.getSaveFileName(self, "Save Recipe", "", "Recipe (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        save_recipe(recipe_from_entries(self.project.entries()), path)
        self._status.setText(f"Saved recipe: {os.path.basename(path)}")

    def _open_batch(self) -> None:
        BatchDialog(self.settings, self).exec()

    def _open_stack(self) -> None:
        try:
            from .stack_dialog import StackDialog
        except ImportError:
            self._status.setText("Stacking unavailable — install astroalign and sep.")
            return
        StackDialog(self.settings, self,
                    on_master=lambda img: self.open_image(img, "stacked master")).exec()

    def _open_haoiii(self) -> None:
        try:
            from .haoiii_dialog import HaOIIIDialog
        except ImportError:
            self._status.setText("Ha/OIII extract unavailable — install astroalign and sep.")
            return
        HaOIIIDialog(self.settings, self,
                     on_master=lambda img: self.open_image(img, "Ha/OIII master")).exec()

    def _remove_stars(self, img):
        rc = RCAstro(resolve_binary(self.settings.rcastro_path))
        return rc.remove_stars(img, runner=self._rc_runner)

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Main")
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        # File
        tb.addAction(load_icon("open"), "Open FITS", self._choose_fits)
        tb.addAction(load_icon("settings"), "Settings", self._open_settings)
        tb.addSeparator()
        # Tools (primary features tinted with the accent)
        self._save_recipe_act = tb.addAction(load_icon("save-recipe"), "Save Recipe", self._save_recipe)
        tb.addAction(load_icon("batch"), "Batch…", self._open_batch)
        tb.addAction(load_icon("stack", ACCENT), "Stack…", self._open_stack)
        tb.addAction(load_icon("haoiii", ACCENT), "Ha/OIII…", self._open_haoiii)
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
        self._status.setText("")  # clear any stale error when changing steps
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
        path = QFileDialog.getOpenFileName(self, "Open FITS", "", "FITS (*.fit *.fits)")[0]
        if path:
            self.open_fits(path)

    def open_fits(self, path: str) -> None:
        try:
            base = load_fits(path)
        except Exception as exc:
            self._status.setText(f"Could not open file: {exc}")
            return
        self.open_image(base, os.path.basename(path))

    def open_image(self, base, label: str) -> None:
        self._source_base = base
        self._source_label = label
        os.makedirs(self._cache_dir, exist_ok=True)
        self.project = Project(base, self._cache_dir)
        self._center_stack.setCurrentWidget(self.image_view)
        self._show_chrome(True)  # reveal stepper + panel now there's an image
        self._status.setText("")
        h, w = base.data.shape[:2]
        self.log_panel.append_entry(
            format_log_entry(f"Opened {label}", "", None, dims=(w, h))
        )
        self._go_to_id("load")  # stay on Import & assess so the user sees metadata
        self._rebuild_panel()
        self._refresh()

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
            self._status.setText(
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
            self._status.setText("")
            self.log_panel.append_entry(format_log_entry("Background", "off", None) + " — skipped")
            self._refresh()
            return
        step = self._step_for(stage_id)
        base = self.project.current()
        self._status.setText("")

        def on_result(result):
            self.project.run_step(_PrecomputedStep(STEP_NAME[stage_id], result), option)
            self._log_step(stage_id, option, base, result)
            self._refresh()  # stay on this step; user clicks Next to advance

        self._run_busy(lambda: step.apply(base, option), on_result,
                       f"Applying {STEP_NAME[stage_id]}…", "Failed")

    def _log_step(self, stage_id: str, option, base, result) -> None:
        name = STEP_NAME[stage_id]
        if stage_id in ("color", "levels"):
            label = ""  # option is a settings object/tuple, not user-facing text
        elif isinstance(option, float):
            label = f"{option:.2f}"
        else:
            label = option
        self.log_panel.append_entry(format_log_entry(name, label, rms_delta(base, result)))

    def _run_busy(self, work, on_result, label: str, err_prefix: str) -> None:
        """Run `work` off the UI thread with busy indication; `on_result(result)`
        on success, `f"{err_prefix}: {exc}"` in the status label on failure.
        Busy is always cleared in a finally (even if `on_result` raises)."""
        self._set_busy(True, label)

        def done(result):
            try:
                on_result(result)
            finally:
                self._set_busy(False)

        def err(exc):
            try:
                self._status.setText(f"{err_prefix}: {exc}")
            finally:
                self._set_busy(False)

        if self._async_enabled:
            run_async(self._pool, work, done, err)
        else:
            try:
                result = work()
            except Exception as exc:  # mirror the async error path
                err(exc)
            else:
                done(result)          # an on_result throw propagates after the finally

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

    def _hide_busy_visuals(self) -> None:
        self._ellipsis_timer.stop()
        if self._busy_shown:
            self._busy_bar.hide_bar()
            self._busy_label.setText("")
        if self._cursor_active:
            QApplication.restoreOverrideCursor()
            self._cursor_active = False
        self._busy_shown = False

    def _tick_ellipsis(self) -> None:
        self._ellipsis_n = (self._ellipsis_n + 1) % 4
        self._busy_label.setText(self._busy_label_text + "." * self._ellipsis_n)

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
        result = _ENHANCE_FN[op](self.project.current())
        self.project.run_step(_PrecomputedStep(op, result), "")
        self.log_panel.append_entry(format_log_entry(op, "", None))
        self._status.setText("")
        self._refresh()

    def _apply_geometry(self, name: str, params) -> None:
        if self.project is None or self._busy:
            return
        self.project.jump_back(self._leading_kept(self.project.entries(), set(GEOMETRY_NAMES)))
        result = self._step_for("crop").apply(self.project.current(), params)
        self.project.run_step(_PrecomputedStep(name, result), "")
        self.log_panel.append_entry(format_log_entry(name, "", None))
        self._status.setText("")
        self._refresh()
        self._setup_crop_overlay()

    def _rotate(self) -> None:
        self._apply_geometry("Rotate", CropParams(rotate=90))

    def _flip_h(self) -> None:
        self._apply_geometry("Flip H", CropParams(flip_h=True))

    def _flip_v(self) -> None:
        self._apply_geometry("Flip V", CropParams(flip_v=True))

    def _remove_green(self) -> None:
        if self.project is None or self._busy:
            return
        idx = PROCESSING_ORDER.index("remove_green")
        preceding = set(GEOMETRY_NAMES) | {
            STEP_NAME[sid] for sid in PROCESSING_ORDER[:idx]
        }
        self.project.jump_back(self._leading_kept(self.project.entries(), preceding))
        base = self.project.current()
        result = self._step_for("remove_green").apply(base, None)
        self.project.run_step(_PrecomputedStep("Remove Green", result), "")
        self.log_panel.append_entry(format_log_entry("Remove Green", "", rms_delta(base, result)))
        self._status.setText("")
        self._refresh()

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
        # Base = the pre-Levels state the commit (apply_current) also uses, so the
        # preview equals what Apply produces even after a prior Levels apply (WYSIWYG).
        preceding = set(GEOMETRY_NAMES) | {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index("levels")]
        }
        img = self.project.state_at(self._leading_kept(self.project.entries(), preceding))
        out = np.clip(apply_levels(img, b, g, w).data, 0, 1)
        rgb = (out * 255 + 0.5).astype(np.uint8)
        if rgb.ndim == 2:
            rgb = np.repeat(rgb[:, :, None], 3, axis=2)
        rgb = np.ascontiguousarray(rgb)
        if self._levels_show_clipping:
            sh, hi = clipping_masks(img.data, b, w)
            rgb[sh] = (40, 120, 255)
            rgb[hi] = (255, 60, 40)
        self.image_view.set_image(rgb_to_qimage(rgb))

    # --- saturation live preview ---
    def _on_sat_change(self, amount: float) -> None:
        """The Saturation slider moved: stash the value and (re)start the debounce."""
        self._sat_pending = amount
        self._sat_timer.start(90)

    def _render_saturation_preview(self) -> None:
        """Non-committing live preview of the current Saturation setting."""
        if self.project is None or self.current_stage_id() != "saturation":
            return
        # Base = the pre-Saturation state the commit (apply_current) also uses, so
        # the preview equals what Apply produces (WYSIWYG).
        preceding = set(GEOMETRY_NAMES) | {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index("saturation")]
        }
        img = self.project.state_at(self._leading_kept(self.project.entries(), preceding))
        amount = (self._sat_pending if self._sat_pending is not None
                  else self._panel.sat_slider.value() / 100.0)
        out = np.clip(saturate(img, amount).data, 0, 1)
        rgb = (out * 255 + 0.5).astype(np.uint8)
        if rgb.ndim == 2:
            rgb = np.repeat(rgb[:, :, None], 3, axis=2)
        rgb = np.ascontiguousarray(rgb)
        self.image_view.set_image(rgb_to_qimage(rgb))

    # --- local contrast live preview ---
    def _on_lc_change(self, amount: float) -> None:
        """The Local Contrast slider moved: stash the value and (re)start debounce."""
        self._lc_pending = amount
        self._lc_timer.start(90)

    def _render_lc_preview(self) -> None:
        """Non-committing live preview of the current Local Contrast setting."""
        if self.project is None or self.current_stage_id() != "local_contrast":
            return
        # Base = the pre-Local-Contrast state the commit (apply_current) also uses,
        # so the preview equals what Apply produces (WYSIWYG).
        preceding = set(GEOMETRY_NAMES) | {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index("local_contrast")]
        }
        img = self.project.state_at(self._leading_kept(self.project.entries(), preceding))
        amount = (self._lc_pending if self._lc_pending is not None
                  else self._panel.lc_slider.value() / 100.0)
        out = np.clip(enhance(img, amount).data, 0, 1)
        rgb = (out * 255 + 0.5).astype(np.uint8)
        if rgb.ndim == 2:
            rgb = np.repeat(rgb[:, :, None], 3, axis=2)
        rgb = np.ascontiguousarray(rgb)
        self.image_view.set_image(rgb_to_qimage(rgb))

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

    def _setup_star_reduction(self) -> None:
        """On entering Star Reduction: run the (slow) StarX split once, off-thread,
        and cache it. The slider then previews the fast wing-curve instantly. A
        cached split for the same base is reused; without RC-Astro the step is
        gated with a note and the slider/Apply stay disabled."""
        self._sr_pending = None
        if self.project is None:
            return
        panel = self._panel
        if not rcastro_valid(self.settings):
            self._sr_ready = False
            if hasattr(panel, "sr_status"):
                panel.sr_status.setText("Needs RC-Astro — set its path in Settings.")
                panel.sr_slider.setEnabled(False)
                panel.apply_btn.setEnabled(False)
            return
        base = self._sr_base()
        sig = self._sr_sig(base)
        if self._sr_layers and self._sr_layers[0] == sig:
            # Already split for this exact base — reuse it, no StarX rerun.
            self._sr_ready = True
            if hasattr(panel, "sr_slider"):
                panel.sr_slider.setEnabled(True)
                panel.apply_btn.setEnabled(True)
                panel.sr_status.setText("")
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
        """The StarX split finished: cache it and enable the slider — unless the
        user has already navigated away from Star Reduction."""
        if self.current_stage_id() != "star_reduction":
            return
        self._sr_layers = (sig, layers[0], layers[1])
        self._sr_ready = True
        if hasattr(self._panel, "sr_slider"):
            self._panel.sr_slider.setEnabled(True)
            self._panel.apply_btn.setEnabled(True)
            self._panel.sr_status.setText("")
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
        out = np.clip(reduce_stars(starless, stars, amount).data, 0, 1)
        rgb = (out * 255 + 0.5).astype(np.uint8)
        if rgb.ndim == 2:
            rgb = np.repeat(rgb[:, :, None], 3, axis=2)
        rgb = np.ascontiguousarray(rgb)
        self.image_view.set_image(rgb_to_qimage(rgb))

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
        self.log_panel.append_entry(
            format_log_entry("Star Reduction", f"{float(amount):.2f}", None))
        self._status.setText("")
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

    def _undo(self) -> None:
        if self.project:
            self.project.undo()
            self.log_panel.append_entry("Undo")
            self._refresh()

    def _redo(self) -> None:
        if self.project:
            self.project.redo()
            self.log_panel.append_entry("Redo")
            self._refresh()

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
        self.log_panel.setVisible(self._log_act.isChecked())

    # --- exports ---
    def export_final(self, fmt: str) -> None:
        if self.project is None or self._busy:
            return
        img = self.project.current()
        self._status.setText("")   # clear any stale error before exporting (parity with apply_current)
        if fmt == "Starless + Stars (two TIFFs)":
            if not rcastro_valid(self.settings):
                self._status.setText("Starless + stars split needs RC-Astro (see Settings).")
                return
            folder = QFileDialog.getExistingDirectory(self, "Export starless + stars to…")
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
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", "", "TIFF (*.tiff);;PNG (*.png);;FITS (*.fits)"
        )
        if not path:
            return
        if fmt == "PNG":
            if not path.lower().endswith(".png"):
                path += ".png"
            save, name = save_png, os.path.basename(path)
        elif fmt == "FITS":
            if not path.lower().endswith((".fits", ".fit")):
                path += ".fits"
            save, name = save_fits, os.path.basename(path)
        else:
            if not path.lower().endswith((".tiff", ".tif")):
                path += ".tiff"
            save, name = save_tiff, os.path.basename(path)
        self._run_busy(lambda: save(img, path),
                       lambda _: self.log_panel.append_entry(f"Exported {name}"),
                       "Exporting…", "Export failed")

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
        if stage.id == "levels":
            self._levels_show_clipping = False  # each visit starts with clipping off
            self._levels_pending = None
        if stage.id == "saturation":
            self._sat_pending = None
        if stage.id == "local_contrast":
            self._lc_pending = None
        if stage.id == "star_reduction":
            self._sr_pending = None
        apply_enabled = loaded
        if stage.id == "background":
            apply_enabled = loaded and graxpert_valid(self.settings)
        split_enabled = loaded and rcastro_valid(self.settings)
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
            on_enhance=self._enhance,
            on_levels_change=self._on_levels_change,
            on_levels_auto=self._on_levels_auto,
            on_levels_clipping=self._on_levels_clipping,
            on_sat_change=self._on_sat_change,
            on_lc_change=self._on_lc_change,
            on_sr_change=self._on_sr_change,
            on_sr_apply=self._apply_star_reduction,
            apply_enabled=apply_enabled,
            split_enabled=split_enabled,
            option_default=(self._step_for(stage.id).default_option()
                            if stage.kind == "process" else None),
        )
        if stage.kind == "import" and loaded and hasattr(new_panel, "meta_label"):
            new_panel.meta_label.setText(
                import_summary(self.project.current().metadata, filename=self._source_label))
        self._right_layout.replaceWidget(self._panel, new_panel)
        self._panel.deleteLater()
        self._panel = new_panel
        self._setup_crop_overlay()  # enable on crop stage, disable elsewhere
        if stage.id == "star_reduction":
            self._setup_star_reduction()  # kick off the cached StarX split on entry
        self._update_explainer()

    def _refresh(self) -> None:
        self.stepper.set_current(self._stage)
        self.stepper.mark_done(self._done_ids())
        if self.project is not None:
            img = self.project.current()
            self.image_view.set_image(to_qimage(img))
            self.histogram_view.set_image(img)
        self._back_btn.setEnabled(prev_enabled(self._stages, self._stage) != self._stage)
        self._next_btn.setEnabled(next_enabled(self._stages, self._stage) != self._stage)
        self._undo_act.setEnabled(bool(self.project and self.project.can_undo()))
        self._redo_act.setEnabled(bool(self.project and self.project.can_redo()))
        self._reset_act.setEnabled(self.project is not None)

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
