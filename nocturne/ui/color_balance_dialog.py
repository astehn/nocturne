from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from ..core.color_balance import TONES, Balance, apply_balance
from ..core.image import AstroImage
from ..core.mask import BAND_PRESETS, band_preset, range_mask
from ..core.narrowband import screen
from ..settings import rcastro_valid, resolve_binary
from ..tools.rcastro import RCAstro
from .frame_preview import FramePreview
from .preview import to_qimage
from .range_handles import RangeHandles
from .reset_slider import ResetSlider
from .worker import run_async

_PREVIEW_MAX = 640
_DEBOUNCE_MS = 90

# The axis labels, in slider order. Named for both ends so the direction of
# travel is readable without consulting help.
_AXES = (("Cyan — Red", "red"),
         ("Magenta — Green", "green"),
         ("Yellow — Blue", "blue"))


def _downscale(img: AstroImage, max_edge: int = _PREVIEW_MAX) -> AstroImage:
    """Shrink for the live preview by AVERAGING each block, not by sampling one
    pixel out of every N.

    Striding is what NarrowbandDialog does and it is much cheaper, but it
    destroys a star field: measured on 300 synthetic stars decimated 8x, 253
    vanished entirely and the 47 survivors were drawn at full amplitude — the
    hard single-pixel blocks Andreas saw when zooming in. Averaging keeps every
    star and conserves flux exactly, for 273 ms once on a 39.5 Mpx mosaic
    against a star split that already takes seconds.

    It also brings the preview CLOSER to the export: the mask blurs the
    luminance before banding it, so an averaged base has statistics much nearer
    the full-resolution image than a strided one.
    """
    from skimage.transform import downscale_local_mean
    h, w = img.data.shape[:2]
    step = max(1, max(h, w) // max_edge)
    if step == 1:
        return img
    blocks = (step, step, 1) if img.data.ndim == 3 else (step, step)
    small = downscale_local_mean(img.data, blocks).astype(np.float32)
    return AstroImage(np.ascontiguousarray(small),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


class ColorBalanceDialog(QDialog):
    """Shift colour within a luminance band, with the stars left alone.

    Modelled on NarrowbandDialog, which is the same shape: split the stars off
    once on open, let the user work live on the starless layer, and screen the
    untouched stars back on Apply. That is what Andreas does by hand in
    Photoshop, so it is the default here rather than a control.

    `compose()` is the ONE path used by both the preview and Apply. They differ
    only in which image goes in — the preview gets a decimated copy — and the
    mask is scale-covariant by construction, so the preview shows what Apply
    will produce.
    """

    def __init__(self, settings, base: AstroImage, parent=None, on_apply=None,
                 starless=None, stars=None, on_split=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Colour Balance")
        self.resize(1100, 760)
        self._settings = settings
        self._base = base
        self._on_apply = on_apply
        self._on_split = on_split   # hand the split back so it can be cached:
                                    # a StarX run per open is the main friction
                                    # in the two-applies workflow
        self._pool = QThreadPool.globalInstance()
        self._starx_runner = self._default_starx
        self._starless = starless
        self._stars = stars
        self._prev_starless = None
        self._prev_stars = None
        self._fitted = False
        self._started = False

        self.preview = FramePreview()
        self.preview.setMinimumSize(460, 460)

        self.tone_box = QComboBox()
        self.tone_box.addItems([t.capitalize() for t in TONES])
        self.tone_box.setCurrentText("Midtones")
        # Each tonal range keeps its OWN three amounts, as Photoshop's Color
        # Balance does — switching the Tone selector must not discard the range
        # you just set. The sliders show one range at a time; this holds them all.
        self._amounts = {t: [0, 0, 0] for t in TONES}
        self._showing = "midtones"

        self.sliders, self.slider_vals = {}, {}
        for _label, key in _AXES:
            self.sliders[key] = ResetSlider(0, minimum=-100, maximum=100)
            self.slider_vals[key] = QLabel("0")

        # Labels stay SHORT. The form's label column leaves roughly 250 px, and a
        # QCheckBox neither wraps nor elides — it simply loses the end of its own
        # text. Detail goes in the tooltip, and the full story in the help.
        self.preserve_check = QCheckBox("Preserve luminosity")
        self.preserve_check.setToolTip(
            "Change colour only — the brightness of every pixel stays exactly as it is")
        self.preserve_check.setChecked(True)
        self.strength_slider = ResetSlider(100)
        self.strength_val = QLabel("100%")

        self.preset_box = QComboBox()
        self.preset_box.addItems(BAND_PRESETS)
        self.handles = RangeHandles()
        self.feather_slider = ResetSlider(8, minimum=0, maximum=30)
        self.feather_val = QLabel("0.08")
        self.invert_check = QCheckBox("Invert the range")
        self.invert_check.setToolTip(
            "Adjust everything OUTSIDE the band instead of inside it — the only way "
            "to say things like \u201ceverything except the galaxy\u201d")
        self.show_mask_check = QCheckBox("Show the mask")
        self.show_mask_check.setToolTip(
            "Light the parts of the picture the adjustment will reach, and dim the "
            "rest — so you can see WHERE it lands, not just how strong it is")

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(_DEBOUNCE_MS)
        self._render_timer.timeout.connect(self._do_render)

        self.tone_box.currentTextChanged.connect(self._on_tone_change)
        for s in self.sliders.values():
            s.valueChanged.connect(lambda _v: self._on_slider_change())
        self.strength_slider.valueChanged.connect(lambda _v: self._on_slider_change())
        self.feather_slider.valueChanged.connect(lambda _v: self._on_slider_change())
        self.preserve_check.toggled.connect(lambda _v: self._schedule_render())
        self.invert_check.toggled.connect(lambda _v: self._do_render())
        self.show_mask_check.toggled.connect(lambda _v: self._do_render())
        self.preset_box.currentTextChanged.connect(self._on_preset)
        self.handles.rangeChanged.connect(lambda _lo, _hi: self._on_slider_change())

        def _row(widget, value_label):
            value_label.setMinimumWidth(48)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight
                                     | Qt.AlignmentFlag.AlignVCenter)
            box = QHBoxLayout()
            box.setContentsMargins(0, 0, 0, 0)
            box.addWidget(widget, 1)
            box.addWidget(value_label)
            wrap = QWidget()
            wrap.setLayout(box)
            return wrap

        controls = QFormLayout()
        blurb = QLabel("Shift the colour of one tonal range. Show the mask lights the "
                       "areas that will change and dims the rest; the stars are never "
                       "altered.")
        blurb.setWordWrap(True)          # without this it clips, or forces the
        controls.addRow(blurb)           # panel past its width cap
        controls.addRow("Tone", self.tone_box)
        for label, key in _AXES:
            controls.addRow(label, _row(self.sliders[key], self.slider_vals[key]))
        controls.addRow("", self.preserve_check)
        controls.addRow("Strength", _row(self.strength_slider, self.strength_val))
        controls.addRow(QLabel("—  Limit to  —"))
        controls.addRow("Range", self.preset_box)
        controls.addRow("", self.handles)
        controls.addRow("Feather", _row(self.feather_slider, self.feather_val))
        controls.addRow("", self.invert_check)
        controls.addRow("", self.show_mask_check)
        controls.addRow("", self.reset_btn)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self._apply)
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
        side_wrap.setMaximumWidth(380)

        body = QHBoxLayout(self)
        body.addWidget(self.preview, 1)
        body.addWidget(side_wrap)
        self._update_value_labels()

    # --- star split, exactly as NarrowbandDialog does it -------------------
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
            self.status.setText("StarX not configured — the whole image is adjusted, "
                                "so star colour shifts with the rest.")
            self._on_starless((self._base, None))
            return
        self.preview.show_message("Removing stars…\n(one-time, then tweak live)")
        self.apply_btn.setEnabled(False)
        run_async(self._pool, lambda: self._starx_runner(self._base),
                  self._on_starless, self._on_error)

    def _on_starless(self, layers) -> None:
        self._starless, self._stars = layers
        if self._on_split is not None and self._stars is not None:
            self._on_split(self._starless, self._stars)
        self._prev_starless = _downscale(self._starless)
        self._prev_stars = None if self._stars is None else _downscale(self._stars)
        self.handles.set_histogram(self._prev_starless.data)
        self._on_preset(self.preset_box.currentText())   # seed the band from the image
        self.apply_btn.setEnabled(True)
        self._do_render()

    def _on_error(self, exc) -> None:
        self.status.setText(f"Star removal failed: {exc} — using the whole image.")
        self._on_starless((self._base, None))

    # --- model ------------------------------------------------------------
    def _capture_visible_tone(self) -> None:
        """Store the sliders into whichever range they are currently showing."""
        self._amounts[self._showing] = [self.sliders[k].value()
                                        for k in ("red", "green", "blue")]

    def _on_tone_change(self, text: str) -> None:
        # No capture here: _on_slider_change stores every edit as it happens and
        # balance() captures again when it reads, so a third call did nothing —
        # removing it changed no test, which is how it was found.
        self._showing = text.lower()
        for key, value in zip(("red", "green", "blue"), self._amounts[self._showing]):
            slider = self.sliders[key]
            # Blocked to avoid three spurious re-renders, not for correctness:
            # _showing is already the new range, so an unblocked load would just
            # re-capture the values it had that instant put there.
            was = slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(was)
        self._update_value_labels()
        self._schedule_render()

    def balance(self) -> Balance:
        self._capture_visible_tone()
        return Balance(
            **{t: tuple(v / 100.0 for v in self._amounts[t]) for t in TONES},
            preserve_lum=self.preserve_check.isChecked(),
            strength=self.strength_slider.value() / 100.0,
        )

    def band(self) -> tuple[float, float, float]:
        lo, hi = self.handles.range()
        return (lo, hi, self.feather_slider.value() / 100.0)

    def options(self) -> dict:
        b = self.balance()
        lo, hi, feather = self.band()
        return {"shadows": list(b.shadows), "midtones": list(b.midtones),
                "highlights": list(b.highlights),
                "preserve_lum": b.preserve_lum, "strength": b.strength,
                "lo": lo, "hi": hi, "feather": feather,
                "invert": self.invert_check.isChecked()}

    def set_balance_for_test(self, **kw) -> None:
        """Drive the real controls from keyword arguments, so tests exercise the
        widgets rather than a private field that Apply might not read."""
        if "tone" in kw:
            self.tone_box.setCurrentText(str(kw["tone"]).capitalize())
        for key in ("red", "green", "blue"):
            if key in kw:
                self.sliders[key].setValue(int(round(kw[key] * 100)))
        self._capture_visible_tone()
        if "preserve_lum" in kw:
            self.preserve_check.setChecked(bool(kw["preserve_lum"]))
        if "strength" in kw:
            self.strength_slider.setValue(int(round(kw["strength"] * 100)))

    def _on_preset(self, name: str) -> None:
        """A preset SETS the handles; it does not lock them. Bounds come from the
        image's own statistics — fixed numbers cannot work, because a stretched
        sky sits wherever the stretch put it."""
        src = self._prev_starless if self._prev_starless is not None else None
        if src is None:
            return
        lum = src.data.mean(axis=2) if src.data.ndim == 3 else src.data
        self.handles.set_range(*band_preset(lum, name))
        self._schedule_render()

    def reset(self) -> None:
        # Zero the sliders BEFORE switching tone. Switching captures whatever the
        # sliders currently show into the range being left, so clearing the store
        # first and switching second wrote the stale values straight back in.
        for s in self.sliders.values():
            s.setValue(0)
        self._amounts = {t: [0, 0, 0] for t in TONES}   # every range, not just the visible one
        was = self.tone_box.blockSignals(True)
        self.tone_box.setCurrentText("Midtones")
        self.tone_box.blockSignals(was)
        self._showing = "midtones"
        self.preserve_check.setChecked(True)
        self.strength_slider.setValue(100)
        self.feather_slider.setValue(8)
        self.invert_check.setChecked(False)
        self.show_mask_check.setChecked(False)
        self.preset_box.setCurrentIndex(0)
        self._on_preset(self.preset_box.currentText())
        self._update_value_labels()
        self._do_render()

    # --- rendering --------------------------------------------------------
    def _on_slider_change(self) -> None:
        self._capture_visible_tone()
        self._update_value_labels()
        self._schedule_render()

    def _update_value_labels(self) -> None:
        for _label, key in _AXES:
            self.slider_vals[key].setText(f"{self.sliders[key].value():+d}")
        self.strength_val.setText(f"{self.strength_slider.value()}%")
        self.feather_val.setText(f"{self.feather_slider.value() / 100.0:.2f}")

    def _schedule_render(self) -> None:
        if self._prev_starless is not None:
            self._render_timer.start()

    def mask_for(self, img: AstroImage) -> np.ndarray:
        """The band, or its complement when inverted.

        Inverting is not reachable any other way: the two handles can only
        describe ONE contiguous range, so "everything except the object" has no
        expression without this.
        """
        lo, hi, feather = self.band()
        lum = img.data.mean(axis=2) if img.data.ndim == 3 else img.data
        m = range_mask(lum, lo, hi, feather=feather)
        return (1.0 - m).astype(np.float32) if self.invert_check.isChecked() else m

    def compose(self, starless: AstroImage | None = None,
                stars: AstroImage | None = None) -> AstroImage:
        """Adjust the starless layer within the band and screen the stars back.

        The single path for both preview and Apply. `stars` is never modified —
        it is screened on top exactly as it arrived.
        """
        base = self._starless if starless is None else starless
        st = self._stars if starless is None else stars
        adjusted = apply_balance(base, self.balance(), self.mask_for(base))
        if st is None:
            return adjusted
        out = screen(adjusted.data, np.clip(st.data, 0.0, 1.0))
        return AstroImage(out, is_linear=base.is_linear, metadata=dict(base.metadata))

    # How far the unselected areas are dimmed when the mask is shown. Low enough
    # that the boundary is unmistakable, high enough that they stay legible as
    # the picture rather than going flat black.
    _UNSELECTED_DIM = 0.30

    def preview_image(self) -> AstroImage:
        src = self._prev_starless if self._prev_starless is not None else self._starless
        shown = self.compose(src, self._prev_stars)
        if not self.show_mask_check.isChecked():
            return shown

        # Light the selection IN THE PICTURE rather than showing a bare greyscale
        # mask. The mask alone shows its shape but not which parts of your own
        # image it covers, which is the question actually being asked. Dimming and
        # desaturating rather than tinting: an astro frame is already full of red,
        # so a coloured wash invents something that can be mistaken for signal.
        data = shown.data
        m = self.mask_for(src)[:, :, None]
        grey = data.mean(axis=2, keepdims=True)
        out = data * m + grey * self._UNSELECTED_DIM * (1.0 - m)
        return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                          is_linear=shown.is_linear, metadata=dict(shown.metadata))

    def _do_render(self) -> None:
        if self._prev_starless is None:
            return
        try:
            shown = self.preview_image()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.preview.show_image(to_qimage(shown))
        if not self._fitted:
            self._fitted = True
            self.preview.view.fit()

    def _apply(self) -> None:
        """Compose at full resolution OFF the UI thread.

        Measured on the 39.5 Mpx M 31 mosaic: 3.4 s with a real mask, 7.8 s with
        the whole frame selected. Run on the UI thread that is a window frozen
        with no feedback, which in this app is indistinguishable from the hang
        that once cost a whole session.
        """
        if self._starless is None:
            self.status.setText("Still removing stars…")
            return
        self.apply_btn.setEnabled(False)
        self.status.setText("Applying at full resolution…")
        run_async(self._pool, self.compose, self._on_composed, self._on_compose_error)

    def _on_composed(self, result: AstroImage) -> None:
        if self._on_apply is not None:
            self._on_apply(result, self.options())
        self.accept()

    def _on_compose_error(self, exc) -> None:
        self.apply_btn.setEnabled(True)
        self.status.setText(f"Could not apply: {exc}")
