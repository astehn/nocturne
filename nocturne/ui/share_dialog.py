from __future__ import annotations

import os
from dataclasses import replace

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
    QSplitter, QVBoxLayout, QWidget,
)

from ..core.plate import PlateText, plate_text
from ..core.presets import PRESETS, style_from_dict, style_to_dict
from ..core.share import (
    ASPECTS, CAPTION_SIZES, DEFAULT_CAPTION_SIZE, DEFAULT_SIZE, FORMATS, SIZES,
    centered_crop, share_filename,
)
from .share_render import compose_share, qimage_from_rgb8, save_share, to_clipboard
from ..settings import start_dir
from .fonts import PLATE_FAMILIES, available_families
from .image_view import ImageView
from .plate_render import ANCHORS, TREATMENTS, last_layout
from . import file_dialogs


def _set_box(box: QComboBox, value) -> None:
    """Move a combo to `value` WITHOUT emitting its signal — a value the code
    chose must not be recorded as a value the user chose."""
    index = box.findData(value)
    if index >= 0:
        box.blockSignals(True)
        box.setCurrentIndex(index)
        box.blockSignals(False)


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
        self._save_runner = save_share            # injectable for tests
        self._clipboard_runner = to_clipboard    # injectable for tests
        # Built first: _compose_current() writes the "will not fit" warning here,
        # and the first compose happens while the rest of the dialog is still
        # being assembled.
        self.status = QLabel("")
        self.status.setWordWrap(True)

        # Type size stays in share_caption_size: it is the same quantity that
        # field always held — caption size as a fraction of the composited
        # height — and the plate has no size slot of its own to put it in.
        self._cap_size = getattr(settings, "share_caption_size", DEFAULT_CAPTION_SIZE)
        # Has the USER chosen a look this session? Until they do, annotations get
        # to pick the safe treatment for them; afterwards their choice stands.
        self._placement_touched = False

        self._presets = self._preset_catalogue()
        start = self._starting_style()
        self._cap_colour = start.colour

        self._image_view = ImageView()
        self._image_view.setMinimumSize(360, 320)
        self._image_view.set_image(qimage_from_rgb8(self._source()))
        self._image_view.set_crop_overlay(True, aspect_ratio=None)
        self._image_view.cropBoxChanged.connect(lambda *_: self._refresh_preview())
        self._image_view.cropBoxShown.connect(self._refresh_preview)

        self._preview_label = QLabel()
        self._preview_label.setMinimumSize(240, 220)
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Ignored, or the scaled pixmap becomes the label's size hint and a large
        # preview walks the splitter wider every time it is repainted.
        self._preview_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                          QSizePolicy.Policy.Ignored)
        self._preview_image = None

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
        self._format_box.setToolTip("PNG is lossless — better for labels and the title plate")

        self._caption_check = QCheckBox("Title plate")
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

        # Three fields rather than one line, because the plate is a composition
        # and not a strip: the object gets one weight, its common name another,
        # the exposure details a third. Each is free text and each is clearable —
        # the auto-fill is a starting point, never a constraint. Reset restores
        # what the image itself says.
        text = plate_text(self._metadata, self._settings.handle)
        self._designation_edit = QLineEdit(text.designation)
        self._designation_edit.setPlaceholderText("Object")
        self._common_edit = QLineEdit(text.common)
        self._common_edit.setPlaceholderText("Common name")
        self._credit_edit = QLineEdit(text.credit)
        self._credit_edit.setPlaceholderText("Exposure, date, @handle")
        for edit in (self._designation_edit, self._common_edit, self._credit_edit):
            edit.textChanged.connect(lambda _t: self._refresh_preview())
        reset_btn = QPushButton("↺")
        reset_btn.setFixedWidth(30)
        reset_btn.setToolTip("Restore the three lines this image's data gives")
        reset_btn.clicked.connect(self._reset_slots)

        self._preset_box = QComboBox()
        for name in self._presets:
            self._preset_box.addItem(name, name)
        _set_box(self._preset_box, start.name)
        self._preset_box.currentIndexChanged.connect(self._set_preset)
        self._preset_box.setToolTip("A whole look in one click — type, treatment and placement")

        # available_families() drops any face Qt refused, so the menu can never
        # offer type the painter would silently substitute. Falling back to the
        # full list keeps the control usable if nothing registered at all.
        self._family_box = QComboBox()
        for label, family in (available_families() or PLATE_FAMILIES):
            self._family_box.addItem(label, family)
        _set_box(self._family_box, start.family)
        self._family_box.currentIndexChanged.connect(self._set_family)
        self._family_box.setToolTip("Bundled with Nocturne, so the export looks the "
                                    "same on every machine")

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
        self._colour_btn.setToolTip("Text colour")
        self._colour_btn.clicked.connect(self._pick_colour)
        self._paint_colour_btn()

        self._treatment_box = QComboBox()
        for label, key in TREATMENTS:
            self._treatment_box.addItem(label, key)
        _set_box(self._treatment_box, start.treatment)
        self._treatment_box.currentIndexChanged.connect(self._set_treatment)
        self._treatment_box.setToolTip("What sits behind the text so it stays readable")

        self._anchor_box = QComboBox()
        for label, key in ANCHORS:
            self._anchor_box.addItem(label, key)
        _set_box(self._anchor_box, start.anchor)
        self._anchor_box.currentIndexChanged.connect(self._set_anchor)
        self._anchor_box.setToolTip("Where the plate sits on the picture")

        self._apply_annotation_treatment_default()

        # Two rows: what the plate SAYS, then how it LOOKS. One row would have
        # squeezed the text fields down to nothing once the styling controls were
        # added, and the text is the part you actually type into.
        text_row = QHBoxLayout()
        text_row.addWidget(self._designation_edit, 3)
        text_row.addWidget(self._common_edit, 4)
        text_row.addWidget(self._credit_edit, 5)
        text_row.addWidget(reset_btn)

        style_row = QHBoxLayout()
        style_row.addWidget(self._preset_box)
        style_row.addWidget(self._family_box)
        style_row.addWidget(self._cap_size_box)
        style_row.addWidget(self._colour_btn)
        style_row.addWidget(self._treatment_box)
        style_row.addWidget(self._anchor_box)
        style_row.addStretch(1)

        caption_row = QVBoxLayout()
        caption_row.setContentsMargins(0, 0, 0, 0)
        caption_row.addLayout(text_row)
        caption_row.addLayout(style_row)
        self._caption_wrap = QWidget()
        self._caption_wrap.setLayout(caption_row)
        self._caption_wrap.setEnabled(self._caption_on)

        self._export_btn = QPushButton("Export…")
        self._export_btn.clicked.connect(self._on_export_clicked)
        self._copy_btn = QPushButton("Copy to clipboard")
        self._copy_btn.clicked.connect(self._do_copy)
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

    # --- the look ---
    def _preset_catalogue(self) -> dict:
        """The shipped presets first, then the user's own saved looks.

        A malformed saved look is skipped rather than raised on: a settings file
        must never be able to stop Share from opening."""
        catalogue = {p.name: p for p in PRESETS}
        for data in list(getattr(self._settings, "plate_user_presets", None) or []):
            try:
                style = style_from_dict(dict(data))
            except (AttributeError, TypeError, ValueError):
                continue
            catalogue[style.name] = style
        return catalogue

    def _starting_style(self):
        """Last session's look, or the saved preset, or the default.

        `plate_style` is only trusted when it names the preset that is actually
        selected — otherwise the two disagree and one of them silently loses."""
        name = str(getattr(self._settings, "plate_preset", "") or "")
        if name not in self._presets:
            name = PRESETS[0].name
        saved = dict(getattr(self._settings, "plate_style", None) or {})
        if saved.get("name") == name:
            try:
                return style_from_dict(saved)
            except (TypeError, ValueError):
                pass
        return self._presets[name]

    def _base_preset(self):
        return self._presets.get(self._preset_box.currentData(), PRESETS[0])

    def _style(self):
        """The style the preview and the export both use. One place, so the two
        cannot disagree — the same reason _compose_current() is the only compose
        path.

        Sizes are scaled rather than set: the preset decides the relationship
        between the three lines, and the size control decides how loud the whole
        plate is. Setting one of them absolutely would flatten the hierarchy the
        preset exists to express.
        """
        base = self._base_preset()
        scale = float(self._cap_size) / DEFAULT_CAPTION_SIZE
        return replace(base,
                       family=self._family_box.currentData() or base.family,
                       treatment=self._treatment_box.currentData() or base.treatment,
                       anchor=self._anchor_box.currentData() or base.anchor,
                       colour=self._cap_colour,
                       size_title=base.size_title * scale,
                       size_sub=base.size_sub * scale,
                       size_credit=base.size_credit * scale)

    def _plate(self) -> PlateText:
        if not self._caption_on:
            return PlateText("", "", "")
        return PlateText(self._designation_edit.text().strip(),
                         self._common_edit.text().strip(),
                         self._credit_edit.text().strip())

    def _sync_style_boxes(self, style) -> None:
        """Point every control at `style` without any of them reporting a user
        choice — a preset is one decision, not five."""
        _set_box(self._family_box, style.family)
        _set_box(self._treatment_box, style.treatment)
        _set_box(self._anchor_box, style.anchor)
        self._cap_colour = style.colour
        self._paint_colour_btn()

    def _set_preset(self, _i: int) -> None:
        self._placement_touched = True     # a preset IS a chosen look
        self._sync_style_boxes(self._base_preset())
        self._persist_plate_style()
        self._refresh_preview()

    def _set_family(self, _i: int) -> None:
        self._persist_plate_style()
        self._refresh_preview()

    def _set_treatment(self, _i: int) -> None:
        self._placement_touched = True
        self._persist_plate_style()
        self._refresh_preview()

    def _set_anchor(self, _i: int) -> None:
        self._persist_plate_style()
        self._refresh_preview()

    # --- aspect / plate text ---
    def _source(self) -> np.ndarray:
        """The pixels every downstream step works from — clean or annotated."""
        if self._annotations_on and self._annotated_rgb8 is not None:
            return self._annotated_rgb8
        return self._rgb8

    def _set_annotations(self, on) -> None:
        self._annotations_on = bool(on)
        self._apply_annotation_treatment_default()
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

    def _reset_slots(self) -> None:
        text = plate_text(self._metadata, self._settings.handle)
        for edit, value in ((self._designation_edit, text.designation),
                            (self._common_edit, text.common),
                            (self._credit_edit, text.credit)):
            edit.blockSignals(True)
            edit.setText(value)
            edit.blockSignals(False)
        self._refresh_preview()            # one redraw, not three

    def _paint_colour_btn(self) -> None:
        self._colour_btn.setStyleSheet(
            f"background:{self._cap_colour}; border:1px solid #666;")

    def _pick_colour(self) -> None:
        c = QColorDialog.getColor(QColor(self._cap_colour), self, "Plate colour")
        if c.isValid():
            self._cap_colour = c.name()
            self._paint_colour_btn()
            self._persist_plate_style()
            self._refresh_preview()

    def _apply_annotation_treatment_default(self) -> None:
        """With annotations burned in, put the plate on a MATTE by default.

        Every other treatment paints over the bottom of the picture — and with an
        overlay present, that is whatever the overlay drew there. On a real
        NGC 7000 export the old caption band swallowed the RA grid labels and cut
        the B 358 object label in half. The two features were built independently
        and neither knew about the other; the matte extends the canvas instead,
        so a collision is not possible rather than merely unlikely.

        A DEFAULT, not a lock: the dropdown still offers every treatment, and
        once the user picks a look themselves that choice is respected for the
        rest of the session. The combo is moved too, so it never reads
        "Gradient" while the preview shows a matte. Deliberately not persisted —
        it belongs to "this share has annotations", not to the user's house
        style.
        """
        if self._placement_touched:
            return
        _set_box(self._treatment_box,
                 "matte" if self._annotations_on else self._base_preset().treatment)

    def _set_cap_size(self, _i: int) -> None:
        self._cap_size = self._cap_size_box.currentData()
        self._persist_plate_style()
        self._refresh_preview()

    def _persist_plate_style(self) -> None:
        """Style is a personal house style, not a per-image choice — re-picking
        it on every share would be absurd. The TEXT is deliberately not saved:
        it belongs to this image."""
        style = self._style()
        if not self._placement_touched and self._annotations_on:
            # The matte came from this image carrying annotations, not from the
            # user. Saving it would make one annotated share change every share
            # that followed.
            style = replace(style, treatment=self._base_preset().treatment)
        self._settings.plate_preset = style.name
        self._settings.plate_style = style_to_dict(style)
        self._settings.share_caption_size = self._cap_size
        if self._settings_saver:
            self._settings_saver(self._settings)

    # --- crop / compose ---
    def _current_crop(self):
        h, w = self._source().shape[:2]
        if self._image_view.crop_box_visible():
            top, bottom, left, right = self._image_view.crop_bounds()
            if bottom - top > 0 and right - left > 0:
                return (top, bottom, left, right)
        return centered_crop(w, h, self._aspect)

    def _compose_current(self) -> QImage:
        plate = self._plate()
        image = compose_share(self._source(), self._current_crop(), plate,
                              longest_edge=self._size, style=self._style())
        # last_layout() is written by the last draw_plate ANYWHERE, so an empty
        # plate — which never reaches the painter — would otherwise report the
        # previous image's overflow.
        drawn = bool(plate.designation or plate.common or plate.credit)
        self.status.setText(
            "Some text will not fit and has been wrapped — shorten it or choose "
            "a smaller size." if drawn and last_layout().get("overflow") else "")
        return image

    def _refresh_preview(self) -> None:
        self._preview_image = self._compose_current()
        self._paint_preview()

    def _paint_preview(self) -> None:
        """Scale the last composed image to whatever room the label has NOW.

        Split from _refresh_preview because __init__ calls that before the
        layout has run, when the label is still at its 240x220 minimum: the
        preview was scaled to a fraction of the pane it eventually occupied and
        never re-scaled, so it sat as a small picture in a large empty box for
        the life of the dialog. That is tolerable for checking a crop and not
        for judging type, which is what this pane is now for.
        """
        if getattr(self, "_preview_image", None) is None:
            return
        self._preview_label.setPixmap(QPixmap.fromImage(self._preview_image).scaled(
            self._preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        # Re-scale from the stored image rather than recomposing: a drag emits a
        # resize per frame, and composing a 4096 px share on each one would make
        # the dialog crawl.
        super().resizeEvent(event)
        self._paint_preview()

    def showEvent(self, event) -> None:  # noqa: N802
        """Paint once more after the layout has settled.

        resizeEvent alone is not enough: the resizes that happen while the
        dialog is being shown arrive before the splitter has taken its final
        geometry, so the preview was still scaled to a stale, smaller pane —
        measured 276x345 inside a 547x473 pane on first open. Same shape as the
        workaround narrowband_dialog carries, and as ImageView.resizeEvent now
        solves for the widget case.
        """
        super().showEvent(event)
        self._paint_preview()

    # --- export / copy ---
    def _on_export_clicked(self) -> None:
        default_name = share_filename(self._metadata.get("source_label"),
                                       self._aspect_label, self._ext)
        default_path = os.path.join(start_dir(self._settings.base_dir), default_name)
        flt = "PNG (*.png)" if self._ext == "png" else "JPEG (*.jpg)"
        path, _ = file_dialogs.save_file(self, "Export share image", default_path, flt)
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
