from __future__ import annotations

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from ..core.image import AstroImage
from ..core.star_spikes import add_spikes, detect_stars
from .frame_preview import FramePreview
from .preview import rgb_to_qimage
from .reset_slider import ResetSlider


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
        self._stars = detect_stars(base.data)          # one-time detection

        self.preview = FramePreview()
        self.length_slider = ResetSlider(0)
        self.intensity_slider = ResetSlider(100, minimum=0, maximum=100)
        self.stars_slider = ResetSlider(6, minimum=0, maximum=50)
        self.angle_slider = ResetSlider(0, minimum=0, maximum=90)
        self.length_val = QLabel("0.00")
        self.intensity_val = QLabel("100%")
        self.stars_val = QLabel("6")
        self.angle_val = QLabel("0°")

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_preview)
        for s in (self.length_slider, self.intensity_slider,
                  self.stars_slider, self.angle_slider):
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
        buttons = QHBoxLayout()
        buttons.addWidget(self.apply_btn)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

        self._render_preview()

    def _params(self):
        return (self.length_slider.value() / 100.0,
                self.stars_slider.value(),
                float(self.angle_slider.value()),
                self.intensity_slider.value() / 100.0)

    def _on_change(self, *_):
        self.length_val.setText(f"{self.length_slider.value() / 100:.2f}")
        self.intensity_val.setText(f"{self.intensity_slider.value()}%")
        self.stars_val.setText(str(self.stars_slider.value()))
        self.angle_val.setText(f"{self.angle_slider.value()}°")
        self._timer.start(90)

    def _render_preview(self) -> None:
        length, count, angle, intensity = self._params()
        self._result = add_spikes(self._base, self._stars, length, count, angle, intensity)
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
