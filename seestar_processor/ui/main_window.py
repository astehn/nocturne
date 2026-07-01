from __future__ import annotations

import os

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from .. import APP_NAME
from ..core.crop import CropParams, detect_content_bounds
from ..core.export import save_fits, save_png, save_tiff
from ..core.fits_io import format_metadata
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
from .about import about_html, help_html
from .batch_dialog import BatchDialog
from .image_view import ImageView
from .log_panel import LogPanel, format_log_entry
from .pipeline import PROCESSING_ORDER, STEP_NAME, next_enabled, path_stages, prev_enabled
from .preview import to_qimage
from .settings_dialog import SettingsDialog
from .step_panels import build_panel
from .stepper import Stepper
from .worker import BusyOverlay, run_async

_ASPECT_RATIO = {"Original": None, "1:1": 1.0, "16:9": 16 / 9, "4:5": 4 / 5, "3:2": 3 / 2}


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
        self.destination = "in_app"
        self._stages = path_stages(self.destination)
        self._stage = 0
        self._bg_runner = run_cli
        self._rc_runner = run_cli
        self._busy = False
        self._async_enabled = True  # tests set False for deterministic apply
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
        root.addWidget(self.image_view, 1)

        right = QWidget()
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
        self._rebuild_panel()
        self._refresh()

    def _build_menu(self) -> None:
        help_menu = self.menuBar().addMenu("Help")
        self._help_act = help_menu.addAction("Help…", self._show_help)
        self._about_act = help_menu.addAction(f"About {APP_NAME}…", self._show_about)

    def _show_help(self) -> None:
        QMessageBox.information(self, f"{APP_NAME} — Help", help_html())

    def _show_about(self) -> None:
        QMessageBox.about(self, f"About {APP_NAME}", about_html())

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

    def _open_palette(self) -> None:
        from .palette_dialog import PaletteDialog
        PaletteDialog(self.settings, self,
                      on_master=lambda img: self.open_image(img, "palette")).exec()

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Main")
        tb.addAction("Open FITS", self._choose_fits)
        tb.addAction("Settings", self._open_settings)
        self._save_recipe_act = tb.addAction("Save Recipe", self._save_recipe)
        tb.addAction("Batch…", self._open_batch)
        tb.addAction("Stack…", self._open_stack)
        tb.addAction("Palette…", self._open_palette)
        self._undo_act = tb.addAction("Undo", self._undo)
        self._redo_act = tb.addAction("Redo", self._redo)
        self._ba_act = tb.addAction("Before/After", self._toggle_before_after)
        self._ba_act.setCheckable(True)
        self._log_act = tb.addAction("Log", self._toggle_log)
        self._log_act.setCheckable(True)
        self._log_act.setChecked(True)
        tb.addAction("Fit", self.image_view.fit)
        tb.addAction("100%", self.image_view.actual_size)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        self._tools_label = QLabel("")
        tb.addWidget(self._tools_label)
        self._update_tools_label()

    def _update_tools_label(self) -> None:
        def chip(name: str, ok: bool) -> str:
            color = "#3fb950" if ok else "#f85149"  # green / red
            mark = "✓" if ok else "✗"
            return f'<span style="color:{color}">{name} {mark}</span>'

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

    # --- destination branch ---
    def set_destination(self, dest: str) -> None:
        if dest == self.destination:
            return
        self.destination = dest
        self._stages = path_stages(dest)
        self._stage = min(self._stage, len(self._stages) - 1)
        self.stepper.set_stages(self._stages)
        self._rebuild_panel()
        self._refresh()

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
        os.makedirs(self._cache_dir, exist_ok=True)
        self.project = Project(base, self._cache_dir)
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

    def apply_current(self, option) -> None:
        if self.project is None or self._busy:
            return
        stage_id = self._stages[self._stage].id
        if stage_id not in PROCESSING_ORDER:
            return
        # Truncate history to this stage's applied predecessors (synchronous).
        preceding = {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index(stage_id)]
        }
        target = sum(1 for name, _ in self.project.entries() if name in preceding)
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
        self._set_busy(True)

        def work():
            return step.apply(base, option)

        def done(result):
            self.project.run_step(_PrecomputedStep(STEP_NAME[stage_id], result), option)
            self._log_step(stage_id, option, base, result)
            self._set_busy(False)
            self._refresh()  # stay on this step; user clicks Next to advance
            if stage_id == "crop":
                self._setup_crop_overlay()

        def err(exc):
            self._set_busy(False)
            self._status.setText(f"Failed: {exc}")

        if self._async_enabled:
            run_async(self._pool, work, done, err)
        else:
            try:
                done(work())
            except Exception as exc:  # mirror the async error path
                err(exc)

    def _log_step(self, stage_id: str, option, base, result) -> None:
        name = STEP_NAME[stage_id]
        if stage_id == "crop":
            h, w = result.data.shape[:2]
            self.log_panel.append_entry(format_log_entry(name, "", None, dims=(w, h)))
            return
        if stage_id in ("color", "levels"):
            label = ""  # option is a settings object/tuple, not user-facing text
        elif isinstance(option, float):
            label = f"{option:.2f}"
        else:
            label = option
        self.log_panel.append_entry(format_log_entry(name, label, rms_delta(base, result)))

    def _set_busy(self, busy: bool) -> None:
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

    def _apply_crop(self) -> None:
        if self.project is None or self._busy:
            return
        top, bottom, left, right = self.image_view.crop_bounds()
        params = CropParams(
            bounds=(top, bottom, left, right),
            rotate=getattr(self._panel, "rotate", 0),
            flip_h=self._panel.flip_h_btn.isChecked(),
            flip_v=self._panel.flip_v_btn.isChecked(),
        )
        self.apply_current(params)

    # --- history ---
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

    def export_external(self, choice: str) -> None:
        if self.project is None:
            return
        img = self.project.current()
        if choice.startswith("Two"):
            if not rcastro_valid(self.settings):
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
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Export TIFF", "", "TIFF (*.tiff)")
            if not path:
                return
            if not path.lower().endswith((".tiff", ".tif")):
                path += ".tiff"
            self._guarded(lambda: save_tiff(img, path), f"Exported {os.path.basename(path)}")

    def export_final(self, fmt: str) -> None:
        if self.project is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", "", "TIFF (*.tiff);;PNG (*.png);;FITS (*.fits)"
        )
        if not path:
            return
        img = self.project.current()
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
        if stage.id == "export_external":
            apply_enabled = loaded and rcastro_valid(self.settings)  # split option
        new_panel = build_panel(
            stage,
            on_open=self._choose_fits,
            on_destination=self.set_destination,
            on_apply=self.apply_current,
            on_crop_apply=self._apply_crop,
            on_crop_change=self._on_crop_change,
            on_export_external=self.export_external,
            on_export=self.export_final,
            apply_enabled=apply_enabled,
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

    def _done_ids(self) -> set:
        done = set()
        if self.project is None:
            return done
        done.add("load")
        applied = {n for n, _ in self.project.entries()}
        for sid, name in STEP_NAME.items():
            if name in applied:
                done.add(sid)
        return done
