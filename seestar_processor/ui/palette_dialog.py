from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QVBoxLayout, QWidget,
)

from ..core.image import AstroImage
from ..core.palette import PaletteParams, compose, render_nebula
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
    def __init__(self, settings, base: AstroImage, parent=None, on_apply=None,
                 starless=None, stars=None) -> None:
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
        self._starless = starless
        self._stars = stars
        self._seeded = starless is not None
        self._prev_starless = None
        self._prev_stars = None

        self.preview = QLabel("Removing stars…")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(480, 360)

        self.foraxx_radio = QRadioButton("Foraxx (dynamic)")
        self.hoo_radio = QRadioButton("HOO")
        self.sho_radio = QRadioButton("Pseudo-SHO (no real SII)")
        self.foraxx_radio.setChecked(True)

        self.ha_slider = ResetSlider(60)
        self.oiii_slider = ResetSlider(70)
        self.hue_slider = ResetSlider(50)
        self.sat_slider = ResetSlider(65)

        self.scnr_check = QCheckBox("Green suppression (SCNR)")
        self.scnr_check.setChecked(True)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset)
        self.hint = QLabel(
            "" if self._base.is_linear else
            "Palette works best on the linear master — run it before the Stretch step.")
        self.hint.setWordWrap(True)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        for r in (self.foraxx_radio, self.hoo_radio, self.sho_radio):
            r.toggled.connect(self._render_preview)
        for s in (self.ha_slider, self.oiii_slider, self.hue_slider, self.sat_slider):
            s.valueChanged.connect(lambda _v: self._render_preview())
        self.scnr_check.toggled.connect(self._render_preview)

        controls = QFormLayout()
        pal = QHBoxLayout()
        pal.addWidget(self.foraxx_radio)
        pal.addWidget(self.hoo_radio)
        pal.addWidget(self.sho_radio)
        pal_wrap = QWidget()
        pal_wrap.setLayout(pal)
        controls.addRow("Palette", pal_wrap)
        controls.addRow("Ha stretch", self.ha_slider)
        controls.addRow("OIII stretch", self.oiii_slider)
        controls.addRow("Hue", self.hue_slider)
        controls.addRow("Saturation", self.sat_slider)
        controls.addRow("", self.scnr_check)
        controls.addRow("", self.reset_btn)
        controls.addRow("", self.hint)

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

    # --- StarX ---
    def _default_starx(self, img: AstroImage):
        rc = RCAstro(resolve_binary(self._settings.rcastro_path))
        return rc.remove_stars(img)

    def start(self) -> None:
        if self._seeded:                          # seeded with pre-computed layers
            self._cache_previews()
            self._render_preview()
            return
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

    def reset(self) -> None:
        self.foraxx_radio.setChecked(True)
        self.ha_slider.setValue(60)
        self.oiii_slider.setValue(70)
        self.hue_slider.setValue(50)
        self.sat_slider.setValue(65)
        self.scnr_check.setChecked(True)
        self._render_preview()

    def _params(self) -> PaletteParams:
        if self.hoo_radio.isChecked():
            palette = "HOO"
        elif self.sho_radio.isChecked():
            palette = "pseudo_SHO"
        else:
            palette = "Foraxx"
        return PaletteParams(
            palette=palette,
            ha_stretch=self.ha_slider.value() / 100.0,
            oiii_stretch=self.oiii_slider.value() / 100.0,
            hue_deg=(self.hue_slider.value() - 50) / 50.0 * 30.0,
            saturation=self.sat_slider.value() / 100.0,
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
