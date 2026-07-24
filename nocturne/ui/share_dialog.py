from __future__ import annotations

import os

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

from ..core.share import (
    ASPECTS, caption_line, centered_crop, compose_share, save_share_jpeg,
    share_filename, to_clipboard,
)
from ..settings import start_dir
from .image_view import ImageView


def _qimage_from_rgb8(rgb8: np.ndarray) -> QImage:
    if rgb8.ndim == 2:
        rgb8 = np.stack([rgb8] * 3, axis=2)
    rgb8 = np.ascontiguousarray(rgb8.astype(np.uint8))
    h, w = rgb8.shape[:2]
    return QImage(rgb8.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class ShareDialog(QDialog):
    def __init__(self, rgb8: np.ndarray, metadata: dict, settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Share")
        self.setMinimumSize(800, 500)
        self.resize(1000, 640)
        self._rgb8 = rgb8
        self._metadata = metadata
        self._settings = settings
        self._aspect: float | None = None
        self._aspect_label = "Original"
        self._caption_on = True
        self._save_runner = save_share_jpeg      # injectable for tests
        self._clipboard_runner = to_clipboard    # injectable for tests

        self._image_view = ImageView()
        self._image_view.setMinimumSize(360, 320)
        self._image_view.set_image(_qimage_from_rgb8(self._rgb8))
        self._image_view.set_crop_overlay(True, aspect_ratio=None)
        self._image_view.cropBoxChanged.connect(lambda *_: self._refresh_preview())
        self._image_view.cropBoxShown.connect(self._refresh_preview)

        self._preview_label = QLabel()
        self._preview_label.setMinimumSize(240, 220)
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        aspect_row = QHBoxLayout()
        for label, aspect in ASPECTS:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, a=aspect, lbl=label: self._select_aspect(a, lbl))
            aspect_row.addWidget(btn)
        self._caption_check = QCheckBox("Caption")
        self._caption_check.setChecked(True)
        self._caption_check.toggled.connect(self._set_caption)
        aspect_row.addStretch(1)
        aspect_row.addWidget(self._caption_check)
        aspect_wrap = QWidget()
        aspect_wrap.setLayout(aspect_row)

        self._export_btn = QPushButton("Export…")
        self._export_btn.clicked.connect(self._on_export_clicked)
        self._copy_btn = QPushButton("Copy to clipboard")
        self._copy_btn.clicked.connect(self._do_copy)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self._export_btn)
        buttons.addWidget(self._copy_btn)
        buttons.addStretch(1)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self._image_view)
        self.splitter.addWidget(self._preview_label)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([500, 500])
        self.splitter.setChildrenCollapsible(False)

        root = QVBoxLayout(self)
        root.addWidget(aspect_wrap)
        root.addWidget(self.splitter, 1)
        root.addWidget(self.status)
        root.addLayout(buttons)

        self._refresh_preview()

    # --- aspect / caption ---
    def _select_aspect(self, aspect, label: str) -> None:
        self._aspect = aspect
        self._aspect_label = label
        self._image_view.set_aspect(aspect)
        if aspect is None:
            # Original = full frame, no crop. Drop any prior aspect box so the
            # user can go "back" to the whole image (crop_box hidden -> _current_crop
            # falls through to the full-frame centered_crop).
            self._image_view.hide_crop_box()
        else:
            self._image_view.show_crop_box()
            self._image_view.apply_aspect(aspect)
        self._refresh_preview()

    def _set_caption(self, on) -> None:
        self._caption_on = bool(on)
        self._refresh_preview()

    def _current_caption(self) -> str:
        if not self._caption_on:
            return ""
        return caption_line(self._metadata, self._settings.handle)

    # --- crop / compose ---
    def _current_crop(self):
        h, w = self._rgb8.shape[:2]
        if self._image_view.crop_box_visible():
            top, bottom, left, right = self._image_view.crop_bounds()
            if bottom - top > 0 and right - left > 0:
                return (top, bottom, left, right)
        return centered_crop(w, h, self._aspect)

    def _compose_current(self) -> QImage:
        return compose_share(self._rgb8, self._current_crop(), self._current_caption())

    def _refresh_preview(self) -> None:
        image = self._compose_current()
        pix = QPixmap.fromImage(image)
        scaled = pix.scaled(self._preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        self._preview_label.setPixmap(scaled)

    # --- export / copy ---
    def _on_export_clicked(self) -> None:
        default_name = share_filename(self._metadata.get("source_label"), self._aspect_label)
        default_path = os.path.join(start_dir(self._settings.base_dir), default_name)
        path, _ = QFileDialog.getSaveFileName(self, "Export share image", default_path, "JPEG (*.jpg)")
        if path:
            self._do_export(path)

    def _do_export(self, path: str) -> None:
        self._save_runner(self._compose_current(), path)
        self.status.setText(f"Saved {os.path.basename(path)}")

    def _do_copy(self) -> None:
        self._clipboard_runner(self._compose_current())
        self.status.setText("Copied to clipboard.")
