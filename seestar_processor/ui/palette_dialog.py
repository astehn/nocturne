from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from ..core.export import save_fits, save_png, save_tiff
from ..core.fits_io import load_master
from ..core.palette import apply_palette, subtract_background

_EXPORTERS = {
    ".tiff": save_tiff, ".tif": save_tiff, ".png": save_png,
    ".fits": save_fits, ".fit": save_fits, ".fts": save_fits,
}


def _picker_row(edit: QLineEdit, on_browse) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(edit)
    btn = QPushButton("Browse…")
    btn.clicked.connect(on_browse)
    lay.addWidget(btn)
    return row


class PaletteDialog(QDialog):
    def __init__(self, settings, parent=None, on_master=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Narrowband palette")
        self.setMinimumWidth(500)
        self._settings = settings
        self._on_master = on_master
        self._palette_runner = apply_palette   # injectable for tests
        self._loader = load_master             # injectable for tests

        self.input_edit = QLineEdit()
        self.output_edit = QLineEdit()
        self.hoo_radio = QRadioButton("HOO — honest duo-band (Ha/OIII)")
        self.sho_radio = QRadioButton("Pseudo-SHO — SHO look from Ha+OIII only (no real SII)")
        self.hoo_radio.setChecked(True)
        self.bg_check = QCheckBox("Subtract background first (recommended for a raw stack)")
        self.bg_check.setChecked(True)
        self.open_check = QCheckBox("Open result in the editor")
        self.open_check.setChecked(True)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.hoo_radio.toggled.connect(self._suggest_output)

        form = QFormLayout()
        form.addRow("Master image", _picker_row(self.input_edit, self._browse_input))
        palettes = QVBoxLayout()
        palettes.addWidget(self.hoo_radio)
        palettes.addWidget(self.sho_radio)
        pal_wrap = QWidget()
        pal_wrap.setLayout(palettes)
        form.addRow("Palette", pal_wrap)
        form.addRow("Output", _picker_row(self.output_edit, self._browse_output))
        form.addRow("", self.bg_check)
        form.addRow("", self.open_check)

        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self.run)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(apply_btn)
        buttons.addWidget(close_btn)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self.status)
        root.addLayout(buttons)

    # --- browse ---
    def _browse_input(self) -> None:
        path = QFileDialog.getOpenFileName(
            self, "Master image", "", "Masters (*.fits *.fit *.fts *.tif *.tiff)")[0]
        if path:
            self.input_edit.setText(path)
            self._suggest_output()

    def _browse_output(self) -> None:
        path = QFileDialog.getSaveFileName(
            self, "Output", "", "Image (*.tiff *.fits *.png)")[0]
        if path:
            self.output_edit.setText(path)

    def _suggest_output(self) -> None:
        inp = self.input_edit.text().strip()
        if not inp:
            return
        stem, ext = os.path.splitext(inp)
        if ext.lower() not in _EXPORTERS:
            ext = ".tiff"
        tag = "HOO" if self.hoo_radio.isChecked() else "SHO"
        self.output_edit.setText(f"{stem}_{tag}{ext}")

    # --- run (synchronous — palette math is fast) ---
    def run(self) -> None:
        inp = self.input_edit.text().strip()
        out = self.output_edit.text().strip()
        if not inp or not out:
            self.status.setText("Pick an input master and an output path.")
            return
        name = "HOO" if self.hoo_radio.isChecked() else "pseudo_SHO"
        exporter = _EXPORTERS.get(os.path.splitext(out)[1].lower())
        if exporter is None:
            self.status.setText("Unsupported output format (use .tiff, .fits or .png).")
            return
        try:
            img = self._loader(inp)
            if self.bg_check.isChecked():
                img = subtract_background(img)
            result = self._palette_runner(img, name)
            exporter(result, out)
        except Exception as exc:
            self.status.setText(f"Failed: {exc}")
            return
        self.status.setText(f"Wrote {os.path.basename(out)}.")
        if self.open_check.isChecked() and self._on_master is not None:
            self._on_master(result)
        self.accept()
