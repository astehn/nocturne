from __future__ import annotations

import os

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider,
    QSplitter, QVBoxLayout, QWidget,
)

from ..core.share import (
    ALIGNMENTS, ASPECTS, CAPTION_SIZES, DEFAULT_SIZE, FORMATS, PLACEMENTS, SIZES,
    caption_line, centered_crop, share_filename,
)
from .share_render import compose_share, qimage_from_rgb8, save_share, to_clipboard
from ..settings import start_dir
from .image_view import ImageView


class ShareDialog(QDialog):
    def __init__(self, rgb8: np.ndarray, metadata: dict, settings, parent=None,
                 annotated_rgb8: np.ndarray | None = None,
                 annotations_on: bool = True, settings_saver=None) -> None:
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
        self._settings_saver = settings_saver
        self._aspect: float | None = None
        self._aspect_label = "Original"
        self._caption_on = True
        self._size = DEFAULT_SIZE
        self._ext = "jpg"
        self._cap_size = getattr(settings, "share_caption_size", 0.028)
        self._cap_colour = getattr(settings, "share_caption_colour", "#ffffff")
        self._cap_placement = getattr(settings, "share_caption_placement", "on")
        # Has the USER chosen a placement this session? Until they do, annotations
        # get to pick the safe one for them; afterwards their choice stands.
        self._placement_touched = False
        self._cap_align = getattr(settings, "share_caption_align", "left")
        self._band_opacity = getattr(settings, "share_band_opacity", 0.59)
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

        # Free text rather than a checkbox per field. Deleting a field is just
        # deleting words, and you also get "first light with the S30", which no
        # set of toggles can express. Reset restores the generated line.
        self._caption_edit = QLineEdit(caption_line(self._metadata, self._settings.handle))
        self._caption_edit.setPlaceholderText("Caption — anything you like")
        self._caption_edit.textChanged.connect(lambda _t: self._refresh_preview())
        reset_btn = QPushButton("↺")
        reset_btn.setFixedWidth(30)
        reset_btn.setToolTip("Restore the caption generated from this image's data")
        reset_btn.clicked.connect(self._reset_caption)

        self._apply_annotation_placement_default()
        self._place_box = QComboBox()
        for label, key in PLACEMENTS:
            self._place_box.addItem(label, key)
        self._place_box.setCurrentIndex([k for _, k in PLACEMENTS].index(self._cap_placement)
                                        if self._cap_placement in [k for _, k in PLACEMENTS] else 0)
        self._place_box.currentIndexChanged.connect(self._set_placement)
        self._place_box.setToolTip("Below the image never covers any of the picture")

        self._cap_size_box = QComboBox()
        for label, frac in CAPTION_SIZES:
            self._cap_size_box.addItem(label, frac)
        fracs = [f for _, f in CAPTION_SIZES]
        self._cap_size_box.setCurrentIndex(
            min(range(len(fracs)), key=lambda i: abs(fracs[i] - self._cap_size)))
        self._cap_size_box.currentIndexChanged.connect(self._set_cap_size)
        self._cap_size_box.setToolTip(
            "Relative to the image, so it stays right at every export size")

        self._colour_btn = QPushButton()
        self._colour_btn.setFixedWidth(34)
        self._colour_btn.setToolTip("Caption colour")
        self._colour_btn.clicked.connect(self._pick_colour)
        self._paint_colour_btn()

        self._align_box = QComboBox()
        for label, key in ALIGNMENTS:
            self._align_box.addItem(label, key)
        keys = [k for _, k in ALIGNMENTS]
        self._align_box.setCurrentIndex(keys.index(self._cap_align)
                                        if self._cap_align in keys else 0)
        self._align_box.currentIndexChanged.connect(self._set_align)
        self._align_box.setToolTip("Where the caption sits along the band")

        self._opacity = QSlider(Qt.Orientation.Horizontal)
        self._opacity.setRange(0, 100)
        self._opacity.setValue(round(self._band_opacity * 100))
        self._opacity.setFixedWidth(110)
        self._opacity.valueChanged.connect(self._set_opacity)
        self._opacity_label = QLabel()

        # Two rows: what the caption SAYS, then how it LOOKS. One row would have
        # squeezed the text field down to nothing once the styling controls were
        # added, and the text is the part you actually type into.
        text_row = QHBoxLayout()
        text_row.addWidget(self._caption_edit, 1)
        text_row.addWidget(reset_btn)

        style_row = QHBoxLayout()
        style_row.addWidget(self._place_box)
        style_row.addWidget(self._align_box)
        style_row.addWidget(self._cap_size_box)
        style_row.addWidget(self._colour_btn)
        style_row.addWidget(QLabel("Band"))
        style_row.addWidget(self._opacity)
        style_row.addWidget(self._opacity_label)
        style_row.addStretch(1)

        caption_row = QVBoxLayout()
        caption_row.setContentsMargins(0, 0, 0, 0)
        caption_row.addLayout(text_row)
        caption_row.addLayout(style_row)
        self._caption_wrap = QWidget()
        self._caption_wrap.setLayout(caption_row)
        self._caption_wrap.setEnabled(self._caption_on)
        self._sync_opacity_enabled()

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
        root.addWidget(self._caption_wrap)
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
        before = self._cap_placement
        self._apply_annotation_placement_default()
        if self._cap_placement != before:
            self._place_box.blockSignals(True)     # a default must not read as a user choice
            self._place_box.setCurrentIndex([k for _, k in PLACEMENTS].index(self._cap_placement))
            self._place_box.blockSignals(False)
            self._sync_opacity_enabled()
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
        self._caption_wrap.setEnabled(self._caption_on)
        self._refresh_preview()

    def _reset_caption(self) -> None:
        self._caption_edit.setText(caption_line(self._metadata, self._settings.handle))

    def _paint_colour_btn(self) -> None:
        self._colour_btn.setStyleSheet(
            f"background:{self._cap_colour}; border:1px solid #666;")

    def _pick_colour(self) -> None:
        c = QColorDialog.getColor(QColor(self._cap_colour), self, "Caption colour")
        if c.isValid():
            self._cap_colour = c.name()
            self._paint_colour_btn()
            self._persist_caption_style()
            self._refresh_preview()

    def _apply_annotation_placement_default(self) -> None:
        """With annotations burned in, put the caption BELOW the image by default.

        On-image, the band is painted over the bottom of the picture — and with
        an overlay present, that is whatever the overlay drew there. On a real
        NGC 7000 export it swallowed the RA grid labels and cut the B 358 object
        label in half. The two features were built independently and neither knew
        about the other; below-image extends the canvas instead, so a collision
        is not possible rather than merely unlikely.

        A DEFAULT, not a lock: the dropdown still offers on-image, and once the
        user picks a placement themselves that choice is respected for the rest
        of the session. Deliberately not persisted either — it belongs to "this
        share has annotations", not to the user's house style.
        """
        if self._annotations_on and not self._placement_touched:
            self._cap_placement = "below"

    def _set_placement(self, _i: int) -> None:
        self._placement_touched = True
        self._cap_placement = self._place_box.currentData()
        self._sync_opacity_enabled()
        self._persist_caption_style()
        self._refresh_preview()

    def _sync_opacity_enabled(self) -> None:
        """The band slider is always live. It was disabled for "Below image" on
        the reasoning that a strip on fresh canvas has nothing to see through —
        correct about alpha, wrong as a control. Disabling it left the user with
        a slider that could not be moved and a tooltip nobody hovers, which reads
        as broken rather than as unavailable. It now means "how dark the band is"
        in both modes, so it always does something visible."""
        on_image = self._cap_placement != "below"
        self._opacity.setEnabled(True)
        self._opacity_label.setText(f"{self._opacity.value()}%")
        self._opacity.setToolTip(
            "How much of the picture shows through the band" if on_image
            else "How dark the strip under the image is (100% = black)")

    def _set_align(self, _i: int) -> None:
        self._cap_align = self._align_box.currentData()
        self._persist_caption_style()
        self._refresh_preview()

    def _set_opacity(self, value: int) -> None:
        self._band_opacity = value / 100.0
        self._opacity_label.setText(f"{value}%")
        self._persist_caption_style()
        self._refresh_preview()

    def _set_cap_size(self, _i: int) -> None:
        self._cap_size = self._cap_size_box.currentData()
        self._persist_caption_style()
        self._refresh_preview()

    def _persist_caption_style(self) -> None:
        """Style is a personal house style, not a per-image choice — re-picking
        it on every share would be absurd. The TEXT is deliberately not saved:
        it belongs to this image."""
        self._settings.share_caption_size = self._cap_size
        self._settings.share_caption_colour = self._cap_colour
        self._settings.share_caption_placement = self._cap_placement
        self._settings.share_caption_align = self._cap_align
        self._settings.share_band_opacity = self._band_opacity
        if self._settings_saver:
            self._settings_saver(self._settings)

    def _current_caption(self) -> str:
        if not self._caption_on:
            return ""
        return self._caption_edit.text()

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
                             self._current_caption(), longest_edge=self._size,
                             size_frac=self._cap_size, colour=self._cap_colour,
                             placement=self._cap_placement, align=self._cap_align,
                             band_opacity=self._band_opacity)

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
