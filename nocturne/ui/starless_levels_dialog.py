"""Set black and white points on the starless layer of a star split.

The split is done by the caller (it is slow and runs off the UI thread), so this
dialog receives both layers and only chooses the two numbers. `compose()` is the
ONE path used for both the preview and the committed result, so what is on
screen is what Apply produces.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QSlider, QVBoxLayout)

from ..core.enhance import starless_levels_layers
from ..core.image import AstroImage
from ..core.inspect import clip_overlay
from .curves_dialog import _downscale, _fit_to_screen, _ZoomPreview
from .preview import rgb_to_qimage

_SCALE = 1000          # QSlider is integer-only; 0..1000 represents 0.0..1.0
_PREFERRED = (1100, 720)


class StarlessLevelsDialog(QDialog):
    def __init__(self, starless: AstroImage, stars: AstroImage, parent=None,
                 on_apply=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Starless Levels")
        self.resize(*_fit_to_screen(*_PREFERRED))
        self._starless = starless
        self._stars = stars
        self._small_starless = _downscale(starless)
        self._small_stars = _downscale(stars)
        self._on_apply = on_apply

        self.black_slider = QSlider(Qt.Orientation.Horizontal)
        self.black_slider.setRange(0, _SCALE)
        self.black_slider.setValue(0)
        self.white_slider = QSlider(Qt.Orientation.Horizontal)
        self.white_slider.setRange(0, _SCALE)
        self.white_slider.setValue(_SCALE)
        self.black_val = QLabel("0.000")
        self.white_val = QLabel("1.000")

        self.clip_check = QCheckBox("Show Clipping")
        self.clip_check.setChecked(False)
        self.clip_check.setToolTip(
            "Light up pixels that have gone pure black or pure white, coloured "
            "by which channel died. Drag until the first specks appear, then "
            "back off.")

        self.preview_label = _ZoomPreview()

        layout = QVBoxLayout(self)
        layout.addWidget(self.preview_label, 1)
        for label, slider, val in (("Black point", self.black_slider, self.black_val),
                                   ("White point", self.white_slider, self.white_val)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(slider, 1)
            row.addWidget(val)
            layout.addLayout(row)
        layout.addWidget(self.clip_check)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Debounced like curves_dialog: a slider drag emits on every tick, and
        # recomposing the full-resolution image on each one stutters. The
        # labels still update immediately — only the (expensive) render waits.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_preview)

        self.black_slider.valueChanged.connect(self._on_slider_changed)
        self.white_slider.valueChanged.connect(self._on_slider_changed)
        self.clip_check.toggled.connect(self._queue_preview)
        self._update_labels()
        self._render_preview()   # first paint, not debounced

    def values(self) -> tuple[float, float]:
        return (self.black_slider.value() / _SCALE,
                self.white_slider.value() / _SCALE)

    def compose(self, starless=None, stars=None) -> AstroImage:
        black, white = self.values()
        return starless_levels_layers(starless if starless is not None else self._starless,
                                      stars if stars is not None else self._stars,
                                      black, white)

    def _update_labels(self) -> None:
        black, white = self.values()
        self.black_val.setText(f"{black:.3f}")
        self.white_val.setText(f"{white:.3f}")

    def _on_slider_changed(self, *_) -> None:
        self._update_labels()
        self._queue_preview()

    def _queue_preview(self, *_) -> None:
        self._timer.start(60)

    def _render_preview(self) -> None:
        """The clipping view REPLACES the picture (as Photoshop's threshold view
        does) rather than tinting it, and its mask comes from the FULL-resolution
        composite: the decimated preview averages a block down, so an isolated
        blown pixel — exactly what dragging the white point is looking for —
        would vanish if the mask were built from the small copy instead."""
        small = self.compose(self._small_starless, self._small_stars)
        rgb = np.clip(small.data * 255.0, 0, 255).astype(np.uint8)
        if rgb.ndim == 2:
            rgb = np.repeat(rgb[..., None], 3, axis=2)
        if self.clip_check.isChecked():
            full = self.compose()
            frgb = np.clip(full.data * 255.0, 0, 255).astype(np.uint8)
            if frgb.ndim == 2:
                frgb = np.repeat(frgb[..., None], 3, axis=2)
            rgb = clip_overlay(frgb, rgb.shape[:2])
        pixmap = QPixmap.fromImage(rgb_to_qimage(rgb))
        self.preview_label.setPixmap(
            pixmap.scaled(self.preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation))

    def _apply(self) -> None:
        if self._on_apply is not None:
            self._on_apply(self.compose(), self.values())
        self.accept()
