from __future__ import annotations

import os

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

from ..core.share import (
    ASPECTS, DEFAULT_SIZE, FORMATS, SIZES, caption_line, centered_crop,
    share_filename,
)
from .share_render import compose_share, qimage_from_rgb8, save_share, to_clipboard
from ..settings import start_dir
from .image_view import ImageView


class ShareDialog(QDialog):
    def __init__(self, rgb8: np.ndarray, metadata: dict, settings, parent=None,
                 annotated_rgb8: np.ndarray | None = None,
                 annotations_on: bool = True) -> None:
        """`annotated_rgb8` is the same frame with the plate-solve overlay burned
        in, supplied only when a valid solution exists. Sharing an annotated
        image was previously impossible — Share received raw pixels, so the one
        way to publish labels was a PNG export, which skips the reframing and
        caption this dialog exists for."""
        super().__init__(parent)
        self.setWindowTitle("Share")
        self.setMinimumSize(800, 500)
        self.resize(1000, 640)
        self._rgb8 = rgb8
        self._annotated_rgb8 = annotated_rgb8
        self._annotations_on = bool(annotated_rgb8 is not None and annotations_on)
        self._metadata = metadata
        self._settings = settings
        self._aspect: float | None = None
        self._aspect_label = "Original"
        self._caption_on = True
        self._size = DEFAULT_SIZE
        self._ext = "jpg"
        self._save_runner = save_share            # injectable for tests
        self._clipboard_runner = to_clipboard    # injectable for tests

        self._image_view = ImageView()
        self._image_view.setMinimumSize(360, 320)
        self._image_view.set_image(qimage_from_rgb8(self._source()))
        self._image_view.set_crop_overlay(True, aspect_ratio=None)
        self._image_view.cropBoxChanged.connect(lambda *_: self._refresh_preview())
        self._image_view.cropBoxShown.connect(self._refresh_preview)

        self._preview_label = QLabel()
        self._preview_label.setMinimumSize(240, 220)
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Checkable + one exclusive group, so the active aspect is visible. Six
        # plain push-buttons showed no state at all: after clicking around, the
        # only way to know what you would get was to read the preview's shape.
        aspect_row = QHBoxLayout()
        self._aspect_group = QButtonGroup(self)
        self._aspect_group.setExclusive(True)
        self._aspect_buttons: dict[str, QPushButton] = {}
        for label, aspect in ASPECTS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(label == self._aspect_label)
            btn.clicked.connect(lambda _checked=False, a=aspect, lbl=label: self._select_aspect(a, lbl))
            self._aspect_group.addButton(btn)
            self._aspect_buttons[label] = btn
            aspect_row.addWidget(btn)
        # Output controls. Every one of these used to be a constant in the
        # source: 2048 px, JPEG, quality 92. For a tool that exists to produce a
        # file for somewhere else, not being able to say how big or what format
        # was the clearest sense in which it was unfinished.
        self._size_box = QComboBox()
        for label, px in SIZES:
            self._size_box.addItem(label, px)
        self._size_box.setCurrentIndex([px for _, px in SIZES].index(DEFAULT_SIZE))
        self._size_box.currentIndexChanged.connect(self._set_size)
        self._size_box.setToolTip("Longest edge of the shared image (never upscaled)")

        self._format_box = QComboBox()
        for label, ext in FORMATS:
            self._format_box.addItem(label, ext)
        self._format_box.currentIndexChanged.connect(self._set_format)
        self._format_box.setToolTip("PNG is lossless — better for labels and the caption band")

        self._caption_check = QCheckBox("Caption")
        self._caption_check.setChecked(True)
        self._caption_check.toggled.connect(self._set_caption)
        # Only offered when a solution exists — a dead checkbox would imply the
        # feature is broken rather than unavailable.
        self._annot_check = QCheckBox("Annotations")
        self._annot_check.setChecked(self._annotations_on)
        self._annot_check.setVisible(annotated_rgb8 is not None)
        self._annot_check.toggled.connect(self._set_annotations)
        aspect_row.addStretch(1)
        aspect_row.addWidget(self._size_box)
        aspect_row.addWidget(self._format_box)
        aspect_row.addWidget(self._annot_check)
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
        root.addWidget(aspect_wrap)
        root.addWidget(self.splitter, 1)
        root.addWidget(self.status)
        root.addLayout(buttons)

        self._refresh_preview()

    # --- aspect / caption ---
    def _source(self) -> np.ndarray:
        """The pixels every downstream step works from — clean or annotated."""
        if self._annotations_on and self._annotated_rgb8 is not None:
            return self._annotated_rgb8
        return self._rgb8

    def _set_annotations(self, on) -> None:
        self._annotations_on = bool(on)
        # Re-set the canvas so the crop box keeps its geometry while the pixels
        # underneath it change.
        box = self._image_view.crop_box() if hasattr(self._image_view, "crop_box") else None
        self._image_view.set_image(qimage_from_rgb8(self._source()))
        if box is not None and hasattr(self._image_view, "show_crop_box"):
            self._image_view.show_crop_box()
        self._refresh_preview()

    def _select_aspect(self, aspect, label: str) -> None:
        self._aspect = aspect
        self._aspect_label = label
        btn = self._aspect_buttons.get(label)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)      # keeps the row honest when called in code
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

    def _set_size(self, _index: int) -> None:
        self._size = self._size_box.currentData()
        self._refresh_preview()

    def _set_format(self, _index: int) -> None:
        self._ext = self._format_box.currentData()

    def _set_caption(self, on) -> None:
        self._caption_on = bool(on)
        self._refresh_preview()

    def _current_caption(self) -> str:
        if not self._caption_on:
            return ""
        return caption_line(self._metadata, self._settings.handle)

    # --- crop / compose ---
    def _current_crop(self):
        h, w = self._source().shape[:2]
        if self._image_view.crop_box_visible():
            top, bottom, left, right = self._image_view.crop_bounds()
            if bottom - top > 0 and right - left > 0:
                return (top, bottom, left, right)
        return centered_crop(w, h, self._aspect)

    def _compose_current(self) -> QImage:
        return compose_share(self._source(), self._current_crop(),
                             self._current_caption(), longest_edge=self._size)

    def _refresh_preview(self) -> None:
        image = self._compose_current()
        pix = QPixmap.fromImage(image)
        scaled = pix.scaled(self._preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        self._preview_label.setPixmap(scaled)

    # --- export / copy ---
    def _on_export_clicked(self) -> None:
        default_name = share_filename(self._metadata.get("source_label"),
                                       self._aspect_label, self._ext)
        default_path = os.path.join(start_dir(self._settings.base_dir), default_name)
        flt = "PNG (*.png)" if self._ext == "png" else "JPEG (*.jpg)"
        path, _ = QFileDialog.getSaveFileName(self, "Export share image", default_path, flt)
        if path:
            self._do_export(path)

    def _do_export(self, path: str) -> None:
        image = self._compose_current()
        self._save_runner(image, path)
        # Report the pixel size: it is the thing you check before posting, and
        # "Saved name.jpg" alone never answered it.
        self.status.setText(
            f"Saved {os.path.basename(path)} — {image.width()} × {image.height()}")

    def _do_copy(self) -> None:
        self._clipboard_runner(self._compose_current())
        self.status.setText("Copied to clipboard.")
