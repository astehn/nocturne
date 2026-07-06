from __future__ import annotations

import os

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import APP_NAME
from ..core.crop import CropParams, detect_content_bounds
from ..core.enhance import boost_hue, darken_sky, lighten_sky
from ..core.export import save_fits, save_png, save_tiff
from ..core.fits_io import format_metadata
from ..core.autostretch import autostretch
from ..core.image import AstroImage
from ..core.palette import PaletteParams, compose, render_nebula
from ..history.project import Project
from ..history.step import Step
from ..settings import (
    graxpert_valid, load_settings, rcastro_valid, resolve_binary, save_settings,
)
from ..recipe import recipe_from_entries, save_recipe
from ..steps.factory import make_step
from ..steps.load import load_fits
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro
from ..core.metrics import rms_delta
from .histogram_view import HistogramView
from .about import help_html
from .about_dialog import AboutDialog
from .theme import ACCENT
from .batch_dialog import BatchDialog
from .image_view import ImageView
from .log_panel import LogPanel, format_log_entry
from .pipeline import ENHANCE_NAMES, GEOMETRY_NAMES, PROCESSING_ORDER, STEP_NAME, next_enabled, path_stages, prev_enabled
from .preview import to_qimage
from .settings_dialog import SettingsDialog
from .step_panels import build_panel
from .icons import load_icon
from .stepper import Stepper
from .welcome import WelcomeScreen
from .worker import BusyOverlay, run_async

