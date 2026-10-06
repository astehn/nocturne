from __future__ import annotations

import numpy as np
import shiboken6
from PySide6.QtCore import QThreadPool, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..core.image import AstroImage
from ..core.star_spikes import _COLOUR_MAX_BOOST, _MAX_STARS, add_spikes, detect_stars
from .busy_gate import BusyGate, keep_live
from .frame_preview import FramePreview
from .preview import rgb_to_qimage, to_qimage
from .preview_runner import PreviewRunner
from .reset_slider import ResetSlider
from .worker import run_async
from .help_link import HelpLink


def _render(base: AstroImage, stars, params) -> tuple:
    """The spikes and their 8-bit picture, for one slider position. A pure
    function of its arguments, so the pool can run it: drawing 50 spikes on
    the 33 MP M 8 drizzle held the window 0.28 s per tick (2026-10-06)."""
    length, count, angle, intensity, variation, colour = params
    result = add_spikes(base, stars, length, count, angle, intensity, variation, colour)
    data = np.clip(result.data, 0.0, 1.0)
    if data.ndim == 2:
        rgb = np.repeat((data * 255 + 0.5).astype(np.uint8)[:, :, None], 3, axis=2)
    else:
        rgb = (data * 255 + 0.5).astype(np.uint8)
    return result, np.ascontiguousarray(rgb)


