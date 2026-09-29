from __future__ import annotations

import os

import numpy as np

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from ..core.export import save_jpeg, save_png, save_tiff
from ..core.share import ASPECTS
from ..core.upscale import (
    UPSCALE_MAX_MP, LanczosEngine, megapixels, output_size, upscale_crop,
    upscale_filename, upscale_provenance_text,
)
from ..settings import start_dir
from .image_view import ImageView
from .worker import run_async
from . import file_dialogs, theme

SCALE = 2   # fixed in v1

NOISE_NOTE = ("Noise Reduction hasn't been applied — enlarging makes noise twice as "
              "visible. Worth running it first.")


def _qimage_from_float(data: np.ndarray) -> QImage:
    """8-bit QImage for previewing a float32 [0,1] AstroImage array. Preview
    only — the real upscale + export always operate on the full float data,
    never this 8-bit copy."""
    arr8 = (np.clip(data, 0.0, 1.0) * 255).astype(np.uint8)
    if arr8.ndim == 2:
        arr8 = np.stack([arr8] * 3, axis=2)
    arr8 = np.ascontiguousarray(arr8)
    h, w = arr8.shape[:2]
    return QImage(arr8.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def _dispatch_save(img, path: str) -> None:
    """Default `_save_runner`: pick the writer by the export extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".tiff", ".tif"):
        save_tiff(img, path)
    elif ext == ".png":
        save_png(img, path)
    else:
        save_jpeg(img, path)


class UpscaleDialog(QDialog):
    def __init__(self, img, metadata: dict, settings, rc=None, on_open_copy=None, parent=None,
                 *, denoised: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle("Upscale Crop")
        self.setMinimumSize(800, 500)
        self.resize(1000, 640)
        self._img = img
        self._metadata = metadata
        self._settings = settings
        self._rc = rc
        self._on_open_copy = on_open_copy
        self._scale = SCALE
        self._engine = LanczosEngine()
        self._result = None
        self._busy = False
        self._save_runner = _dispatch_save   # injectable for tests
        self._pool = QThreadPool.globalInstance()

        self.picker = ImageView()
        self.picker.setMinimumSize(360, 320)
        self.picker.set_image(_qimage_from_float(self._img.data))
        self.picker.set_crop_overlay(True, aspect_ratio=None)
        self.picker.cropBoxChanged.connect(lambda *_: self._sync_size())

        self.shape_buttons, group = {}, QButtonGroup(self)
        shapes = QHBoxLayout()
        for label, ratio in ASPECTS:
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, r=ratio: self._set_shape(r))
            group.addButton(b)
            shapes.addWidget(b)
            self.shape_buttons[label] = b
        self.shape_buttons["Original"].setChecked(True)

        self.size_label = QLabel("")
        self.noise_note = QLabel(NOISE_NOTE)
        self.noise_note.setWordWrap(True)
        self.noise_note.setStyleSheet(f"color: {theme.WARNING};")
        self.noise_note.setVisible(not denoised)
        self.upscale_btn = QPushButton("Upscale 2×")
        self.upscale_btn.setObjectName("primary")
        self.upscale_btn.clicked.connect(self._on_upscale_clicked)

        panel = QVBoxLayout()
        panel.addWidget(QLabel("<b>Shape</b>"))
        panel.addLayout(shapes)
        panel.addWidget(QLabel("<b>Size</b>"))
        panel.addWidget(self.size_label)
        panel.addWidget(self.noise_note)
        panel.addStretch(1)
        panel.addWidget(self.upscale_btn)
        side = QWidget()
        side.setLayout(panel)
        side.setFixedWidth(240)

        pick = QHBoxLayout()
        pick.addWidget(self.picker, 1)
        pick.addWidget(side)
        pick_page = QWidget()
        pick_page.setLayout(pick)
        self.pages = QStackedWidget()
        self.pages.addWidget(pick_page)
        self.pages.addWidget(QWidget())       # Task 5 replaces this compare page

        self._export_btn = QPushButton("Export…")
        self._export_btn.clicked.connect(self._on_export_clicked)
        self._export_btn.setEnabled(False)
        self._open_copy_btn = QPushButton("Open as copy")
        self._open_copy_btn.clicked.connect(self._do_open_copy)
        self._open_copy_btn.setEnabled(False)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self._export_btn)
        buttons.addWidget(self._open_copy_btn)
        buttons.addStretch(1)
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.reject)
        buttons.addWidget(self._close_btn)

        root = QVBoxLayout(self)
        root.addWidget(self.pages, 1)
        root.addWidget(self.status)
        root.addLayout(buttons)
        self._sync_size()

    # --- shape / size ---
    def _set_shape(self, ratio) -> None:
        self.picker.apply_aspect(ratio)
        self._sync_size()

    def _crop_dims(self) -> tuple[int, int]:
        crop = self._current_crop()
        if crop is None:
            h, w = self._img.data.shape[:2]
            return w, h
        top, bottom, left, right = crop
        return right - left, bottom - top

    def _sync_size(self) -> None:
        w, h = self._crop_dims()
        ow, oh = output_size(w, h, self._scale)
        self.size_label.setText(f"{w} × {h} → {ow} × {oh}")
        mp = megapixels(ow, oh)
        over = mp > UPSCALE_MAX_MP
        self.size_label.setStyleSheet(f"color: {theme.WARNING};" if over else "")
        self.upscale_btn.setEnabled(not over and not self._busy)
        if over:
            self.status.setText(f"Too large to enlarge: {mp:.0f} MP (limit {UPSCALE_MAX_MP} MP). "
                                "Choose a smaller crop.")
        elif self.status.text().startswith("Too large"):
            self.status.setText("")

    # --- crop ---
    def _current_crop(self):
        if self.picker.crop_box_visible():
            top, bottom, left, right = self.picker.crop_bounds()
            if bottom - top > 0 and right - left > 0:
                return (top, bottom, left, right)
        return None

    # --- run (synchronous core; the button routes this off-thread) ---
    def _run_upscale(self) -> None:
        """Compute the upscale and store `._result`. Directly callable and
        synchronous (tests rely on this): it does the real work itself rather
        than merely kicking off a background job. The live "Upscale" button
        instead runs the same computation via `run_async` + a busy indicator,
        since the split + resample can take several seconds."""
        crop = self._current_crop()
        self._result = upscale_crop(self._img, crop, self._engine, scale=self._scale, rc=self._rc)
        self._show_result()
        self._export_btn.setEnabled(True)
        self._open_copy_btn.setEnabled(True)
        h, w = self._result.data.shape[:2]
        self.status.setText(f"Upscaled to {w}×{h}.")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._sync_size()

    def _on_upscale_clicked(self) -> None:
        if self._busy:
            return
        crop = self._current_crop()
        engine = self._engine
        scale = self._scale
        rc = self._rc
        self._set_busy(True)
        self.status.setText("Upscaling…")

        def work():
            return upscale_crop(self._img, crop, engine, scale=scale, rc=rc)

        def on_done(result) -> None:
            self._result = result
            self._set_busy(False)
            self._show_result()
            self._export_btn.setEnabled(True)
            self._open_copy_btn.setEnabled(True)
            h, w = result.data.shape[:2]
            self.status.setText(f"Upscaled to {w}×{h}.")

        def on_error(exc) -> None:
            self._set_busy(False)
            self.status.setText(f"Failed: {exc}")

        run_async(self._pool, work, on_done, on_error)

    def _show_result(self) -> None:
        """Stub: Task 5 shows the comparison view here."""

    # --- export / open as copy ---
    def _on_export_clicked(self) -> None:
        if self._result is None:
            return
        default_name = upscale_filename(self._metadata.get("source_label"), self._scale)
        default_path = os.path.join(start_dir(self._settings.base_dir), default_name)
        path, _ = file_dialogs.save_file(self, "Export upscaled image", default_path,
                                              "JPEG (*.jpg);;PNG (*.png);;TIFF (*.tiff)")
        if path:
            self._do_export(path)

    def _do_export(self, path: str) -> None:
        if self._result is None:
            return
        self._save_runner(self._result, path)
        stem = os.path.splitext(path)[0]
        with open(stem + ".txt", "w") as f:
            f.write(upscale_provenance_text(self._result.metadata))
        self.status.setText(f"Saved {os.path.basename(path)}")

    def _do_open_copy(self) -> None:
        """`on_open_copy` returns False if it declined to swap — it asks first
        when the open project has unsaved edits. Anything else (including the
        None a caller that never declines returns) counts as opened."""
        if self._result is not None and self._on_open_copy is not None:
            if self._on_open_copy(self._result) is False:
                return         # they kept their project; leave the dialog up
            self.accept()      # close so the user lands on the main window showing the copy
                               # (the swap was invisible behind the modal dialog, esp. full screen)
