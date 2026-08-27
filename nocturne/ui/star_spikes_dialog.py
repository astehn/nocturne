from __future__ import annotations

import numpy as np
from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from ..core.image import AstroImage
from ..core.star_spikes import _COLOUR_MAX_BOOST, _MAX_STARS, add_spikes, detect_stars
from .frame_preview import FramePreview
from .preview import rgb_to_qimage, to_qimage
from .reset_slider import ResetSlider
from .worker import run_async


class StarSpikesDialog(QDialog):
    """Artistic tool: draw diffraction spikes on the brightest stars of the
    current (display-space) image, with a live preview. Detection runs once on
    open; the three sliders then re-render instantly. Apply hands the rendered
    AstroImage back via `on_apply`."""

    def __init__(self, base: AstroImage, parent=None, on_apply=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Star Spikes")
        self.setMinimumSize(720, 560)
        self._base = base
        self._on_apply = on_apply
        self._result = base
        self._pool = QThreadPool.globalInstance()
        self._stars = None                 # None = still looking; [] = none found

        self.preview = FramePreview()
        self.length_slider = ResetSlider(0)
        self.intensity_slider = ResetSlider(100, minimum=0, maximum=100)
        # Only ever LOWERS the ceiling. SEP finds thousands of objects on a rich
        # field and drawing 2,000 spikes costs 1.7 s per slider tick on a 39.5 MP
        # master, so _MAX_STARS stays the safety cap; this just stops the slider
        # promising stars the image does not contain.
        # Sized properly once detection lands; _MAX_STARS is the ceiling it can
        # never exceed, and _on_stars only ever lowers it.
        self.stars_slider = ResetSlider(6, minimum=0, maximum=_MAX_STARS)
        self.angle_slider = ResetSlider(0, minimum=0, maximum=90)
        self.variation_slider = ResetSlider(35, minimum=0, maximum=100)
        self.colour_slider = ResetSlider(50, minimum=0, maximum=100)
        self.length_val = QLabel("0.00")
        self.intensity_val = QLabel("100%")
        self.stars_val = QLabel("6")
        self.angle_val = QLabel("0°")
        self.variation_val = QLabel("35%")
        self.colour_val = QLabel("×2.00")
        self.compare_check = QCheckBox("Compare with original")
        self.compare_check.toggled.connect(self._on_compare_toggled)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_preview)
        for s in (self.length_slider, self.intensity_slider,
                  self.stars_slider, self.angle_slider,
                  self.variation_slider, self.colour_slider):
            s.valueChanged.connect(self._on_change)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self._apply)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)

        def _row(label, widget, val):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(val)
            outer = QVBoxLayout()
            outer.addLayout(row)
            outer.addWidget(widget)
            return outer

        root = QVBoxLayout(self)
        root.addWidget(self.preview, 1)
        note = QLabel("Add diffraction spikes to the brightest stars. Length 0 = off. "
                      "Keep the star count low so it looks intentional.")
        note.setWordWrap(True)
        root.addWidget(note)
        root.addLayout(_row("Length (off → long)", self.length_slider, self.length_val))
        root.addLayout(_row("Intensity (faint → full)", self.intensity_slider, self.intensity_val))
        root.addLayout(_row("Number of stars", self.stars_slider, self.stars_val))
        root.addLayout(_row("Rotation", self.angle_slider, self.angle_val))
        root.addLayout(_row("Variation (uniform → varied)",
                            self.variation_slider, self.variation_val))
        root.addLayout(_row("Star colour (white → full)",
                            self.colour_slider, self.colour_val))
        root.addWidget(self.compare_check)
        buttons = QHBoxLayout()
        buttons.addWidget(self.reset_btn)
        buttons.addWidget(self.apply_btn)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

        # Detection off the UI thread. It ran in __init__ and cost 0.28 s on an
        # 8.3 MP frame, about 1.3 s on a 39.5 MP master, with a frozen window and
        # nothing on screen saying why.
        self._set_controls_enabled(False)
        self.apply_btn.setEnabled(False)
        self.preview.show_message("Finding stars…")
        run_async(self._pool, lambda: detect_stars(self._base.data),
                  self._on_stars, self._on_detect_error)

    _SLIDER_DEFAULTS = {"length": 0, "intensity": 100, "angle": 0,
                        "variation": 35, "colour": 50}

    def _sliders(self):
        return (self.length_slider, self.intensity_slider, self.stars_slider,
                self.angle_slider, self.variation_slider, self.colour_slider)

    def _set_controls_enabled(self, on: bool) -> None:
        for s in self._sliders():
            s.setEnabled(on)
        self.reset_btn.setEnabled(on)
        self.compare_check.setEnabled(on)

    def _on_stars(self, stars) -> None:
        self._stars = stars
        if not stars:
            self._no_stars()
            return
        cap = min(_MAX_STARS, len(stars))
        self.stars_slider.setMaximum(cap)
        self.stars_slider.setValue(min(6, cap))
        self._set_controls_enabled(True)
        self.apply_btn.setEnabled(True)
        self.preview.overlay.hide()
        self._render_preview()

    def _on_detect_error(self, exc) -> None:
        self._stars = []
        self._no_stars()

    def reset(self) -> None:
        d = self._SLIDER_DEFAULTS
        self.length_slider.setValue(d["length"])
        self.intensity_slider.setValue(d["intensity"])
        self.angle_slider.setValue(d["angle"])
        self.variation_slider.setValue(d["variation"])
        self.colour_slider.setValue(d["colour"])
        # bounded by what this image holds, exactly as _on_stars set it
        self.stars_slider.setValue(min(6, self.stars_slider.maximum()))
        self._on_change()

    def _on_compare_toggled(self, on: bool) -> None:
        """Split-divider compare against the frame as it arrived.

        Set ONCE here, never in _render_preview: set_compare() re-centres the
        divider, so calling it per render would drag the handle back to the
        middle every time a slider moved.
        """
        if not on or self._stars is None:
            self.preview.view.set_compare(None)
            return
        self.preview.view.set_compare(to_qimage(self._base))

    def _no_stars(self) -> None:
        """Say so, rather than leaving four sliders that quietly do nothing.

        Measured on a smooth nebula, a starless export and pure noise: zero
        stars found and every slider a silent no-op, with nothing to tell the
        user whether the tool was broken or the image simply had no stars. A
        starless export is an ordinary input for anyone using Starless + Stars.
        """
        self._set_controls_enabled(False)
        self.apply_btn.setEnabled(False)
        self.preview.show_message(
            "No stars found in this image.\n\n"
            "Star Spikes needs stars to draw on — a starless layer, a very "
            "soft frame, or one that has already had its stars removed will "
            "not give it anything to work with.")

    def _params(self):
        return (self.length_slider.value() / 100.0,
                self.stars_slider.value(),
                float(self.angle_slider.value()),
                self.intensity_slider.value() / 100.0,
                self.variation_slider.value() / 100.0,
                self.colour_slider.value() / 100.0 * _COLOUR_MAX_BOOST)

    def _on_change(self, *_):
        self.length_val.setText(f"{self.length_slider.value() / 100:.2f}")
        self.intensity_val.setText(f"{self.intensity_slider.value()}%")
        self.stars_val.setText(str(self.stars_slider.value()))
        self.angle_val.setText(f"{self.angle_slider.value()}°")
        self.variation_val.setText(f"{self.variation_slider.value()}%")
        self.colour_val.setText(
            f"×{self.colour_slider.value() / 100.0 * _COLOUR_MAX_BOOST:.2f}")
        self._timer.start(90)

    def _render_preview(self) -> None:
        if not self._stars:
            return
        length, count, angle, intensity, variation, colour = self._params()
        self._result = add_spikes(self._base, self._stars, length, count, angle,
                                  intensity, variation, colour)
        data = np.clip(self._result.data, 0.0, 1.0)
        if data.ndim == 2:
            rgb = np.repeat((data * 255 + 0.5).astype(np.uint8)[:, :, None], 3, axis=2)
        else:
            rgb = (data * 255 + 0.5).astype(np.uint8)
        self.preview.show_image(rgb_to_qimage(np.ascontiguousarray(rgb)))

    def result(self) -> AstroImage:
        return self._result

    def _apply(self) -> None:
        self._render_preview()                 # ensure result matches the sliders
        if self._on_apply is not None:
            self._on_apply(self._result)
        self.accept()
