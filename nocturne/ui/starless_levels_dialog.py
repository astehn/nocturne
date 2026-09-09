"""Set black and white points on the starless layer of a star split.

The split is done by the caller (it is slow and runs off the UI thread), so this
dialog receives both layers and only chooses the two numbers. `compose()` is the
ONE path used for both the preview and the committed result, so what is on
screen is what Apply produces.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout, QWidget)

from ..core.enhance import starless_levels_layers
from ..core.image import AstroImage
from ..core.inspect import clip_overlay
from .curves_dialog import (_downscale, _fit_to_screen, _fitted_size,
                           _pixmap_for, _ZoomPreview)
from .preview import rgb_to_qimage, to_rgb8
from .reset_slider import ResetSlider

_SCALE = 1000          # QSlider is integer-only; 0..1000 represents 0.0..1.0
_PREFERRED = (1100, 720)

# One slider step. `apply_levels` clamps a crossed pair to `white = black + 1e-4`,
# so a single step (0.001) is comfortably clear of the point where the two would
# be describing something the labels do not say.
_MIN_GAP = 1


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

        # ResetSlider, as step_panels, star_spikes, narrowband and colour
        # balance all use: double-click returns it to the identity endpoint, so
        # there is a way back to exactly (0.0, 1.0) to compare against the
        # untouched image. A plain QSlider has none.
        self.black_slider = ResetSlider(0, minimum=0, maximum=_SCALE)
        self.white_slider = ResetSlider(_SCALE, minimum=0, maximum=_SCALE)
        self.black_val = QLabel("0.000")
        self.white_val = QLabel("1.000")

        self.clip_check = QCheckBox("Show Clipping")
        self.clip_check.setChecked(False)
        # Word for word the main window's own Show clipping tooltip. One
        # legend: a mark must not mean two different things in two places.
        self.clip_check.setToolTip(
            "The mark's colour is the channel that died:\n"
            "  red / green / blue — that one channel is at zero\n"
            "  yellow / magenta / cyan — those two are\n"
            "  white — all three, so the pixel really is black\n"
            "Amber marks a channel blown to white instead.\n"
            "Drag until the first specks appear, then back off.")

        self.preview_label = _ZoomPreview()

        # Scroll to zoom, drag to pan — plus explicit buttons, the same set
        # CurvesDialog carries over the same widget and for the same reason: a
        # trackpad gesture is not discoverable, and a large mosaic is unusable
        # without one. Sharper here than there, because zooming CHANGES WHAT
        # THE MASK COVERS (whole frame at fit, visible region beyond it) — so a
        # user who scroll-zoomed by accident silently lost the whole-frame clip
        # mask and had no way back to Fit.
        self.zoom_label = QLabel("1.0x")
        self.fit_btn = QPushButton("Fit")
        self.fit_btn.clicked.connect(self.preview_label.reset_view)
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.clicked.connect(
            lambda: self.preview_label.set_zoom(self.preview_label.zoom_level() * 1.5))
        self.zoom_out_btn = QPushButton("−")
        self.zoom_out_btn.clicked.connect(
            lambda: self.preview_label.set_zoom(self.preview_label.zoom_level() / 1.5))
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel("Preview"))
        zoom_row.addStretch(1)
        zoom_row.addWidget(self.zoom_label)
        zoom_row.addWidget(self.zoom_out_btn)
        zoom_row.addWidget(self.zoom_in_btn)
        zoom_row.addWidget(self.fit_btn)

        note = QLabel("Pull the endpoints in to where the data begins. The stars "
                      "are held aside and screened back untouched, so the white "
                      "point cannot clip a star core.")
        note.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)

        side = QVBoxLayout()
        side.addWidget(note)
        for label, slider, val in (("Black point", self.black_slider, self.black_val),
                                   ("White point", self.white_slider, self.white_val)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(slider, 1)
            row.addWidget(val)
            side.addLayout(row)
        side.addWidget(self.clip_check)
        side.addLayout(zoom_row)
        side.addWidget(QLabel("Scroll to zoom · drag to pan"))
        side.addStretch(1)
        side.addWidget(buttons)

        side_wrap = QWidget()
        side_wrap.setLayout(side)
        # The house pattern — preview left at stretch 1, a vertical control
        # column right, capped at the same 340 star_spikes and narrowband use:
        # "Without it the column takes half the window and the preview is no
        # better off than it was stacked." Star Spikes was moved to this on
        # 2026-09-08 and this dialog had reintroduced the stacked layout it was
        # moved away from.
        side_wrap.setMaximumWidth(340)

        body = QHBoxLayout(self)
        body.addWidget(self.preview_label, 1)
        body.addWidget(side_wrap)

        # Debounced like curves_dialog: a slider drag emits on every tick, and
        # recomposing the full-resolution image on each one stutters. The
        # labels still update immediately — only the (expensive) render waits.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_preview)

        self.black_slider.valueChanged.connect(self._on_black_changed)
        self.white_slider.valueChanged.connect(self._on_white_changed)
        self.clip_check.toggled.connect(self._queue_preview)
        # _ZoomPreview accepts wheel-zoom and drag-pan on its own (see
        # curves_dialog._ZoomPreview) and emits viewChanged either way. Without
        # this connection the widget still tracks the gesture internally but the
        # picture never redraws -- finding the first clipped specks IS this
        # tool's workflow, more than it is CurvesDialog's sanity-check preview,
        # so zoom/pan has to actually feed back into the render here.
        self.preview_label.viewChanged.connect(self._on_view_changed)
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

    def _on_black_changed(self, value: int) -> None:
        if value > self.white_slider.value() - _MIN_GAP:
            # Clamped, not merely tolerated. `apply_levels` silently rescues a
            # crossed pair as `white = black + 1e-4`, which makes the preview a
            # hard threshold while the labels still read "0.800 / 0.200" and the
            # committed params describe an operation that never happened.
            self.black_slider.setValue(self.white_slider.value() - _MIN_GAP)
            return          # the setValue re-enters; that pass does the rest
        self._update_labels()
        self._queue_preview()

    def _on_white_changed(self, value: int) -> None:
        if value < self.black_slider.value() + _MIN_GAP:
            self.white_slider.setValue(self.black_slider.value() + _MIN_GAP)
            return
        self._update_labels()
        self._queue_preview()

    def _queue_preview(self, *_) -> None:
        self._timer.start(60)

    def _on_view_changed(self, *_) -> None:
        # The readout tracks the gesture, the render waits for the debounce —
        # the same split the value labels use. A zoom number that only caught
        # up 60 ms later would lag the thing it is describing.
        self.zoom_label.setText(f"{self.preview_label.zoom_level():.1f}x")
        self._queue_preview()

    def _render_preview(self) -> None:
        """The clipping view REPLACES the picture (as Photoshop's threshold view
        does) rather than tinting it, and its mask comes from the FULL-resolution
        composite: the decimated preview averages a block down, so an isolated
        blown pixel — exactly what dragging the white point is looking for —
        would vanish if the mask were built from the small copy instead.

        Zoomed in, "full resolution" means the native crop under the visible
        rect, not the whole-frame decimated copy — same reasoning as
        CurvesDialog._render, and for the same reason: rendering the whole frame
        at a size fine enough to be useful while zoomed would make dragging
        stutter, so only the on-screen region is ever composed at full detail.

        The two branches are exclusive: the clipping view replaces the picture,
        so the decimated composite it used to build and then throw away is
        simply not made.
        """
        view = self.preview_label
        fit = view.zoom_level() <= 1.0
        if fit:
            full_starless, full_stars = self._starless, self._stars
        else:
            shape = self._starless.data.shape
            x0, y0, x1, y1 = view.visible_rect(shape)
            full_starless = AstroImage(self._starless.data[y0:y1, x0:x1],
                                       is_linear=self._starless.is_linear,
                                       metadata=dict(self._starless.metadata))
            full_stars = AstroImage(self._stars.data[y0:y1, x0:x1],
                                    is_linear=self._stars.is_linear,
                                    metadata=dict(self._stars.metadata))

        if self.clip_check.isChecked():
            view.setPixmap(self._clip_pixmap(full_starless, full_stars))
        else:
            if fit:
                small_starless, small_stars = self._small_starless, self._small_stars
            else:
                edge = max(view.width(), view.height(), 1)
                small_starless = _downscale(full_starless, max_edge=edge)
                small_stars = _downscale(full_stars, max_edge=edge)
            view.setPixmap(_pixmap_for(self.compose(small_starless, small_stars),
                                       view.size()))

    def _clip_pixmap(self, starless: AstroImage, stars: AstroImage) -> QPixmap:
        """The clipping mask, block-maxed straight to the size it is DISPLAYED
        at — no smooth rescale afterwards.

        `clip_overlay` goes to lengths to keep an isolated speck at full
        intensity, and a `SmoothTransformation` to the label then undid it:
        measured, an isolated lit block came out at 195, 111 or 55 depending on
        the factor, so a blown speck could render dimmer than a flat crushed
        background and read as the wrong fault entirely.
        `FastTransformation` is not the alternative — nearest-neighbour on a
        downscale drops the speck outright.

        Enlarging is the one case that still needs Qt, because a block-max can
        only combine pixels, never invent them. There nearest-neighbour is
        exactly right: it makes the lit block bigger at full intensity.
        """
        full = self.compose(starless, stars)
        rgb = to_rgb8(full)                    # the canvas's own conversion
        src_h, src_w = rgb.shape[:2]
        box = _fitted_size(src_w, src_h, self.preview_label.size())
        tw, th = min(src_w, max(1, box.width())), min(src_h, max(1, box.height()))
        pixmap = QPixmap.fromImage(rgb_to_qimage(clip_overlay(rgb, (th, tw))))
        if (tw, th) != (box.width(), box.height()):
            pixmap = pixmap.scaled(self.preview_label.size(),
                                   Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.FastTransformation)
        return pixmap

    def _apply(self) -> None:
        if self._on_apply is not None:
            self._on_apply(self.compose(), self.values())
        self.accept()
