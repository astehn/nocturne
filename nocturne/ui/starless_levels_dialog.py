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

from PySide6.QtCore import QLocale, Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..core.enhance import starless_levels_layers
from ..core.levels import apply_levels
from ..core.image import AstroImage
from ..core.inspect import capture_clip_baseline, clip_masks, clip_overlay
from .compare_view import CompareView
from .curves_dialog import _downscale, _fit_to_screen, _fitted_size
from .preview import rgb_to_qimage, to_qimage, to_rgb8
from .range_handles import RangeHandles
from .zoom_row import ZoomRow

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
        # What the image ARRIVED with, over the WHOLE frame — see
        # `_frame_fractions`. Never recomputed, so the sentence under the
        # checkbox does not change when the user zooms.
        self._frame_clip = None

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
        # Spin boxes, not labels. The removed `ResetSlider` pair gave arrow-key
        # stepping at 0.001; a histogram handle is mouse-only at ~0.001 per
        # pixel, so the rework took the precision away with the sliders. These
        # are not a second control holding a second copy of the number — they
        # READ FROM `handles.range()` and write straight back into it, and
        # `_sync_readouts` re-reads the handles afterwards so what is shown is
        # always what the handles took (they clamp `_MIN_SPAN`).
        self.black_val = QDoubleSpinBox()
        self.white_val = QDoubleSpinBox()
        for box, tip in ((self.black_val, "Black point — type a value or use "
                                          "the arrow keys to nudge by 0.001"),
                         (self.white_val, "White point — type a value or use "
                                          "the arrow keys to nudge by 0.001")):
            box.setDecimals(3)
            box.setRange(0.0, 1.0)
            box.setSingleStep(0.001)
            # Without this every keystroke of a typed value is a separate edit,
            # so typing "0.25" passes through 0.2 and recomposes the image on
            # the way.
            box.setKeyboardTracking(False)
            # A decimal POINT, whatever the system locale says. Every other
            # number in the app is formatted "{:.3f}" — the history step, the
            # provenance report, the log line, this dialog's own help — so on a
            # Swedish machine (Andreas') the untouched spin box read "0,000"
            # beside a history entry saying "0.000" for the same value.
            box.setLocale(QLocale.c())
            box.setToolTip(tip)
            box.valueChanged.connect(self._on_readout_edited)
        self.black_val.valueChanged.connect(lambda *_: self._note_end("lo"))
        self.white_val.valueChanged.connect(lambda *_: self._note_end("hi"))
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setToolTip("Back to 0.000 / 1.000 — the untouched image")
        self.reset_btn.clicked.connect(self.reset)

        # Which end the user is working, when they said so by TYPING rather than
        # by dragging. None means "ask the handles".
        self._typed_end: str | None = None
        # (shadow, highlight) fractions the CURRENT endpoints add; None until measured.
        self._added: tuple[float, float] | None = None

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

        # The shared row (zoom_row.py), so the buttons drive whichever widget
        # the current Compare mode actually shows. Built by hand here before,
        # they drove the side/off pane's model in Wipe mode too — where the
        # picture is an ImageView that does not use it: Fit did nothing, the
        # readout froze at whatever it last said, and "+" re-cropped from a
        # DETACHED pane's stale geometry (a 400x600 crop out of a square
        # frame). The help documents these three buttons, so that was a
        # documented control lying in one of three modes.
        zoom_row = ZoomRow(self.preview)
        self.zoom_label = zoom_row.label
        self.fit_btn = zoom_row.fit_btn
        self.zoom_in_btn, self.zoom_out_btn = zoom_row.in_btn, zoom_row.out_btn

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
        # A mode switch changes the pane's size without resizing `CompareView`,
        # so neither this dialog's resizeEvent nor `viewChanged` sees it — and
        # the clipping overlay is built AT the pane size, which would then be
        # the previous mode's.
        self.preview.paneResized.connect(self._queue_preview)
        self._sync_readouts()
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
        # `set_range` is deliberately silent, so the readout refresh and the
        # re-render are asked for explicitly here.
        # Reset means no end is being worked any more, so the clipping view goes
        # back to its opening polarity rather than keeping whichever ground the
        # abandoned edit had chosen.
        self._typed_end = None
        self.handles.reset_last_handle()
        self.handles.set_range(0.0, 1.0)
        self._sync_readouts()
        self._queue_preview()

    def _sync_readouts(self) -> None:
        """Push the handles' numbers into the two spin boxes.

        Signals blocked, so writing the handles' value back into a box the user
        just edited cannot echo round and drive the handles again.
        """
        for box, value in zip((self.black_val, self.white_val), self.values()):
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)

    def _on_readout_edited(self, *_) -> None:
        """A typed or arrow-keyed value goes STRAIGHT into the handles, and the
        boxes are then re-read from them — so the handles stay the one place
        these two numbers live, and a value they clamp is shown clamped rather
        than the box keeping a number the tool is not using."""
        self.handles.set_range(self.black_val.value(), self.white_val.value())
        self._sync_readouts()
        self._queue_preview()

    def _on_range_changed(self, _lo: float, _hi: float) -> None:
        # A real handle drag is now the most recent statement of which end is
        # being worked, so a typed one stops speaking for it. `rangeChanged`
        # fires on drags only (`set_range` is silent), so this cannot be
        # tripped by the sync below writing the numbers back.
        self._typed_end = None
        self._sync_readouts()
        self._queue_preview()

    def _queue_preview(self, *_) -> None:
        self._timer.start(60)

    def _on_clip_toggled(self, on: bool) -> None:
        self.clip_line.setVisible(bool(on))
        # Not debounced: a 60 ms window where the line is visible but blank
        # reads as a bug in the line rather than a wait for a render. The line
        # itself is filled in by `_render_preview` (which now keeps it live on
        # every drag too, not just on toggle), so there is nothing left to do
        # here once clipping is on.
        self._render_preview()

    def _on_mode_changed(self, index: int) -> None:
        self.preview.set_mode(_MODES[index][1])
        # Not debounced: the mode switch has already relaid the widget out, and
        # "before" is only rendered at all when a compare mode is showing, so
        # the new pane would otherwise sit empty for the length of the debounce.
        self._render_preview()

    def _on_view_changed(self, *_) -> None:
        # The readout tracks the gesture (ZoomRow is connected to the same
        # signal), the render waits for the debounce — the same split the two
        # value readouts use.
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
            # A drag can flip which end is showing (`_clip_end`) without going
            # through `_on_clip_toggled` at all, so the label has to be kept
            # live here too — otherwise it goes stale the moment someone drags
            # a handle with the overlay already on, exactly the "which end am
            # I looking at" confusion the label exists to prevent.
            self._update_clip_line()
        else:
            after = to_qimage(self.compose(small_starless, small_stars))
        # With clipping on the two halves are produced by different paths — the
        # overlay is built at the PANE's size, "before" from the decimated copy
        # — so they must be reconciled explicitly. `ImageView.set_compare` takes
        # the divider's whole range from the COMPARE pixmap: measured on a
        # 1200^2 frame, base 601x601 against compare 1200x1200, which spread the
        # divider over twice the picture and showed the "before" half as a 2x
        # magnified top-left quadrant.
        before = self._before_qimage(small_starless, small_stars, key,
                                     box=after.size() if clipping else None) \
            if show_before else None
        view.set_images(before, after)

    def _before_qimage(self, small_starless: AstroImage, small_stars: AstroImage,
                       key, box=None):
        """The untouched composite, cached: it depends on the crop and the
        preview scale, never on the two handles, so recomposing it on every tick
        of a drag would double the cost of the drag for a picture that has not
        changed.

        `box` is the size the "after" image came out at, given only when the two
        paths can disagree about it — see the call site. Same source aspect, so
        a KeepAspectRatio fit into it lands on exactly that size.
        """
        cache_key = (key, small_starless.data.shape,
                     None if box is None else (box.width(), box.height()))
        if cache_key != self._before_key:
            img = to_qimage(
                starless_levels_layers(small_starless, small_stars, 0.0, 1.0))
            if box is not None and img.size() != box:
                img = img.scaled(box, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            self._before_img = img
            self._before_key = cache_key
        return self._before_img

    def _levels_args(self) -> tuple[float, float, float]:
        """(black, gamma, white) for `apply_levels`. Gamma is fixed at 1.0 —
        this tool is the two endpoints and nothing else."""
        black, white = self.values()
        return (black, 1.0, white)

    def _clip_baseline(self, starless: AstroImage, stars: AstroImage, key):
        """The clipping already present with the tool doing nothing.

        Re-captured whenever the crop changes, never reused across zoom levels:
        `clip_masks` raises on a shape mismatch, and a same-shaped crop from
        somewhere else in the frame would be worse than an exception. Cached on
        the key so a handle drag — which changes neither crop nor baseline —
        keeps costing one compose per tick rather than two.
        """
        if key != self._baseline_key:
            # Same layer the mask is taken from (see _clip_qimage), or the two
            # measure different pictures and the subtraction is meaningless.
            untouched = apply_levels(starless, 0.0, 1.0, 1.0)
            self._baseline = capture_clip_baseline(to_rgb8(untouched))
            self._baseline_key = key
            if key == ("fit",) and self._frame_clip is None:
                # At fit this crop IS the whole frame, so the reported figures
                # come free — see `_frame_fractions`.
                self._frame_clip = (self._baseline.shadow_frac,
                                    self._baseline.highlight_frac)
        return self._baseline

    def _frame_fractions(self) -> tuple[float, float]:
        """What the image ARRIVED with, measured over the WHOLE frame ONCE.

        The per-crop baseline cannot answer this. It is captured on whatever is
        currently visible, so zooming into a dark corner took the line from
        "2.1% crushed" to "40% crushed" while the sentence still said "before
        this tool touched it" — which reads as a property of the file. The
        overlay answers "what am I adding here" and is right to follow the crop;
        this sentence answers "what did this image arrive with", and that does
        not change when you zoom.

        Measured on first need rather than in __init__: it is a full compose of
        the whole frame, and nobody who leaves Show Clipping off should pay it.
        At fit it costs nothing at all — `_clip_baseline` has already done the
        work and hands the figures over.
        """
        if self._frame_clip is None:
            untouched = starless_levels_layers(self._starless, self._stars,
                                               0.0, 1.0)
            base = capture_clip_baseline(to_rgb8(untouched))
            self._frame_clip = (base.shadow_frac, base.highlight_frac)
        return self._frame_clip

    def _clip_end(self) -> str | None:
        """Which end the clipping view shows: whichever handle the user last
        DRAGGED, or None before either has been touched.

        Photoshop flips the ground with the end being worked — white for the
        black point, black for the highlights — rather than showing both ends
        on one ground. Reading straight from `RangeHandles` rather than
        tracking a second copy here: it already has to know which handle moved
        to clamp the pair, so this is one accessor, not a duplicate state
        machine that could drift from it.
        """
        return self._typed_end or self.handles.last_handle()

    def _note_end(self, end: str) -> None:
        """Typing into a readout is working that end, exactly as dragging its
        handle is.

        `RangeHandles.last_handle` deliberately ignores `set_range`, so that a
        preset cannot masquerade as a handle drag — correct for its own
        purposes, but the spin boxes here are not a preset. They are the same
        control as the handle, offered to someone who wants to type 0.154
        rather than find it with a mouse, so they must flip the clipping ground
        the same way. Held here rather than pushed into RangeHandles, so
        Colour Balance's use of the same widget is untouched."""
        self._typed_end = end

    def _added_phrase(self, end) -> str:
        """What the current endpoints are costing, in the same voice as the rest.

        The marks alone cannot say whether they mean half the frame or almost
        none of it — and on a large image almost none of it still paints a
        startling number of dots, because one display pixel stands for a hundred
        real ones and lights if any of them clips.
        """
        if self._added is None:
            return "Nothing is clipping now."
        shadow, highlight = self._added
        parts = []
        if end != "hi" and shadow > 0:
            parts.append(f"{shadow * 100:.3f}% crushed")
        if end != "lo" and highlight > 0:
            parts.append(f"{highlight * 100:.3f}% blown")
        if not parts:
            return "Nothing is clipping now."
        return "Right now that is " + " and ".join(parts) + "."

    def _update_clip_line(self) -> None:
        """State which end is showing, then the total in words, the way the
        main window does.

        The end has to be said out loud — Andreas' first report of trouble
        ("the overlay does not seem to fill the entire image area") was a dark
        mark on a dark ground with a dark letterbox, i.e. exactly the shadow
        case with no way to tell it apart from "nothing is clipped".

        The total-in-words precedent is unchanged: the TOTAL is always what is
        reported, because those shadows really are gone. Only the MARKS are
        restricted to what this tool added — `auto_levels` sets the black
        point at median − 3.5·MAD earlier in the pipeline, so a starless layer
        arrives with 2-6% of its pixels already at zero (measured on Andreas'
        masters, 2026-09-09) and the old overlay lit every one of them the
        moment the dialog opened.
        """
        end = self._clip_end()
        if end == "lo":
            which = "Showing shadow clipping only, on a white ground — working the black point."
        elif end == "hi":
            which = "Showing highlight clipping only, on a black ground — working the white point."
        else:
            which = "Showing shadow and highlight clipping together, on a black ground."
        shadow_frac, highlight_frac = self._frame_fractions()
        was = []
        if shadow_frac > 0:
            was.append(f"{shadow_frac * 100:.1f}% crushed")
        if highlight_frac > 0:
            was.append(f"{highlight_frac * 100:.1f}% blown")
        detail = ", ".join(was) + " before this tool touched it" if was \
            else "nothing was clipped before this tool touched it"
        now = self._added_phrase(end)
        self.clip_line.setText(
            f"{which} Marks only what these two points add. {now} "
            f"For reference, {detail}.")

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

        `end` (from `_clip_end`) follows Photoshop's polarity: the ground and
        which end is drawn both come from `clip_overlay`, keyed off whichever
        handle was last dragged. `None` — nothing dragged yet — is the one
        case handed straight through with no new argument at all, which is
        what keeps this identical to the view that shipped before.
        """
        baseline = self._clip_baseline(starless, stars, key)
        # The STARLESS layer, not the composite. The endpoints act on this layer
        # alone; the stars are screened back untouched, so clipping a star causes
        # is neither something these two points did nor something they can undo.
        # Measured on Andreas' IC 1396A drizzle: 335 of 2357 marks (14.2%) came
        # from the stars, every one of them on a star, over starless values as
        # low as 0.161 — i.e. a faint star on dark nebulosity, marked as though
        # the user had blown it. That is what sent him to Photoshop to check.
        rgb = to_rgb8(apply_levels(starless, *self._levels_args()))
        src_h, src_w = rgb.shape[:2]
        box = _fitted_size(src_w, src_h, self.preview.pane_size())
        tw, th = min(src_w, max(1, box.width())), min(src_h, max(1, box.height()))
        end = self._clip_end()
        # What these endpoints cost, so the readout can give the marks a scale.
        # Without it a screen of alarming dots came with no way to tell whether
        # it meant half the frame or, as on Andreas' IC 1396A, 0.0095% of it.
        sh, hi = clip_masks(rgb, baseline=baseline)
        px = max(1, rgb.shape[0] * rgb.shape[1])
        self._added = (float(sh.any(axis=2).sum()) / px,
                       float(hi.any(axis=2).sum()) / px)
        qimage = rgb_to_qimage(clip_overlay(rgb, (th, tw), baseline=baseline, end=end))
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
