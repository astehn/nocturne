"""Set black and white points on the starless layer of a star split.

The split is done by the caller (it is slow and runs off the UI thread), so this
dialog receives both layers and only chooses the two numbers. `compose()` is the
ONE path used for both the preview and the committed result, so what is on
screen is what Apply produces.

The two points are set on a HISTOGRAM, not on sliders. Andreas, on the tool as
first shipped: "it's strange that we have a Starless Levels function that does
not even show a levels histogram, as that is what determines how much to push
the black and white levels ... for starless levels the levels IS the key". The
histogram is `RangeHandles` — the same widget Colour Balance uses — and its two
draggable bounds ARE the black and white points, so there is one control for one
value rather than two that can drift apart.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from ..core.enhance import starless_levels_layers
from ..core.image import AstroImage
from ..core.inspect import capture_clip_baseline, clip_overlay
from .compare_view import CompareView
from .curves_dialog import _downscale, _fit_to_screen, _fitted_size
from .preview import rgb_to_qimage, to_qimage, to_rgb8
from .range_handles import RangeHandles

_PREFERRED = (1180, 860)

# The histogram gets its own full-width row under the preview rather than a slot
# in the 340 px control column, because a histogram in a 340 px column is
# exactly the "small histogram levels ... as it is in colorbalance" he rejected.
# Width is what a histogram needs most; 200 px of height is what makes the shape
# of the noise floor — where the black point belongs — readable at all.
_HIST_MIN_H = 200

# Label -> CompareView mode. Off is the default: someone who does not want a
# before/after sees exactly the dialog they had.
_MODES = (("Off", "off"), ("Wipe", "wipe"), ("Side by side", "side"))


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
        # `clip_masks` raises on a shape mismatch, so a baseline belongs to ONE
        # crop. The key is the visible rect (or "fit"), never the shape: two
        # different crops of the same size would otherwise share a baseline and
        # light the wrong pixels.
        self._baseline_key = None
        self._baseline = None
        self._before_key = None
        self._before_img = None

        self.handles = RangeHandles()
        self.handles.setMinimumHeight(_HIST_MIN_H)
        # The STARLESS layer, not the composite: these are the pixels the two
        # points act on. A composite histogram would show the screened-back
        # stars as a bright tail neither handle can touch, which is precisely
        # the confusion the tool exists to remove.
        #
        # Full resolution, not the decimated preview: block-averaging narrows
        # the noise floor by the square root of the block, and the left edge of
        # that floor IS where the black point goes. Measured 82 ms on an 8.3 MP
        # frame, paid once against a star split that takes seconds.
        self.handles.set_histogram(starless.data)
        self.black_val = QLabel("0.000")
        self.white_val = QLabel("1.000")
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setToolTip("Back to 0.000 / 1.000 — the untouched image")
        self.reset_btn.clicked.connect(self.reset)

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
        # What the overlay leaves out. The marks show only what THIS tool added,
        # but the total is still reported in words — the main window's rule:
        # those shadows really are gone, and hiding that from someone editing an
        # already-crushed file would be its own lie.
        self.clip_line = QLabel("")
        self.clip_line.setWordWrap(True)
        self.clip_line.hide()

        self.preview = CompareView()
        self.preview.setMinimumSize(320, 240)
        self.mode_box = QComboBox()
        self.mode_box.addItems([label for label, _ in _MODES])
        self.mode_box.setToolTip(
            "Wipe splits one picture with a divider you drag; Side by side "
            "shows both at once, and pan and zoom move them together")

        # Scroll to zoom, drag to pan — plus explicit buttons, the same set
        # CurvesDialog carries over the same widget and for the same reason: a
        # trackpad gesture is not discoverable, and a large mosaic is unusable
        # without one. Sharper here than there, because zooming CHANGES WHAT
        # THE MASK COVERS (whole frame at fit, visible region beyond it) — so a
        # user who scroll-zoomed by accident silently lost the whole-frame clip
        # mask and had no way back to Fit.
        self.zoom_label = QLabel("1.0x")
        self.fit_btn = QPushButton("Fit")
        self.fit_btn.clicked.connect(self.preview.reset_view)
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.clicked.connect(
            lambda: self.preview.set_zoom(self.preview.zoom_level() * 1.5))
        self.zoom_out_btn = QPushButton("−")
        self.zoom_out_btn.clicked.connect(
            lambda: self.preview.set_zoom(self.preview.zoom_level() / 1.5))
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
        values_row = QHBoxLayout()
        values_row.addWidget(QLabel("Black"))
        values_row.addWidget(self.black_val)
        values_row.addStretch(1)
        values_row.addWidget(QLabel("White"))
        values_row.addWidget(self.white_val)
        side.addLayout(values_row)
        side.addWidget(self.reset_btn)
        compare_row = QHBoxLayout()
        compare_row.addWidget(QLabel("Compare"))
        compare_row.addWidget(self.mode_box, 1)
        side.addLayout(compare_row)
        side.addWidget(self.clip_check)
        side.addWidget(self.clip_line)
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

        self._body = QHBoxLayout()
        self._body.addWidget(self.preview, 1)
        self._body.addWidget(side_wrap)

        hist_caption = QLabel("Levels — the starless layer alone. Drag the two "
                              "handles to where the data begins and ends.")
        hist_caption.setWordWrap(True)

        root = QVBoxLayout(self)
        root.addLayout(self._body, 1)
        root.addWidget(hist_caption)
        root.addWidget(self.handles)

        # Debounced like curves_dialog: a handle drag emits on every pixel of
        # movement, and recomposing the full-resolution image on each one
        # stutters. The labels still update immediately — only the (expensive)
        # render waits.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_preview)

        self.handles.rangeChanged.connect(self._on_range_changed)
        self.clip_check.toggled.connect(self._on_clip_toggled)
        self.mode_box.currentIndexChanged.connect(self._on_mode_changed)
        # CompareView emits viewChanged for wheel-zoom, drag-pan and the
        # buttons alike. Without this connection the widget still tracks the
        # gesture internally but the picture never redraws -- finding the first
        # clipped specks IS this tool's workflow, more than it is CurvesDialog's
        # sanity-check preview, so zoom/pan has to actually feed back into the
        # render here.
        self.preview.viewChanged.connect(self._on_view_changed)
        self._update_labels()
        self._render_preview()   # first paint, not debounced

    # --- the two numbers ---
    def values(self) -> tuple[float, float]:
        """The handles ARE the black and white points — there is no second copy
        of these numbers to fall out of step with them."""
        return self.handles.range()

    def compose(self, starless=None, stars=None) -> AstroImage:
        black, white = self.values()
        return starless_levels_layers(starless if starless is not None else self._starless,
                                      stars if stars is not None else self._stars,
                                      black, white)

    def reset(self) -> None:
        # `set_range` is deliberately silent, so the label refresh and the
        # re-render are asked for explicitly here.
        self.handles.set_range(0.0, 1.0)
        self._update_labels()
        self._queue_preview()

    def _update_labels(self) -> None:
        black, white = self.values()
        self.black_val.setText(f"{black:.3f}")
        self.white_val.setText(f"{white:.3f}")

    def _on_range_changed(self, _lo: float, _hi: float) -> None:
        self._update_labels()
        self._queue_preview()

    def _queue_preview(self, *_) -> None:
        self._timer.start(60)

    def _on_clip_toggled(self, on: bool) -> None:
        self.clip_line.setVisible(bool(on))
        # Not debounced: the readout beside the checkbox is written when the
        # baseline is captured, and a 60 ms window where the line is visible but
        # blank reads as a bug in the line rather than a wait for a render.
        self._render_preview()

    def _on_mode_changed(self, index: int) -> None:
        self.preview.set_mode(_MODES[index][1])
        # Not debounced: the mode switch has already relaid the widget out, and
        # "before" is only rendered at all when a compare mode is showing, so
        # the new pane would otherwise sit empty for the length of the debounce.
        self._render_preview()

    def _on_view_changed(self, *_) -> None:
        # The readout tracks the gesture, the render waits for the debounce —
        # the same split the value labels use. A zoom number that only caught
        # up 60 ms later would lag the thing it is describing.
        self.zoom_label.setText(f"{self.preview.zoom_level():.1f}x")
        self._queue_preview()

    # --- rendering ---
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

        "Before" is the untouched composite — black 0.0, white 1.0, the tool
        doing nothing — and is composed ONLY when a compare mode is showing it.
        In Off it would be a second full compose per tick for a picture nobody
        can see.
        """
        view = self.preview
        fit = view.zoom_level() <= 1.0
        if fit:
            key = ("fit",)
            full_starless, full_stars = self._starless, self._stars
        else:
            shape = self._starless.data.shape
            key = view.visible_rect(shape)
            x0, y0, x1, y1 = key
            full_starless = AstroImage(self._starless.data[y0:y1, x0:x1],
                                       is_linear=self._starless.is_linear,
                                       metadata=dict(self._starless.metadata))
            full_stars = AstroImage(self._stars.data[y0:y1, x0:x1],
                                    is_linear=self._stars.is_linear,
                                    metadata=dict(self._stars.metadata))

        clipping = self.clip_check.isChecked()
        show_before = view.mode() != "off"
        small_starless = small_stars = None
        if show_before or not clipping:
            if fit:
                small_starless, small_stars = self._small_starless, self._small_stars
            else:
                box = view.pane_size()
                edge = max(box.width(), box.height(), 1)
                small_starless = _downscale(full_starless, max_edge=edge)
                small_stars = _downscale(full_stars, max_edge=edge)

        if clipping:
            after = self._clip_qimage(full_starless, full_stars, key)
        else:
            after = to_qimage(self.compose(small_starless, small_stars))
        before = self._before_qimage(small_starless, small_stars, key) \
            if show_before else None
        view.set_images(before, after)

    def _before_qimage(self, small_starless: AstroImage, small_stars: AstroImage,
                       key):
        """The untouched composite, cached: it depends on the crop and the
        preview scale, never on the two handles, so recomposing it on every tick
        of a drag would double the cost of the drag for a picture that has not
        changed."""
        cache_key = (key, small_starless.data.shape)
        if cache_key != self._before_key:
            self._before_img = to_qimage(
                starless_levels_layers(small_starless, small_stars, 0.0, 1.0))
            self._before_key = cache_key
        return self._before_img

    def _clip_baseline(self, starless: AstroImage, stars: AstroImage, key):
        """The clipping already present with the tool doing nothing.

        Re-captured whenever the crop changes, never reused across zoom levels:
        `clip_masks` raises on a shape mismatch, and a same-shaped crop from
        somewhere else in the frame would be worse than an exception. Cached on
        the key so a handle drag — which changes neither crop nor baseline —
        keeps costing one compose per tick rather than two.
        """
        if key != self._baseline_key:
            untouched = starless_levels_layers(starless, stars, 0.0, 1.0)
            self._baseline = capture_clip_baseline(to_rgb8(untouched))
            self._baseline_key = key
            self._update_clip_line()
        return self._baseline

    def _update_clip_line(self) -> None:
        """State the total in words, the way the main window does.

        Its precedent is explicit: the TOTAL is always what is reported, because
        those shadows really are gone. Only the MARKS are restricted to what
        this tool added — `auto_levels` sets the black point at median − 3.5·MAD
        earlier in the pipeline, so a starless layer arrives with 2-6% of its
        pixels already at zero (measured on Andreas' masters, 2026-09-09) and
        the old overlay lit every one of them the moment the dialog opened.
        """
        base = self._baseline
        was = []
        if base is not None and base.shadow_frac > 0:
            was.append(f"{base.shadow_frac * 100:.1f}% crushed")
        if base is not None and base.highlight_frac > 0:
            was.append(f"{base.highlight_frac * 100:.1f}% blown")
        detail = ", ".join(was) + " before this tool touched it" if was \
            else "nothing was clipped before this tool touched it"
        self.clip_line.setText(f"Marks only what these two points add — {detail}.")

    def _clip_qimage(self, starless: AstroImage, stars: AstroImage, key):
        """The clipping mask, block-maxed straight to the size it is DISPLAYED
        at — no smooth rescale afterwards.

        `clip_overlay` goes to lengths to keep an isolated speck at full
        intensity, and a `SmoothTransformation` to the pane then undid it:
        measured, an isolated lit block came out at 195, 111 or 55 depending on
        the factor, so a blown speck could render dimmer than a flat crushed
        background and read as the wrong fault entirely.
        `FastTransformation` is not the alternative — nearest-neighbour on a
        downscale drops the speck outright.

        Enlarging is the one case that still needs Qt, because a block-max can
        only combine pixels, never invent them. There nearest-neighbour is
        exactly right: it makes the lit block bigger at full intensity.

        Handed back at exactly the pane's fitted size, so `CompareView`'s own
        scale-to-fit is a no-op rather than a second rescale.
        """
        baseline = self._clip_baseline(starless, stars, key)
        full = self.compose(starless, stars)
        rgb = to_rgb8(full)                    # the canvas's own conversion
        src_h, src_w = rgb.shape[:2]
        box = _fitted_size(src_w, src_h, self.preview.pane_size())
        tw, th = min(src_w, max(1, box.width())), min(src_h, max(1, box.height()))
        qimage = rgb_to_qimage(clip_overlay(rgb, (th, tw), baseline=baseline))
        if (tw, th) != (box.width(), box.height()):
            qimage = qimage.scaled(box, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.FastTransformation)
        return qimage

    def resizeEvent(self, event) -> None:
        """Re-render at the new size rather than leaving `CompareView` to
        rescale what it already has. Its scale-to-fit is smooth, and a smooth
        rescale of the clipping overlay re-dilutes exactly the block-max the
        overlay exists to preserve — an isolated speck measured 195, 111 or 55
        instead of 255."""
        super().resizeEvent(event)
        self._queue_preview()

    def _apply(self) -> None:
        if self._on_apply is not None:
            self._on_apply(self.compose(), self.values())
        self.accept()
