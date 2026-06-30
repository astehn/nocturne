from __future__ import annotations

import os

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget,
)

from ..core.crop import CropParams, detect_content_bounds
from ..core.export import save_fits, save_png, save_tiff
from ..core.fits_io import format_metadata
from ..history.project import Project
from ..history.step import Step
from ..settings import (
    graxpert_valid, load_settings, rcastro_valid, resolve_binary, save_settings,
)
from ..steps.background import BackgroundStep
from ..steps.color import ColorStep
from ..steps.crop import CropStep
from ..steps.load import load_fits
from ..steps.noise_sharpen import NoiseSharpenStep
from ..steps.saturation_step import SaturationStep
from ..steps.stretch_step import StretchStep
from ..tools.base import run_cli
from ..tools.graxpert import GraXpert
from ..tools.rcastro import RCAstro
from .image_view import ImageView
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
        self.setWindowTitle("Seestar Processor")
        self._settings_path = settings_path
        self.settings = load_settings(settings_path)
        self.project: Project | None = None
        self._cache_dir = os.path.join(os.path.dirname(settings_path), "cache")
        self.destination = "in_app"
        self._stages = path_stages(self.destination)
        self._stage = 0
        self._before_after = False
        self._bg_runner = run_cli
        self._rc_runner = run_cli
        self._busy = False
        self._async_enabled = True  # tests set False for deterministic apply
        self._pool = QThreadPool.globalInstance()
        self._busy_overlay = BusyOverlay()

        central = QWidget()
        root = QHBoxLayout(central)

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

        self.setCentralWidget(central)
        self._build_toolbar()
        self._rebuild_panel()
        self._refresh()

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Main")
        tb.addAction("Open FITS", self._choose_fits)
        tb.addAction("Settings", self._open_settings)
        self._undo_act = tb.addAction("Undo", self._undo)
        self._redo_act = tb.addAction("Redo", self._redo)
        self._ba_act = tb.addAction("Before/After", self._toggle_before_after)
        self._ba_act.setCheckable(True)
        tb.addAction("Fit", self.image_view.fit)
        tb.addAction("100%", self.image_view.actual_size)

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
        os.makedirs(self._cache_dir, exist_ok=True)
        self.project = Project(base, self._cache_dir)
        self._status.setText("")
        self._go_to_id("load")  # stay on Import & assess so the user sees metadata
        self._rebuild_panel()
        self._refresh()

    # --- apply a processing stage ---
    def _step_for(self, stage_id: str):
        if stage_id == "crop":
            return CropStep()
        if stage_id == "background":
            step = BackgroundStep(GraXpert(resolve_binary(self.settings.graxpert_path)))
            step._runner = self._bg_runner
            return step
        if stage_id == "color":
            return ColorStep()
        if stage_id == "stretch":
            return StretchStep()
        if stage_id == "saturation":
            return SaturationStep()
        if stage_id == "noise_sharpen":
            rc = (RCAstro(resolve_binary(self.settings.rcastro_path))
                  if rcastro_valid(self.settings) else None)
            step = NoiseSharpenStep(rc)
            step._runner = self._rc_runner
            return step
        raise ValueError(stage_id)

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
        step = self._step_for(stage_id)
        base = self.project.current()
        self._status.setText("")
        self._set_busy(True)

        def work():
            return step.apply(base, option)

        def done(result):
            self.project.run_step(_PrecomputedStep(STEP_NAME[stage_id], result), option)
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
        self.image_view.set_aspect(_ASPECT_RATIO.get(aspect_text))

    def _apply_crop(self) -> None:
        if self.project is None or self._busy:
            return
        top, bottom, left, right = self.image_view.crop_bounds()
        margin = self._panel.margin_slider.value() / 100.0
        if margin > 0:
            h, w = bottom - top, right - left
            dh, dw = int(h * margin), int(w * margin)
            top, bottom, left, right = top + dh, bottom - dh, left + dw, right - dw
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
            self._refresh()

    def _redo(self) -> None:
        if self.project:
            self.project.redo()
            self._refresh()

    def _toggle_before_after(self) -> None:
        self._before_after = self._ba_act.isChecked()
        self._refresh()

    # --- exports ---
    def _guarded(self, fn) -> bool:
        """Run a file-writing action; surface failures instead of crashing."""
        try:
            fn()
        except Exception as exc:
            self._status.setText(f"Export failed: {exc}")
            return False
        self._status.setText("")
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

            self._guarded(_do)
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Export TIFF", "", "TIFF (*.tiff)")
            if not path:
                return
            if not path.lower().endswith((".tiff", ".tif")):
                path += ".tiff"
            self._guarded(lambda: save_tiff(img, path))

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
            self._guarded(lambda: save_png(img, path))
        elif fmt == "FITS":
            if not path.lower().endswith((".fits", ".fit")):
                path += ".fits"
            self._guarded(lambda: save_fits(img, path))
        else:
            if not path.lower().endswith((".tiff", ".tif")):
                path += ".tiff"
            self._guarded(lambda: save_tiff(img, path))

    # --- settings ---
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.result_settings()
            save_settings(self.settings, self._settings_path)
            self._rebuild_panel()
            self._refresh()

    # --- rendering ---
    def _rebuild_panel(self) -> None:
        stage = self._stages[self._stage]
        loaded = self.project is not None
        apply_enabled = loaded
        if stage.id == "background":
            apply_enabled = loaded and graxpert_valid(self.settings)
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
            if self._before_after:
                before, _ = self.project.before_after()
                img = before
            self.image_view.set_image(to_qimage(img))
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