_ASPECT_RATIO = {"Original": None, "1:1": 1.0, "16:9": 16 / 9, "4:5": 4 / 5, "3:2": 3 / 2}

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
        self._colourise_layers = None
        self._pool = QThreadPool.globalInstance()
        self._busy_overlay = BusyOverlay()

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

    def _build_menu(self) -> None:
        help_menu = self.menuBar().addMenu("Help")
        self._help_act = help_menu.addAction("Help…", self._show_help)
        self._about_act = help_menu.addAction(f"About {APP_NAME}…", self._show_about)

    def _show_help(self) -> None:
        QMessageBox.information(self, f"{APP_NAME} — Help", help_html())

    def _make_about_dialog(self) -> AboutDialog:
        return AboutDialog(self)

    def _show_about(self) -> None:
        self._make_about_dialog().exec()

    # --- recipes / batch ---
    def _save_recipe(self) -> None:
        if self.project is None:
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

    @staticmethod
    def _base_sig(base):
        return (base.data.shape, float(base.data.mean()), float(base.data.std()))

    def _colourise_starx(self, base):
        sig = self._base_sig(base)
        if self._colourise_layers is not None and self._colourise_layers[0] == sig:
            return self._colourise_layers[1], self._colourise_layers[2]
        if rcastro_valid(self.settings):
            starless, _ = self._remove_stars(base)                        # linear -> colour starless
            stretched = AstroImage(autostretch(base), is_linear=False)    # display stretch
            _, stars = self._remove_stars(stretched)                      # bright, complete stars
        else:
            starless, stars = base, None
        self._colourise_layers = (sig, starless, stars)
        return starless, stars

    def _colourise(self) -> None:
        if self.project is None or self._busy:
            return
        idx = self._leading_kept(self.project.entries(), self._stretch_preceding())
        base = self.project.state_at(idx)          # non-destructive
        if not base.is_color:
            self._status.setText("Colourise needs a colour image.")
            return
        self._status.setText("")

        def work():
            starless, stars = self._colourise_starx(base)
            if stars is None:
                return render_nebula(starless, PaletteParams())
            return compose(starless, stars, PaletteParams())

        def on_result(result):
            self.project.jump_back(idx)             # truncate only on success
            self.project.run_step(_PrecomputedStep("Colourise", result), "")
            self.log_panel.append_entry(
                format_log_entry("Colourise", "", rms_delta(base, result)))
            self._refresh()

        self._run_busy(work, on_result, "Colourising…", "Colourise failed")

    def _open_advanced_palette(self) -> None:
        if self.project is None or self._busy:
            return
        idx = self._leading_kept(self.project.entries(), self._stretch_preceding())
        base = self.project.state_at(idx)          # non-destructive
        if not base.is_color:
            self._status.setText("Palette needs a colour image.")
            return
        sig = self._base_sig(base)
        if self._colourise_layers is not None and self._colourise_layers[0] == sig:
            starless, stars = self._colourise_layers[1], self._colourise_layers[2]
        else:
            starless, stars = None, None           # cold: dialog runs StarX async itself
        from .palette_dialog import PaletteDialog
        PaletteDialog(self.settings, base, self, on_apply=self._record_colourise,
                      starless=starless, stars=stars).exec()

    def _record_colourise(self, result) -> None:
        self.project.jump_back(
            self._leading_kept(self.project.entries(), self._stretch_preceding()))
        self.project.run_step(_PrecomputedStep("Colourise", result), "")
        self._status.setText("")
        self.log_panel.append_entry(format_log_entry("Colourise", "", None))
        self._refresh()

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

    def _go_to(self, index: int) -> None:
        if not (0 <= index < len(self._stages)) or not self._stages[index].enabled:
            return
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
        self._colourise_layers = None  # invalidate cached star layers for the new image
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
        predecessors a Colourise or Apply-Stretch preserves."""
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
        # Truncate history to this stage's applied predecessors (synchronous).
        preceding = set(GEOMETRY_NAMES) | {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index(stage_id)]
        }
        if STEP_NAME["stretch"] in preceding:
            preceding.add("Colourise")   # Colourise occupies the stretch position
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
            self._busy_overlay.show_over(self.image_view)
        else:
            self._busy_overlay.hide()
        self._back_btn.setDisabled(busy)
        self._next_btn.setDisabled(busy)
        if hasattr(self._panel, "apply_btn"):
            self._panel.apply_btn.setDisabled(busy)

    # --- crop overlay ---
    def _setup_crop_overlay(self) -> None:
        if self.project is not None and self.current_stage_id() == "crop":
            bounds = detect_content_bounds(self.project.current())
            aspect_text = "Original"
            if hasattr(self._panel, "aspect_box"):
                aspect_text = self._panel.aspect_box.currentText()
            self.image_view.set_crop_overlay(
                True, bounds=bounds, aspect_ratio=_ASPECT_RATIO.get(aspect_text)
            )
        else:
            self.image_view.set_crop_overlay(False)

    def _on_crop_change(self, aspect_text: str) -> None:
        # Snap the visible box to the chosen ratio (and lock future resizes).
        self.image_view.apply_aspect(_ASPECT_RATIO.get(aspect_text))

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
    def _guarded(self, fn, log_label: str | None = None) -> bool:
        """Run a file-writing action; surface failures instead of crashing."""
        try:
            fn()
        except Exception as exc:
            self._status.setText(f"Export failed: {exc}")
            return False
        self._status.setText("")
        if log_label:
            self.log_panel.append_entry(log_label)
        return True

    def export_final(self, fmt: str) -> None:
        if self.project is None:
            return
        img = self.project.current()
        if fmt == "Starless + Stars (two TIFFs)":
            if not rcastro_valid(self.settings):
                self._status.setText("Starless + stars split needs RC-Astro (see Settings).")
                return
            folder = QFileDialog.getExistingDirectory(self, "Export starless + stars to…")
            if not folder:
                return

            def _do():
                rc = RCAstro(resolve_binary(self.settings.rcastro_path))
                starless, stars = rc.remove_stars(img, runner=self._rc_runner)
                save_tiff(starless, os.path.join(folder, "starless.tif"))
                save_tiff(stars, os.path.join(folder, "stars.tif"))

            self._guarded(_do, "Exported starless.tif + stars.tif")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", "", "TIFF (*.tiff);;PNG (*.png);;FITS (*.fits)"
        )
        if not path:
            return
        if fmt == "PNG":
            if not path.lower().endswith(".png"):
                path += ".png"
            self._guarded(lambda: save_png(img, path), f"Exported {os.path.basename(path)}")
        elif fmt == "FITS":
            if not path.lower().endswith((".fits", ".fit")):
                path += ".fits"
            self._guarded(lambda: save_fits(img, path), f"Exported {os.path.basename(path)}")
        else:
            if not path.lower().endswith((".tiff", ".tif")):
                path += ".tiff"
            self._guarded(lambda: save_tiff(img, path), f"Exported {os.path.basename(path)}")

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
        apply_enabled = loaded
        if stage.id == "background":
            apply_enabled = loaded and graxpert_valid(self.settings)
        if stage.id == "star_reduction":
            apply_enabled = loaded and rcastro_valid(self.settings)  # needs StarX
        split_enabled = loaded and rcastro_valid(self.settings)
        new_panel = build_panel(
            stage,
            on_open=self._choose_fits,
            on_apply=self.apply_current,
            on_crop_apply=self._apply_crop,
            on_crop_change=self._on_crop_change,
            on_rotate=self._rotate,
            on_flip_h=self._flip_h,
            on_flip_v=self._flip_v,
            on_export=self.export_final,
            on_remove_green=self._remove_green,
            on_colourise=self._colourise,
            on_palette_advanced=self._open_advanced_palette,
            on_enhance=self._enhance,
            apply_enabled=apply_enabled,
            split_enabled=split_enabled,
        )
        if stage.kind == "import" and loaded and hasattr(new_panel, "meta_label"):
            new_panel.meta_label.setText(format_metadata(self.project.current().metadata))
        self._right_layout.replaceWidget(self._panel, new_panel)
        self._panel.deleteLater()
        self._panel = new_panel
        self._setup_crop_overlay()  # enable on crop stage, disable elsewhere

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
        if "Colourise" in applied:
            done.add("stretch")
        if any(e in applied for e in ENHANCE_NAMES):
            done.add("enhancements")
        return done
