from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from ..core.image import AstroImage
from ..core.narrowband import NarrowbandParams, render, screen
from ..settings import rcastro_valid, resolve_binary
from ..tools.rcastro import RCAstro
from .frame_preview import FramePreview
from .preview import to_qimage
from .reset_slider import ResetSlider
from .worker import run_async

_PREVIEW_MAX = 640
_DEBOUNCE_MS = 90
PALETTES = ["HOO", "Pseudo-SHO", "Pseudo-bicolor"]


def _downscale(img: AstroImage) -> AstroImage:
    h, w = img.data.shape[:2]
    step = max(1, max(h, w) // _PREVIEW_MAX)
    return AstroImage(np.ascontiguousarray(img.data[::step, ::step]),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


class NarrowbandDialog(QDialog):
    """Interactive narrowband recolour with live preview. Applied to a STARLESS
    nebula so stars keep their natural colour: on open we split stars
    (StarXTerminator, or whole-image without it), the user tweaks the starless
    recolour live, and on Apply the stars are screened back."""

    def __init__(self, settings, base: AstroImage, parent=None, on_apply=None,
                 starless=None, stars=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Narrowband")
        self.resize(1100, 720)
        self._settings = settings
        self._base = base
        self._on_apply = on_apply
        self._pool = QThreadPool.globalInstance()
        self._starx_runner = self._default_starx
        self._starless = starless
        self._stars = stars
        self._prev_starless = None
        self._last = None                 # last rendered starless AstroImage (preview)
        self._fitted = False
        self._started = False

        self.preview = FramePreview()
        self.preview.setMinimumSize(460, 460)

        self.palette_box = QComboBox()
        self.palette_box.addItems(PALETTES)
        self.blend_slider = ResetSlider(60)
        self.oiii_slider = ResetSlider(50)
        self.sat_slider = ResetSlider(50)
        self.bright_slider = ResetSlider(50)
        self.protect_slider = ResetSlider(40)
        self.oiii_val = QLabel()
        self.blend_val = QLabel()
        self.protect_val = QLabel()
        self.sat_val = QLabel()
        self.bright_val = QLabel()
        self.lightness_check = QCheckBox("Preserve lightness (keep tonal structure)")
        self.lightness_check.setChecked(False)   # off = brighter combine; the better default
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(_DEBOUNCE_MS)
        self._render_timer.timeout.connect(self._do_render)
        self.palette_box.currentTextChanged.connect(lambda _t: self._schedule_render())
        for s in (self.blend_slider, self.oiii_slider, self.sat_slider,
                  self.bright_slider, self.protect_slider):
            s.valueChanged.connect(lambda _v: self._on_slider_change())
        self.lightness_check.toggled.connect(lambda _v: self._schedule_render())

        def _row(slider, value_label):
            value_label.setMinimumWidth(48)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            box = QHBoxLayout()
            box.setContentsMargins(0, 0, 0, 0)
            box.addWidget(slider, 1)
            box.addWidget(value_label)
            wrap = QWidget()
            wrap.setLayout(box)
            return wrap

        controls = QFormLayout()
        controls.addRow("Palette", self.palette_box)
        controls.addRow("OIII boost", _row(self.oiii_slider, self.oiii_val))
        controls.addRow("Green blend", _row(self.blend_slider, self.blend_val))
        controls.addRow("Protect background", _row(self.protect_slider, self.protect_val))
        controls.addRow("Saturation", _row(self.sat_slider, self.sat_val))
        controls.addRow("Brightness", _row(self.bright_slider, self.bright_val))
        controls.addRow("", self.lightness_check)
        controls.addRow("", self.reset_btn)
        self._update_value_labels()

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self.apply)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.apply_btn)
        buttons.addWidget(close_btn)

        side = QVBoxLayout()
        side.addLayout(controls)
        side.addStretch(1)
        side.addWidget(self.status)
        side.addLayout(buttons)
        side_wrap = QWidget()
        side_wrap.setLayout(side)
        side_wrap.setMaximumWidth(340)

        body = QHBoxLayout(self)
        body.addWidget(self.preview, 1)
        body.addWidget(side_wrap)

    def _default_starx(self, img: AstroImage):
        rc = RCAstro(resolve_binary(self._settings.rcastro_path))
        return rc.remove_stars(img)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._started:
            return
        self._started = True
        if self._starless is not None:
            self._on_starless((self._starless, self._stars))
            return
        if not rcastro_valid(self._settings):
            self.status.setText("StarX not configured — narrowband applied to the whole "
                                "image (star colour may look off).")
            self._on_starless((self._base, None))
            return
        self.preview.show_message("Removing stars…\n(one-time, then tweak live)")
        self.apply_btn.setEnabled(False)
        run_async(self._pool, lambda: self._starx_runner(self._base),
                  self._on_starless, self._on_error)

    def _on_starless(self, layers) -> None:
        self._starless, self._stars = layers
        self._prev_starless = _downscale(self._starless)
        self.apply_btn.setEnabled(True)
        self._do_render()

    def _on_error(self, exc) -> None:
        self.status.setText(f"Star removal failed: {exc} — using the whole image.")
        self._on_starless((self._base, None))

    def reset(self) -> None:
        self.palette_box.setCurrentIndex(0)
        self.blend_slider.setValue(60)
        self.oiii_slider.setValue(50)
        self.sat_slider.setValue(50)
        self.bright_slider.setValue(50)
        self.protect_slider.setValue(40)
        self.lightness_check.setChecked(False)
        self._update_value_labels()
        self._do_render()

    def _on_slider_change(self) -> None:
        self._update_value_labels()
        self._schedule_render()

    def _update_value_labels(self) -> None:
        """Show each slider's mapped value. OIII boost / Brightness read as a
        multiplier (×1.33) to match the numbers a tutorial or PixInsight uses."""
        self.oiii_val.setText(f"×{max(0.3, self.oiii_slider.value() / 50.0):.2f}")
        self.bright_val.setText(f"×{max(0.3, self.bright_slider.value() / 50.0):.2f}")
        self.blend_val.setText(f"{self.blend_slider.value() / 100.0:.2f}")
        self.sat_val.setText(f"{self.sat_slider.value() / 100.0:.2f}")
        self.protect_val.setText(f"{self.protect_slider.value()}%")

    def _params(self) -> NarrowbandParams:
        return NarrowbandParams(
            palette=self.palette_box.currentText(),
            blend_amount=self.blend_slider.value() / 100.0,
            oiii_boost=max(0.3, self.oiii_slider.value() / 50.0),
            saturation=self.sat_slider.value() / 100.0,
            brightness=max(0.3, self.bright_slider.value() / 50.0),
            protect_background=self.protect_slider.value() / 100.0,
            lightness_preserve=self.lightness_check.isChecked(),
        )

    def _schedule_render(self) -> None:
        if self._prev_starless is not None:
            self._render_timer.start()

    def _do_render(self) -> None:
        if self._prev_starless is None:
            return
        try:
            self._last = render(self._prev_starless, self._params())
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.preview.show_image(to_qimage(self._last))
        if not self._fitted:
            self._fitted = True
            self.preview.view.fit()

    def preview_result(self) -> AstroImage:
        return self._last

    def apply(self) -> None:
        if self._starless is None:
            self.status.setText("Still removing stars…")
            return
        params = self._params()
        nebula = render(self._starless, params)
        if self._stars is None:
            result = nebula
        else:
            out = screen(nebula.data, np.clip(self._stars.data, 0.0, 1.0))
            result = AstroImage(out, is_linear=False, metadata=dict(self._starless.metadata))
        if self._on_apply is not None:
            self._on_apply(result, params)
        self.accept()
