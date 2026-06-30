from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QMainWindow, QPushButton, QVBoxLayout, QWidget,
)

from ..core.export import save_jpeg, save_tiff
from ..history.project import Project
from ..history.step import Step
from ..settings import graxpert_valid, load_settings, rcastro_valid, save_settings
from ..steps.background import BackgroundStep
from ..steps.color import ColorStep
from ..steps.crop import CropStep
from ..steps.deconvolution import DeconvolutionStep
from ..steps.final_fixes import FinalFixesStep
from ..steps.load import load_fits
from ..steps.noise import NoiseStep
from ..steps.stretch_step import StretchStep
from ..tools.base import run_cli
from ..tools.graxpert import GraXpert
from ..tools.rcastro import RCAstro
from .image_view import ImageView
from .pipeline import PIPELINE, PROCESSING_ORDER, STEP_NAME, next_enabled, prev_enabled
from .preview import to_qimage
from .settings_dialog import SettingsDialog
from .step_panels import build_panel
from .stepper import Stepper


def _stage_index(stage_id: str) -> int:
    return next(i for i, s in enumerate(PIPELINE) if s.id == stage_id)


class _PrecomputedStep(Step):
    """Pushes an already-computed image into the history (e.g. the starless result)."""

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
        self._stage = 0
        self._before_after = False
        self._bg_runner = run_cli  # injectable for tests / future config
        self._rc_runner = run_cli  # RC-Astro subprocess runner (injectable)
        self._stars_image = None   # stashed stars-only layer for separate export

        central = QWidget()
        root = QHBoxLayout(central)

        self.stepper = Stepper()
        self.stepper.setMaximumWidth(200)
        self.stepper.stageSelected.connect(self._go_to)
        root.addWidget(self.stepper)

        self.image_view = ImageView()
        root.addWidget(self.image_view, 1)

        right = QWidget()
        right.setMinimumWidth(240)
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
        self._export_stars_act = tb.addAction("Export Stars", self._export_stars_layer)
        tb.addAction("Fit", self.image_view.fit)
        tb.addAction("100%", self.image_view.actual_size)

    # --- navigation ---
    def current_stage_id(self) -> str:
        return PIPELINE[self._stage].id

    def go_next(self) -> None:
        self._go_to(next_enabled(self._stage))

    def go_back(self) -> None:
        self._go_to(prev_enabled(self._stage))

    def _go_to(self, index: int) -> None:
        if not PIPELINE[index].enabled:
            return
        self._stage = index
        self._rebuild_panel()
        self._refresh()

    def _go_to_id(self, stage_id: str) -> None:
        self._go_to(_stage_index(stage_id))

    # --- file / project ---
    def _choose_fits(self) -> None:
        path = QFileDialog.getOpenFileName(self, "Open FITS", "", "FITS (*.fit *.fits)")[0]
        if path:
            self.open_fits(path)

    def open_fits(self, path: str) -> None:
        base = load_fits(path)
        os.makedirs(self._cache_dir, exist_ok=True)
        self.project = Project(base, self._cache_dir)
        self._go_to(next_enabled(_stage_index("load")))  # advance Load -> Background

    # --- apply a processing stage ---
    def _step_for(self, stage_id: str):
        if stage_id == "crop":
            return CropStep()
        if stage_id == "color":
            return ColorStep()
        if stage_id in ("deconvolution", "noise"):
            rc = RCAstro(self.settings.rcastro_path) if rcastro_valid(self.settings) else None
            step = DeconvolutionStep(rc) if stage_id == "deconvolution" else NoiseStep(rc)
            step._runner = self._rc_runner
            return step
        if stage_id == "final_fixes":
            return FinalFixesStep()
        if stage_id == "background":
            step = BackgroundStep(GraXpert(self.settings.graxpert_path))
            step._runner = self._bg_runner
            return step
        if stage_id == "stretch":
            return StretchStep()
        raise ValueError(stage_id)

    def apply_current(self, option: str) -> None:
        if self.project is None:
            return
        stage_id = PIPELINE[self._stage].id
        if stage_id not in PROCESSING_ORDER:
            return
        # Truncate history to the entries for processing stages that come BEFORE
        # this one and are actually applied, so a re-apply replaces (not
        # duplicates) this stage and drops anything after it. Counting applied
        # predecessors (not the nominal index) keeps it correct when an earlier
        # stage was skipped.
        preceding = {
            STEP_NAME[sid]
            for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index(stage_id)]
        }
        target = sum(1 for name, _ in self.project.entries() if name in preceding)
        self.project.jump_back(target)
        self.project.run_step(self._step_for(stage_id), option)
        self._go_to(next_enabled(self._stage))

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

    # --- export ---
    def _export_current(self, fmt: str) -> None:
        if not self.project:
            return
        path, selected = QFileDialog.getSaveFileName(
            self, "Export", "", "TIFF (*.tiff);;JPEG (*.jpg)"
        )
        if not path:
            return
        img = self.project.current()
        wants_jpeg = "JPEG" in fmt or path.lower().endswith((".jpg", ".jpeg"))
        if wants_jpeg:
            if not path.lower().endswith((".jpg", ".jpeg")):
                path += ".jpg"
            save_jpeg(img, path)
        else:
            if not path.lower().endswith((".tiff", ".tif")):
                path += ".tiff"
            save_tiff(img, path)

    # --- starless / stars ---
    def _apply_stars(self, mode: str, unscreen: bool) -> None:
        if self.project is None or not rcastro_valid(self.settings):
            return
        rc = RCAstro(self.settings.rcastro_path)
        starless, stars = rc.remove_stars(
            self.project.current(), unscreen=unscreen, runner=self._rc_runner
        )
        self._stars_image = stars
        if mode.startswith("Split"):
            folder = QFileDialog.getExistingDirectory(self, "Export starless + stars to…")
            if folder:
                save_tiff(starless, os.path.join(folder, "starless.tif"))
                save_tiff(stars, os.path.join(folder, "stars.tif"))
        else:  # Remove stars (keep editing)
            self.project.run_step(_PrecomputedStep("Starless", starless), None)
        self._rebuild_panel()
        self._refresh()

    def _export_stars_layer(self) -> None:
        if self._stars_image is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Stars", "", "TIFF (*.tiff);;JPEG (*.jpg)"
        )
        if not path:
            return
        if path.lower().endswith((".jpg", ".jpeg")):
            save_jpeg(self._stars_image, path)
        else:
            if not path.lower().endswith((".tiff", ".tif")):
                path += ".tiff"
            save_tiff(self._stars_image, path)

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
        stage = PIPELINE[self._stage]
        apply_enabled = self.project is not None
        if stage.id == "background":
            apply_enabled = apply_enabled and graxpert_valid(self.settings)
        if stage.id == "stars":
            apply_enabled = apply_enabled and rcastro_valid(self.settings)
        new_panel = build_panel(
            stage,
            on_open=self._choose_fits,
            on_apply=self.apply_current,
            on_export=self._export_current,
            on_stars=self._apply_stars,
            apply_enabled=apply_enabled,
        )
        self._right_layout.replaceWidget(self._panel, new_panel)
        self._panel.deleteLater()
        self._panel = new_panel

    def _refresh(self) -> None:
        self.stepper.set_current(self._stage)
        self.stepper.mark_done(self._done_ids())
        if self.project is not None:
            img = self.project.current()
            if self._before_after:
                before, _ = self.project.before_after()
                img = before
            self.image_view.set_image(to_qimage(img))
        self._back_btn.setEnabled(prev_enabled(self._stage) != self._stage)
        self._next_btn.setEnabled(next_enabled(self._stage) != self._stage)
        self._undo_act.setEnabled(bool(self.project and self.project.can_undo()))
        self._redo_act.setEnabled(bool(self.project and self.project.can_redo()))
        self._export_stars_act.setEnabled(self._stars_image is not None)

    def _done_ids(self) -> set:
        done = set()
        if self.project is None:
            return done
        done.add("load")
        applied = {n for n, _ in self.project.entries()}
        for sid, name in STEP_NAME.items():
            if name in applied:
                done.add(sid)
        if self._stars_image is not None:
            done.add("stars")
        return done
