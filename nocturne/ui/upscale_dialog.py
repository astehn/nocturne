from __future__ import annotations

import os

import numpy as np

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

from ..core.export import save_jpeg, save_png, save_tiff
from ..core.upscale import LanczosEngine, upscale_crop, upscale_filename, upscale_provenance_text
from ..settings import start_dir
from .image_view import ImageView
from .worker import run_async
from . import file_dialogs

SCALE = 2   # fixed in v1; only the engine choice varies


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
    def __init__(self, img, metadata: dict, settings, rc=None, on_open_copy=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Upscale crop")
        self.setMinimumSize(800, 500)
        self.resize(1000, 640)
        self._img = img
        self._metadata = metadata
        self._settings = settings
        self._rc = rc
        self._on_open_copy = on_open_copy
        self._scale = SCALE
        self._engines = [LanczosEngine()]   # v1: Lanczos only; EDSR appends later
        self._engine = self._engines[0]
        self._result = None
        self._compare_on = False
        self._busy = False
        self._save_runner = _dispatch_save   # injectable for tests
        self._pool = QThreadPool.globalInstance()

        self._image_view = ImageView()
        self._image_view.setMinimumSize(360, 320)
        self._image_view.set_image(_qimage_from_float(self._img.data))
        self._image_view.set_crop_overlay(True, aspect_ratio=None)

        self._preview_label = QLabel("Run Upscale to see a preview.")
        self._preview_label.setMinimumSize(240, 220)
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setWordWrap(True)

        self._engine_box = QComboBox()
        self._engine_box.addItems([e.name for e in self._engines])
        self._engine_box.currentIndexChanged.connect(self._select_engine)

        self._compare_check = QCheckBox("Compare")
        self._compare_check.toggled.connect(self._set_compare)

        self._upscale_btn = QPushButton("Upscale")
        self._upscale_btn.setObjectName("primary")
        self._upscale_btn.clicked.connect(self._on_upscale_clicked)

        controls = QHBoxLayout()
        # A dropdown offering exactly one choice is a control that does nothing.
        # It exists because EDSR is meant to join Lanczos later; until it does,
        # both the label and the box stay out of the way.
        self._engine_label = QLabel("Engine")
        controls.addWidget(self._engine_label)
        controls.addWidget(self._engine_box)
        if len(self._engines) < 2:
            self._engine_label.setVisible(False)
            self._engine_box.setVisible(False)
        controls.addWidget(QLabel("2×"))
        controls.addWidget(self._upscale_btn)
        controls.addStretch(1)
        controls.addWidget(self._compare_check)
        controls_wrap = QWidget()
        controls_wrap.setLayout(controls)

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

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self._image_view)
        self.splitter.addWidget(self._preview_label)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([500, 500])
        self.splitter.setChildrenCollapsible(False)

        root = QVBoxLayout(self)
        root.addWidget(controls_wrap)
        root.addWidget(self.splitter, 1)
        root.addWidget(self.status)
        root.addLayout(buttons)

    # --- engine / compare ---
    def _select_engine(self, index: int) -> None:
        if 0 <= index < len(self._engines):
            self._engine = self._engines[index]

    def _set_compare(self, on) -> None:
        self._compare_on = bool(on)
        self._refresh_preview()

    # --- crop ---
    def _current_crop(self):
        if self._image_view.crop_box_visible():
            top, bottom, left, right = self._image_view.crop_bounds()
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
        self._refresh_preview()
        self._export_btn.setEnabled(True)
        self._open_copy_btn.setEnabled(True)
        h, w = self._result.data.shape[:2]
        self.status.setText(f"Upscaled to {w}×{h}.")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._upscale_btn.setEnabled(not busy)

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
            self._refresh_preview()
            self._export_btn.setEnabled(True)
            self._open_copy_btn.setEnabled(True)
            h, w = result.data.shape[:2]
            self.status.setText(f"Upscaled to {w}×{h}.")

        def on_error(exc) -> None:
            self._set_busy(False)
            self.status.setText(f"Failed: {exc}")

        run_async(self._pool, work, on_done, on_error)

    # --- preview ---
    def _refresh_preview(self) -> None:
        if self._result is None:
            self._preview_label.setText("Run Upscale to see a preview.")
            return
        if self._compare_on:
            crop = self._current_crop()
            data = self._img.data if crop is None else self._img.data[crop[0]:crop[1], crop[2]:crop[3]]
            qimage = _qimage_from_float(data)
            target_h, target_w = self._result.data.shape[:2]
            qimage = qimage.scaled(target_w, target_h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
        else:
            qimage = _qimage_from_float(self._result.data)
        pix = QPixmap.fromImage(qimage)
        scaled = pix.scaled(self._preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        self._preview_label.setPixmap(scaled)

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
