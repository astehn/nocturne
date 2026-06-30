from __future__ import annotations

import os

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QListWidget, QMainWindow, QPushButton,
    QVBoxLayout, QWidget, QComboBox,
)

from ..core.export import save_jpeg, save_tiff
from ..history.project import Project
from ..settings import load_settings, save_settings, graxpert_valid
from ..steps.background import BackgroundStep
from ..steps.load import load_fits
from ..steps.stretch_step import StretchStep
from ..tools.graxpert import GraXpert
from .preview import to_qimage
from .settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self, settings_path: str) -> None:
        super().__init__()
        self.setWindowTitle("Seestar Processor")
        self._settings_path = settings_path
        self.settings = load_settings(settings_path)
        self.project: Project | None = None
        self._cache_dir = os.path.join(os.path.dirname(settings_path), "cache")

        self.stretch_step = StretchStep()

        central = QWidget()
        root = QHBoxLayout(central)

        self.step_list = QListWidget()
        self.step_list.itemClicked.connect(self._on_step_clicked)
        root.addWidget(self.step_list, 1)

        self.preview_label = QLabel("Open a FITS file to begin")
        self.preview_label.setMinimumSize(640, 360)
        root.addWidget(self.preview_label, 4)

        panel = QWidget()
        pl = QVBoxLayout(panel)
        self.option_box = QComboBox()
        pl.addWidget(QLabel("Strength / preset"))
        pl.addWidget(self.option_box)
        self.bg_button = QPushButton("Apply Background")
        self.bg_button.clicked.connect(self._apply_background)
        self.stretch_button = QPushButton("Apply Stretch")
        self.stretch_button.clicked.connect(self._apply_stretch)
        pl.addWidget(self.bg_button)
        pl.addWidget(self.stretch_button)
        pl.addStretch(1)
        root.addWidget(panel, 1)

        self.setCentralWidget(central)
        self._build_toolbar()
        self._refresh_enabled()

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Main")
        tb.addAction("Open FITS", self._choose_fits)
        tb.addAction("Settings", self._open_settings)
        self._undo_act = tb.addAction("Undo", self._undo)
        self._redo_act = tb.addAction("Redo", self._redo)
        self._ba_act = tb.addAction("Before/After", self._toggle_before_after)
        self._ba_act.setCheckable(True)
        tb.addAction("Export", self._export)

    # --- file / project ---
    def _choose_fits(self) -> None:
        path = QFileDialog.getOpenFileName(self, "Open FITS", "", "FITS (*.fit *.fits)")[0]
        if path:
            self.open_fits(path)

    def open_fits(self, path: str) -> None:
        base = load_fits(path)
        os.makedirs(self._cache_dir, exist_ok=True)
        self.project = Project(base, self._cache_dir)
        self._render()
        self._refresh_steps()
        self._refresh_enabled()

    # --- steps ---
    def apply_step(self, step, option: str) -> None:
        assert self.project is not None
        self.project.run_step(step, option)
        self._render()
        self._refresh_steps()
        self._refresh_enabled()

    def _apply_background(self) -> None:
        gx = GraXpert(self.settings.graxpert_path)
        self.apply_step(BackgroundStep(gx), self.option_box.currentText() or "Medium")

    def _apply_stretch(self) -> None:
        self.apply_step(self.stretch_step, self.option_box.currentText() or "Medium")

    # --- history ---
    def _undo(self) -> None:
        if self.project:
            self.project.undo()
            self._render(); self._refresh_steps(); self._refresh_enabled()

    def _redo(self) -> None:
        if self.project:
            self.project.redo()
            self._render(); self._refresh_steps(); self._refresh_enabled()

    def _toggle_before_after(self) -> None:
        if not self.project:
            return
        before, after = self.project.before_after()
        self._show(before if self._ba_act.isChecked() else after)

    def _on_step_clicked(self, item) -> None:
        if not self.project:
            return
        # step_list row 0 == "Load" (base); rows 1..N map to entries(). Guard
        # against a stale row (jump_back raises IndexError for row > position).
        row = self.step_list.row(item)
        if 0 <= row <= len(self.project.entries()):
            self.project.jump_back(row)
            self._render(); self._refresh_steps(); self._refresh_enabled()

    # --- export ---
    def _export(self) -> None:
        if not self.project:
            return
        path, selected = QFileDialog.getSaveFileName(
            self, "Export", "", "TIFF (*.tiff);;JPEG (*.jpg)"
        )
        if not path:
            return
        img = self.project.current()
        wants_jpeg = path.lower().endswith((".jpg", ".jpeg")) or "JPEG" in selected
        if wants_jpeg:
            if not path.lower().endswith((".jpg", ".jpeg")):
                path += ".jpg"
            save_jpeg(img, path)
        else:
            if not path.lower().endswith((".tiff", ".tif")):
                path += ".tiff"
            save_tiff(img, path)

    # --- settings ---
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.result_settings()
            save_settings(self.settings, self._settings_path)
            self._refresh_enabled()

    # --- rendering / state ---
    def _render(self) -> None:
        if self.project:
            self._show(self.project.current())
        # populate option box from current default step (stretch presets are fine for both)
        if self.option_box.count() == 0:
            self.option_box.addItems(["Small", "Medium", "Large"])

    def _show(self, img) -> None:
        self.preview_label.setPixmap(QPixmap.fromImage(to_qimage(img)))

    def _refresh_steps(self) -> None:
        self.step_list.clear()
        self.step_list.addItem("Load")
        if self.project:
            for name, opt in self.project.entries():
                self.step_list.addItem(f"{name} ({opt})")

    def _refresh_enabled(self) -> None:
        has = self.project is not None
        self.bg_button.setEnabled(has and graxpert_valid(self.settings))
        self.stretch_button.setEnabled(has)
        self._undo_act.setEnabled(bool(self.project and self.project.can_undo()))
        self._redo_act.setEnabled(bool(self.project and self.project.can_redo()))