class StarSpikesDialog(QDialog):
    """Artistic tool: draw diffraction spikes on the brightest stars of the
    current (display-space) image, with a live preview. Detection runs once on
    open; the three sliders then re-render instantly. Apply hands the rendered
    AstroImage back via `on_apply`."""

    def __init__(self, base: AstroImage, parent=None, on_apply=None, *,
                 is_async=None) -> None:
        """`is_async()` False renders and applies inline — the tests' setting,
        and MainWindow's when its own `_async_enabled` is off."""
        super().__init__(parent)
        self.setWindowTitle("Star Spikes")
        # Side-by-side like every other preview dialog, so these are the
        # family's proportions rather than this one's own.
        self.setMinimumSize(760, 540)
        self.resize(1080, 700)
        self._base = base
        self._on_apply = on_apply
        self._result = base
        self._pool = QThreadPool.globalInstance()
        self._stars = None                 # None = still looking; [] = none found
        self._is_async = is_async if is_async is not None else (lambda: False)
        self._runner = PreviewRunner(self, pool=self._pool, is_async=self._is_async)
        self._shown_params = None          # the slider values self._result was drawn at
        self._gate = BusyGate()
        self._applying = False
        self._closed = False

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
        self._timer.timeout.connect(self._queue_render)
        for s in (self.length_slider, self.intensity_slider,
                  self.stars_slider, self.angle_slider,
                  self.variation_slider, self.colour_slider):
            s.valueChanged.connect(self._on_change)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self._apply)
        close_btn = keep_live(QPushButton("Close"))
        close_btn.clicked.connect(self.reject)

        def _row(label, widget, val):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(val)
            outer = QVBoxLayout()
            outer.addLayout(row)
            outer.addWidget(widget)
            return outer

        # Preview LEFT, controls RIGHT — the shape Curves, Narrowband, Share,
        # Upscale, Stack and Colour Balance all use. This dialog was the only
        # one stacked vertically, and Andreas named the cost (2026-09-06):
        # "thats a poor usage of screen realestate". Stacked, the preview got a
        # letterbox strip of the height while six slider tracks ran the full
        # width of the window to carry a control that needs about 200px.
        note = QLabel("Add diffraction spikes to the brightest stars. Length 0 = off. "
                      "Keep the star count low so it looks intentional.")
        note.setWordWrap(True)

        side = QVBoxLayout()
        side.addWidget(note)
        side.addLayout(_row("Length (off → long)", self.length_slider, self.length_val))
        side.addLayout(_row("Intensity (faint → full)", self.intensity_slider, self.intensity_val))
        side.addLayout(_row("Number of stars", self.stars_slider, self.stars_val))
        side.addLayout(_row("Rotation", self.angle_slider, self.angle_val))
        side.addLayout(_row("Variation (uniform → varied)",
                            self.variation_slider, self.variation_val))
        side.addLayout(_row("Star colour (white → full)",
                            self.colour_slider, self.colour_val))
        side.addWidget(self.compare_check)
        side.addStretch(1)
        self.help_link = HelpLink("star_spikes", self)
        side.addWidget(self.help_link, 0, Qt.AlignmentFlag.AlignRight)
        buttons = QHBoxLayout()
        buttons.addWidget(self.reset_btn)
        buttons.addWidget(self.apply_btn)
        buttons.addWidget(close_btn)
        side.addLayout(buttons)

        side_wrap = QWidget()
        side_wrap.setLayout(side)
        self._side = side_wrap
        # The same cap narrowband_dialog uses. Without it the column takes half
        # the window and the preview is no better off than it was stacked.
        side_wrap.setMaximumWidth(340)

        body = QHBoxLayout(self)
        body.addWidget(self.preview, 1)
        body.addWidget(side_wrap)

        # Detection off the UI thread. It ran in __init__ and cost 0.28 s on an
        # 8.3 MP frame, about 1.3 s on a 39.5 MP master, with a frozen window and
        # nothing on screen saying why.
        self._set_controls_enabled(False)
        self.apply_btn.setEnabled(False)
        self.preview.show_waiting("Finding stars…")
        data = base.data            # the job holds the pixels, never the dialog
        run_async(self._pool, lambda: detect_stars(data),
                  lambda stars: self._alive() and self._on_stars(stars),
                  lambda exc: self._alive() and self._on_detect_error(exc))

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

    def _alive(self) -> bool:
        """A job's landing outlives the dialog: closed, nothing it brings
        may paint, enable or apply."""
        return not self._closed and shiboken6.isValid(self)

    def done(self, r: int) -> None:
        self._closed = True
        self._timer.stop()
        self._runner.cancel()
        super().done(r)

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
        self._queue_render()        # the first picture, off the UI thread like every tick

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

    def _queue_render(self) -> None:
        """The debounce timer's target: the render goes to the pool, and only
        the newest slider position is ever painted (PreviewRunner)."""
        if not self._stars or self._applying:
            return
        params, base, stars = self._params(), self._base, self._stars
        self._runner.request(params, lambda: _render(base, stars, params),
                             lambda out: self._show(params, out))

    def _show(self, params, out) -> None:
        result, rgb = out
        self._result, self._shown_params = result, params
        self.preview.show_image(rgb_to_qimage(rgb))

    def _render_preview(self) -> None:
        """Render NOW, inline — what a caller that reads `result()` on the next
        line needs. The sliders' own route is `_queue_render`."""
        if not self._stars:
            return
        self._runner.cancel()           # nothing older may land over this one
        params = self._params()
        self._show(params, _render(self._base, self._stars, params))

    def result(self) -> AstroImage:
        return self._result

    def _apply(self) -> None:
        """The sliders' values at the press are what is applied — never a
        preview still being drawn for an older position. When the picture on
        screen already is that position it is handed over as it is; otherwise
        it is drawn on the pool while the window waits, dimmed, with Close
        live."""
        if self._applying or not self._stars:
            return
        params = self._params()
        self._timer.stop()
        self._runner.cancel()
        if self._shown_params == params:
            self._deliver(self._result, params)
            return
        if not self._is_async():
            self._render_preview()
            self._deliver(self._result, params)
            return
        self._applying = True
        self._gate.close(self._side)
        self.preview.show_waiting("Applying…")
        base, stars = self._base, self._stars

        def failed(exc) -> None:
            if not self._alive():
                return
            self._applying = False
            self._gate.open()
            self.preview._end_wait()
            self.preview.show_message(f"Could not apply: {exc}")

        run_async(self._pool, lambda: _render(base, stars, params)[0],
                  lambda result: self._alive() and self._deliver(result, params),
                  failed)

    def _deliver(self, result: AstroImage, params) -> None:
        self._result = result
        if self._on_apply is not None:
            # The params go with the picture. Star Spikes recorded `""` until
            # 2026-09-17, so its six sliders left no trace anywhere — the
            # provenance report said "Star Spikes" and stopped. The same tuple
            # the picture was drawn at, so the record cannot describe a
            # different image than the one applied.
            self._on_apply(result, self._named(params))
        self.accept()

    def params_dict(self) -> dict:
        """_params() by name, for the history entry. Named rather than the bare
        tuple because a reader of the report has to know which 0.35 is which."""
        return self._named(self._params())

    @staticmethod
    def _named(params) -> dict:
        length, count, angle, intensity, variation, colour = params
        return {"length": round(length, 3), "count": int(count),
                "angle": angle, "intensity": round(intensity, 3),
                "variation": round(variation, 3), "colour": round(colour, 3)}
