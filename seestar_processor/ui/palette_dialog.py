from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QVBoxLayout, QWidget,
)

from ..core.image import AstroImage
from ..core.palette import ChannelCurve, PaletteParams, compose, render_nebula
from ..settings import rcastro_valid, resolve_binary
from ..tools.rcastro import RCAstro
from .preview import to_qimage
from .reset_slider import ResetSlider
from .worker import run_async

_PREVIEW_MAX = 700  # long-side pixels for the interactive preview


def _downscale(img: AstroImage) -> AstroImage:
    h, w = img.data.shape[:2]
    step = max(1, max(h, w) // _PREVIEW_MAX)
    return AstroImage(np.ascontiguousarray(img.data[::step, ::step]),
                      is_linear=img.is_linear)


class PaletteDialog(QDialog):
    def __init__(self, settings, base: AstroImage, parent=None, on_apply=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Narrowband palette")
        self.setMinimumWidth(720)
        self._settings = settings
        self._base = base
        self._on_apply = on_apply
        self._pool = QThreadPool.globalInstance()
        self._async = True
        self._starx_enabled = rcastro_valid(settings)
        self._starx_runner = self._default_starx
        self._starless = None
        self._stars = None
        self._prev_starless = None
        self._prev_stars = None

        self.preview = QLabel("Removing stars…")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(480, 360)

        self.hoo_radio = QRadioButton("HOO")
        self.sho_radio = QRadioButton("Pseudo-SHO (no real SII)")
        self.hoo_radio.setChecked(True)

        # per-channel curve state; sliders edit the active channel
        self._curves = {"R": ChannelCurve(), "G": ChannelCurve(), "B": ChannelCurve()}
        self._active_channel = "R"
        self.r_radio = QRadioButton("R")
        self.g_radio = QRadioButton("G")
        self.b_radio = QRadioButton("B")
        self.r_radio.setChecked(True)

        self.black_slider = self._slider(0)
        self.mid_slider = self._slider(50)
        self.white_slider = self._slider(100)

        self.scnr_check = QCheckBox("Green suppression (SCNR)")
        self.scnr_check.setChecked(True)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        for w in (self.hoo_radio, self.sho_radio):
            w.toggled.connect(self._render_preview)
        self.r_radio.toggled.connect(lambda on: on and self._select_channel("R"))
        self.g_radio.toggled.connect(lambda on: on and self._select_channel("G"))
        self.b_radio.toggled.connect(lambda on: on and self._select_channel("B"))
        for s in (self.black_slider, self.mid_slider, self.white_slider):
            s.valueChanged.connect(self._on_slider)
        self.scnr_check.toggled.connect(self._render_preview)

        controls = QFormLayout()
        pal = QHBoxLayout()
        pal.addWidget(self.hoo_radio)
        pal.addWidget(self.sho_radio)
        pal_wrap = QWidget()
        pal_wrap.setLayout(pal)
        controls.addRow("Palette", pal_wrap)
        chan = QHBoxLayout()
        chan.addWidget(self.r_radio)
        chan.addWidget(self.g_radio)
        chan.addWidget(self.b_radio)
        chan_wrap = QWidget()
        chan_wrap.setLayout(chan)
        controls.addRow("Channel", chan_wrap)
        controls.addRow("Black", self.black_slider)
        controls.addRow("Mid", self.mid_slider)
        controls.addRow("White", self.white_slider)
        controls.addRow("", self.scnr_check)
        controls.addRow("", self.reset_btn)

        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self.apply)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(apply_btn)
        buttons.addWidget(close_btn)

        body = QHBoxLayout()
        body.addWidget(self.preview, 2)
        side = QVBoxLayout()
        side.addLayout(controls)
        side.addStretch(1)
        side.addWidget(self.status)
        side.addLayout(buttons)
        side_wrap = QWidget()
        side_wrap.setLayout(side)
        body.addWidget(side_wrap, 1)

        root = QVBoxLayout(self)
        root.addLayout(body)

        self.start()

    # --- slider factory ---
    def _slider(self, default: int) -> ResetSlider:
        return ResetSlider(default)

    # --- StarX ---
    def _default_starx(self, img: AstroImage):
        rc = RCAstro(resolve_binary(self._settings.rcastro_path))
        return rc.remove_stars(img)

    def start(self) -> None:
        if not self._starx_enabled:
            self._starless = self._base
            self._stars = None
            self.status.setText("StarX not configured — palette applied to the whole image.")
            self._cache_previews()
            self._render_preview()
            return
        self.status.setText("Removing stars…")
        if self._async:
            run_async(self._pool, lambda: self._starx_runner(self._base),
                      self._on_starless, self._on_error)
        else:
            try:
                self._on_starless(self._starx_runner(self._base))
            except Exception as exc:  # noqa: BLE001
                self._on_error(exc)

    def _on_starless(self, layers) -> None:
        self._starless, self._stars = layers
        self.status.setText("")
        self._cache_previews()
        self._render_preview()

    def _on_error(self, exc) -> None:
        self.status.setText(f"Star removal failed: {exc}")

    def _cache_previews(self) -> None:
        self._prev_starless = _downscale(self._starless)
        self._prev_stars = _downscale(self._stars) if self._stars is not None else None

    # --- channel curve controls ---
    def _select_channel(self, name: str) -> None:
        self._active_channel = name
        c = self._curves[name]
        for slider, val in ((self.black_slider, c.black),
                            (self.mid_slider, c.mid), (self.white_slider, c.white)):
            slider.blockSignals(True)
            slider.setValue(round(val * 100))
            slider.blockSignals(False)
        self._render_preview()

    def _on_slider(self, _value: int) -> None:
        self._curves[self._active_channel] = ChannelCurve(
            black=self.black_slider.value() / 100.0,
            mid=self.mid_slider.value() / 100.0,
            white=self.white_slider.value() / 100.0,
        )
        self._render_preview()

    def reset(self) -> None:
        self._curves = {"R": ChannelCurve(), "G": ChannelCurve(), "B": ChannelCurve()}
        self._select_channel(self._active_channel)

    # --- params + render ---
    def _params(self) -> PaletteParams:
        return PaletteParams(
            palette="HOO" if self.hoo_radio.isChecked() else "pseudo_SHO",
            r=self._curves["R"], g=self._curves["G"], b=self._curves["B"],
            scnr=self.scnr_check.isChecked(),
        )

    def _result(self, starless: AstroImage, stars) -> AstroImage:
        params = self._params()
        if stars is not None:
            return compose(starless, stars, params)
        return render_nebula(starless, params)

    def _render_preview(self) -> None:
        if self._prev_starless is None:
            return
        result = self._result(self._prev_starless, self._prev_stars)
        self.preview.setPixmap(QPixmap.fromImage(to_qimage(result)))

    # --- apply ---
    def apply(self) -> None:
        if self._starless is None:
            self.status.setText("Still working…")
            return
        result = self._result(self._starless, self._stars)
        if self._on_apply is not None:
            self._on_apply(result)
        self.accept()
