from __future__ import annotations

import numpy as np
import shiboken6
from PySide6.QtCore import QEvent, Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ..core.image import AstroImage
from ..core.narrowband import (
    GOLD_BLUE, PALETTE_DESCRIPTIONS, OFFERED_PALETTES as _CORE_PALETTES, PALETTES_USING_BLEND,
    NarrowbandParams, gold_blue_stats, palette_defaults, render, screen,
)
from ..settings import resolve_binary
from ..steps.star_split import preferred_splitter, splitter_name
from ..tools.rcastro import RCAstro
from .compare_view import MODE_CHOICES, CompareView
from .progress_ring import ProgressRing, WaitingBlock
from .preview import downscale as _downscale, to_qimage
from .reset_slider import ResetSlider
from .busy_gate import BusyGate, keep_live
from .worker import run_async
from .help_link import HelpLink
from .zoom_row import ZoomRow

_SPLIT_MSG = "Separating stars…\n(one-time, then tweak live)"

_TAME_SPAN = 4.0     # slider 100% -> highlight_reduction 5.0

# THE REVERT SWITCH: the palette the dialog opens on (and Reset returns to).
# Before gold and blue the dialog opened on "HOO"; set it back to that (or to
# any palette) to revert. Every starting slider position and double-click
# default follows from palette_defaults() of whatever is here. The help's
# "the dialog opens on this one" line must move with it — a help test fails
# until it does. Saved projects and recipes are unaffected either way: they
# store the palette.
DEFAULT_PALETTE = GOLD_BLUE

_ENGINE_DEFAULTS = palette_defaults(DEFAULT_PALETTE)

# Controls that cannot bite in a palette, and the tooltip that says why. Greyed
# rather than hidden, and their VALUES are kept for the palette they serve.
_LIGHTNESS_INERT_TIP = (
    f"{GOLD_BLUE} always keeps the picture's own lightness, so this has no "
    f"effect here.")


def _slider_positions(p: NarrowbandParams) -> dict:
    """Slider positions for `p` — the exact inverse of NarrowbandDialog._params().

    Declared once, because the constructor, Reset and the engine each used to
    carry their own copy of these numbers and one had already drifted:
    lightness_preserve shipped False here and True in NarrowbandParams, so the
    same tool produced a different image from a recipe than it did by hand.
    """
    return {
        "palette": p.palette,
        # /100 rather than /50 like its neighbours: the default is 0.85 and
        # round(0.85 * 50) is 42, which reads back as 0.84. A control whose
        # own default it cannot represent is a control with a rounding bug.
        "oxygen": round(p.oxygen_strength * 100),
        "blend": round(p.blend_amount * 100),
        "sat": round(p.saturation * 100),
        "gold": round(p.gold_strength * 100),
        "blue": round(p.blue_strength * 100),
        "bright": round(p.brightness * 50),
        "protect": round(p.protect_background * 100),
        # highlight_reduction is identity at 1.0 and rolls the highlights down
        # above it, so the slider runs 0..100 over 1.0..5.0 with ZERO meaning off.
        # Zero must land on exactly 1.0 or every existing recipe re-renders.
        "tame": round((p.highlight_reduction - 1.0) / _TAME_SPAN * 100),
        "lightness": p.lightness_preserve,
    }


_DEBOUNCE_MS = 90
# Taken from the engine rather than retyped: this list and core.PALETTES were
# two copies of the same fact, which is exactly how lightness_preserve drifted.
# Only the offered ones: a retired palette still replays but is not a choice.
PALETTES = list(_CORE_PALETTES)


class NarrowbandDialog(QDialog):
    """Interactive narrowband recolour with live preview. Applied to a STARLESS
    nebula so stars keep their natural colour: on open we split stars
    (StarXTerminator, or whole-image without it), the user tweaks the starless
    recolour live, and on Apply the stars are screened back."""

    def __init__(self, settings, base: AstroImage, parent=None, on_apply=None,
                 starless=None, stars=None, on_split=None) -> None:
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
        # Hand a fresh split back so the app can cache it for every other
        # surface, exactly as ColorBalanceDialog does.
        self._on_split = on_split
        # Set when a split actually runs (see _default_starx). "" until
        # then, because a dialog closed without splitting has no engine
        # to report and must not invent one.
        self.last_engine = ""
        self._prev_starless = None
        self._prev_stars = None
        # Gold-and-blue statistics, measured ONCE per split from the preview
        # copy and handed to both the preview and Apply (spec D6).
        self._gb_stats = None
        self._last = None                 # last COMPOSED AstroImage (what the preview shows)
        self._started = False
        self._applying = False
        # Every control is off while the split or Apply runs: moved during
        # Apply, the committed picture was not the one on screen (audit
        # 2026-10-05). Close stays live; it drops a result still in flight.
        self._gate = BusyGate()

        # The same Off / Wipe / Side by side compare as Starless Levels, with
        # one pan/zoom for both panes (Andreas, 2026-10-07: "I want the side
        # by side in Narrowband as well").
        self.preview = CompareView()
        self.preview.setMinimumSize(460, 460)
        self.preview.set_placeholder("")
        self.waiting = WaitingBlock(self.preview)
        self.waiting.hide()
        self.preview.installEventFilter(self)
        self._before_q = None             # the opened image, at preview size
        self._after_q = None              # what the preview shows, at preview size

        pos = _slider_positions(_ENGINE_DEFAULTS)
        self.palette_box = QComboBox()
        self.palette_box.addItems(PALETTES)
        self.palette_box.setCurrentText(pos["palette"])
        self.blend_slider = ResetSlider(pos["blend"])
        self.oxygen_slider = ResetSlider(pos["oxygen"], maximum=200)
        self.sat_slider = ResetSlider(pos["sat"])
        self.gold_slider = ResetSlider(pos["gold"], maximum=200)
        self.blue_slider = ResetSlider(pos["blue"], maximum=200)
        self.bright_slider = ResetSlider(pos["bright"])
        self.protect_slider = ResetSlider(pos["protect"])
        self.tame_slider = ResetSlider(pos["tame"])
        self.oxygen_val = QLabel()
        self.blend_val = QLabel()
        self.protect_val = QLabel()
        self.sat_val = QLabel()
        self.gold_val = QLabel()
        self.blue_val = QLabel()
        self.bright_val = QLabel()
        self.tame_val = QLabel()
        self.palette_desc = QLabel()
        self.palette_desc.setWordWrap(True)
        # A wrapped label needs its height to follow its width, or the form row
        # keeps the one-line height and slices the rest off — which is exactly
        # what happened: three lines shown, the sentence cut mid-word.
        self.palette_desc.setSizePolicy(QSizePolicy.Policy.Preferred,
                                        QSizePolicy.Policy.MinimumExpanding)
        self.palette_desc.setMinimumHeight(self.palette_desc.fontMetrics().height() * 3)
        self.palette_desc.setObjectName("hint")
        self.mode_box = QComboBox()
        self.mode_box.addItems([label for label, _ in MODE_CHOICES])
        self.mode_box.setToolTip(
            "Compare with the image as you opened it. Wipe splits one picture "
            "with a divider you drag; Side by side shows both at once, and pan "
            "and zoom move them together")
        self.lightness_check = QCheckBox("Preserve lightness (keep tonal structure)")
        self.lightness_check.setChecked(pos["lightness"])
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(_DEBOUNCE_MS)
        self._render_timer.timeout.connect(self._do_render)
        self.palette_box.currentTextChanged.connect(self._on_palette_change)
        for s in (self.blend_slider, self.oxygen_slider, self.sat_slider,
                  self.gold_slider, self.blue_slider,
                  self.bright_slider, self.protect_slider, self.tame_slider):
            s.valueChanged.connect(lambda _v: self._on_slider_change())
        self.lightness_check.toggled.connect(lambda _v: self._schedule_render())
        self.mode_box.currentIndexChanged.connect(self._on_mode_changed)
        self.preview.viewChanged.connect(self._push_images)
        self.preview.paneResized.connect(self._push_images)

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
        # "SHO-style (gold and blue)" is wider than the field column under the
        # dark theme (209 px wanted, 186 given) and was cut to "...(gold and bl".
        # A row whose field cannot fit drops below its label instead; the
        # sliders all fit, so only that one row ever moves.
        controls.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        controls.addRow("Palette", self.palette_box)
        controls.addRow(self.palette_desc)      # spans both columns: see below
        controls.addRow("Oxygen strength", _row(self.oxygen_slider, self.oxygen_val))
        controls.addRow("Green blend", _row(self.blend_slider, self.blend_val))
        controls.addRow("Protect background", _row(self.protect_slider, self.protect_val))
        # Saturation for HOO / Pseudo-SHO; Gold and Blue in its place for
        # SHO-style. Swapped rather than greyed: the panel has to fit 1280x800,
        # and two dead rows on two palettes of three is clutter. Hidden rows
        # keep their values for when you switch back.
        self._sat_row = _row(self.sat_slider, self.sat_val)
        self._gold_row = _row(self.gold_slider, self.gold_val)
        self._blue_row = _row(self.blue_slider, self.blue_val)
        controls.addRow("Saturation", self._sat_row)
        controls.addRow("Gold", self._gold_row)
        controls.addRow("Blue", self._blue_row)
        controls.addRow("Tame core", _row(self.tame_slider, self.tame_val))
        controls.addRow("Brightness", _row(self.bright_slider, self.bright_val))
        controls.addRow(self.lightness_check)
        controls.addRow("Compare", self.mode_box)
        self._controls = controls   # walked by the help-accuracy guard
        self._shown_palette = self.palette_box.currentText()
        self._update_value_labels()
        self._describe_palette(self.palette_box.currentText())
        self._restrict_blend(self.palette_box.currentText())

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self.apply)
        close_btn = keep_live(QPushButton("Close"))
        close_btn.clicked.connect(self.reject)
        # Reset sits in the pinned row, as in Star Spikes: the three actions on
        # the dialog as a whole live together, not one of them mid-form.
        buttons = QHBoxLayout()
        buttons.addWidget(self.reset_btn)
        buttons.addWidget(self.apply_btn)
        buttons.addWidget(close_btn)

        zoom_row = ZoomRow(self.preview)
        self.zoom_label = zoom_row.label
        self.fit_btn = zoom_row.fit_btn
        self.zoom_in_btn, self.zoom_out_btn = zoom_row.in_btn, zoom_row.out_btn

        side = QVBoxLayout()
        side.addLayout(controls)
        side.addLayout(zoom_row)
        side.addStretch(1)
        self.status_ring = ProgressRing(size="small")
        self.status_ring.hide()
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.addWidget(self.status_ring, 0, Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.status, 1)
        side.addLayout(status_row)
        self.help_link = HelpLink("narrowband", self)
        side.addWidget(self.help_link, 0, Qt.AlignmentFlag.AlignRight)
        side.addLayout(buttons)
        side_wrap = QWidget()
        side_wrap.setLayout(side)
        side_wrap.setMaximumWidth(340)
        self._side = side_wrap

        body = QHBoxLayout(self)
        body.addWidget(self.preview, 1)
        body.addWidget(side_wrap)

    def _default_starx(self, img: AstroImage):
        """Whichever splitter is configured — RC-Astro, else StarNet2.

        Was RC-Astro only, which is why this dialog still said "StarX not
        configured" after StarNet2 worked in every step (2026-09-18). The rule
        lives in steps/star_split.preferred_splitter so there is one copy of it.

        Records the engine as it picks it, for the history line — the same
        contract every pipeline step now follows (Step.last_engine). Recorded
        HERE rather than looked up when the line is written, because this dialog
        runs for minutes and Settings is reachable throughout.
        """
        splitter = preferred_splitter(self._settings)
        self.last_engine = splitter_name(splitter)
        return splitter.remove_stars(img)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # The theme's font lands at polish, after __init__ sized the row from
        # the default one: under the dark theme the gold-and-blue description
        # needed 51 px and got 45, slicing its last line off. Re-measure now.
        self._fit_description()
        if self._started:
            return
        self._started = True
        if self._starless is not None:
            self._on_starless((self._starless, self._stars))
            return
        if preferred_splitter(self._settings) is None:
            self.status.setText("No star separation tool — narrowband applied to the whole "
                                "image (star colour may look off). Install StarNet2 (free) "
                                "or RC-Astro and point at it in Settings.")
            self._on_starless((self._base, None))
            return
        self.waiting.set_text(_SPLIT_MSG)
        self.waiting.set_indeterminate()
        self.waiting.setGeometry(self.preview.rect())
        self.waiting.show()
        self.waiting.raise_()
        self._gate.close(self._side)
        run_async(self._pool, lambda: self._starx_runner(self._base),
                  self._on_starless, self._on_error,
                  on_progress=self._on_split_progress)

    def _on_split_progress(self, done: int, total: int) -> None:
        """Count the star split up on the ring.

        The dialog's only sign of life was a static line of text, for the same
        split Starless Levels and Colour Balance count up on the same ring —
        same work, same wait.
        """
        if not shiboken6.isValid(self.waiting):
            return
        self.waiting.set_progress(done, total)

    def _on_starless(self, layers) -> None:
        self._release_controls()
        self.waiting.hide()
        self._starless, self._stars = layers
        # Only a REAL split is worth sharing. The no-splitter and error paths
        # both call this with (base, None), and publishing that would poison the
        # store for every other surface with an image that has all its stars in
        # it — silently, because it is the right shape.
        if self._on_split is not None and self._stars is not None:
            # WITH the tag. Publishing untagged left the history line for this
            # tool unable to say which splitter ran, while every pipeline step
            # could — and the cache is where a later surface reads it from.
            self._on_split(self._starless, self._stars, self.last_engine)
        self._prev_starless = _downscale(self._starless)
        self._prev_stars = None if self._stars is None else _downscale(self._stars)
        self._gb_stats = None
        self._before_q = to_qimage(_downscale(self._base))
        self._do_render()

    def _release_controls(self) -> None:
        """Open the gate, THEN re-derive: Green blend is off for every
        palette but HOO whatever the gate gave back, and Apply is on now
        there is a split."""
        self._gate.open()
        self._restrict_blend(self.palette_box.currentText())
        self.apply_btn.setEnabled(True)

    def _on_error(self, exc) -> None:
        self.status.setText(f"Star removal failed: {exc} — using the whole image.")
        self._on_starless((self._base, None))

    def reset(self) -> None:
        pos = _slider_positions(_ENGINE_DEFAULTS)
        self.palette_box.setCurrentText(pos["palette"])
        self.blend_slider.setValue(pos["blend"])
        self.oxygen_slider.setValue(pos["oxygen"])
        self.sat_slider.setValue(pos["sat"])
        self.gold_slider.setValue(pos["gold"])
        self.blue_slider.setValue(pos["blue"])
        self.bright_slider.setValue(pos["bright"])
        self.protect_slider.setValue(pos["protect"])
        self.tame_slider.setValue(pos["tame"])
        self.lightness_check.setChecked(pos["lightness"])
        self._update_value_labels()
        self._do_render()

    def _on_palette_change(self, palette: str) -> None:
        self._carry_defaults(self._shown_palette, palette)
        self._shown_palette = palette
        # Double-click resets to THIS palette's default: built once, the
        # sliders sent HOO's Oxygen to 60% and Protect to 20%.
        now = _slider_positions(palette_defaults(palette))
        for key, slider in self._sliders().items():
            slider.set_default(now[key])
        self._describe_palette(palette)
        self._restrict_blend(palette)
        self._update_value_labels()
        self._schedule_render()

    def _sliders(self) -> dict:
        return {"oxygen": self.oxygen_slider, "blend": self.blend_slider,
                "sat": self.sat_slider, "gold": self.gold_slider,
                "blue": self.blue_slider, "bright": self.bright_slider,
                "protect": self.protect_slider, "tame": self.tame_slider}

    def _carry_defaults(self, old: str, new: str) -> None:
        """Palettes start from different places (gold and blue: Oxygen 60%,
        Protect 20%). A slider still at the OLD palette's default was never
        touched, so it moves to the new palette's; one the user moved is
        theirs and stays put. Judged by position, so a slider moved and put
        back exactly on its default counts as untouched."""
        was, now = _slider_positions(palette_defaults(old)), _slider_positions(palette_defaults(new))
        for key, slider in self._sliders().items():
            if slider.value() == was[key] and was[key] != now[key]:
                slider.setValue(now[key])

    def _describe_palette(self, palette: str) -> None:
        self.palette_desc.setText(PALETTE_DESCRIPTIONS.get(palette, ""))
        self._fit_description()

    def _fit_description(self) -> None:
        lbl = self.palette_desc
        need = lbl.fontMetrics().height() * 3
        if lbl.width() > 0:
            need = max(need, lbl.heightForWidth(lbl.width()))
        lbl.setMinimumHeight(need)

    def _restrict_blend(self, palette: str) -> None:
        """Grey Green blend out where it cannot bite.

        Only HOO builds a synthetic green; the pseudo palettes take green
        straight from Ha or OIII and gold and blue never makes one, so the
        slider moved and the picture did not change —
        which reads as a broken app in the moment, and the help saying so does
        not undo that. Greyed rather than hidden, so the control stays
        discoverable, and its VALUE is kept: it applies again the moment you
        return to HOO.

        Preserve lightness is greyed the same way for gold and blue, which
        always keeps the picture's own lightness. Saturation is different: it
        is REPLACED there by Gold and Blue, so those rows are swapped, not
        greyed (see the form layout).
        """
        active = palette in PALETTES_USING_BLEND
        self.blend_slider.setEnabled(active)
        self.blend_val.setEnabled(active)
        if active:
            tip = ""
        elif palette == GOLD_BLUE:
            tip = (f"{palette} colours each pixel by its share of oxygen and never "
                   f"builds a green, so the blend has no effect here. Switch to HOO "
                   f"to use it.")
        else:
            tip = (f"{palette} builds its green directly from one channel, so the "
                   f"blend has no effect here. Switch to HOO to use it.")
        self.blend_slider.setToolTip(tip)
        lightness = palette != GOLD_BLUE
        self.lightness_check.setEnabled(lightness)
        self.lightness_check.setToolTip("" if lightness else _LIGHTNESS_INERT_TIP)
        gb = palette == GOLD_BLUE
        self._controls.setRowVisible(self._sat_row, not gb)
        self._controls.setRowVisible(self._gold_row, gb)
        self._controls.setRowVisible(self._blue_row, gb)

    def _on_mode_changed(self, index: int) -> None:
        self.preview.set_mode(MODE_CHOICES[index][1])
        self._push_images()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.preview and event.type() == QEvent.Type.Resize:
            self.waiting.setGeometry(self.preview.rect())
        return super().eventFilter(obj, event)

    def _on_slider_change(self) -> None:
        self._update_value_labels()
        self._schedule_render()

    def _update_value_labels(self) -> None:
        """Show each slider's mapped value. OIII boost / Brightness read as a
        multiplier (×1.33) to match the numbers a tutorial or PixInsight uses."""
        oxy = max(0.3, self.oxygen_slider.value() / 100.0)
        if self.palette_box.currentText() == GOLD_BLUE:
            # Here it is how much of the picture is blue (where the gold/blue
            # line sits), not a gain on OIII and not how strong the blue is —
            # that is the Blue slider. 100% is the picture's own balance point.
            self.oxygen_val.setText(f"{round(oxy * 100)}%")
        else:
            # 1.00 is the photometric match — the one value here that means
            # something beyond taste, and where the colour minimum sits. Naming
            # it makes it a place you can go back to.
            self.oxygen_val.setText(f"×{oxy:.2f} · matched" if abs(oxy - 1.0) < 5e-3
                                    else f"×{oxy:.2f}")
        self.bright_val.setText(f"×{max(0.3, self.bright_slider.value() / 50.0):.2f}")
        self.blend_val.setText(f"{self.blend_slider.value() / 100.0:.2f}")
        self.sat_val.setText(f"{self.sat_slider.value() / 100.0:.2f}")
        self.gold_val.setText(f"{self.gold_slider.value()}%")
        self.blue_val.setText(f"{self.blue_slider.value()}%")
        self.protect_val.setText(f"{self.protect_slider.value()}%")
        # "off", not "×1.00": the raw number means nothing outside the PixInsight
        # formula it comes from, and zero genuinely does nothing at all.
        tame = self.tame_slider.value()
        self.tame_val.setText("off" if tame == 0 else f"{tame}%")

    def _params(self) -> NarrowbandParams:
        palette = self.palette_box.currentText()
        # Each palette reads only the rows it shows: SHO-style takes Gold and
        # Blue at the default saturation, the others Saturation at Gold and
        # Blue 100%. A hidden slider's value never reaches the picture or the
        # history line.
        if palette == GOLD_BLUE:
            sat = palette_defaults(GOLD_BLUE).saturation
            gold, blue = self.gold_slider.value() / 100.0, self.blue_slider.value() / 100.0
        else:
            sat = self.sat_slider.value() / 100.0
            gold = blue = 1.0
        return NarrowbandParams(
            palette=palette,
            blend_amount=self.blend_slider.value() / 100.0,
            oxygen_strength=max(0.3, self.oxygen_slider.value() / 100.0),
            saturation=sat,
            gold_strength=gold,
            blue_strength=blue,
            brightness=max(0.3, self.bright_slider.value() / 50.0),
            protect_background=self.protect_slider.value() / 100.0,
            highlight_reduction=1.0 + self.tame_slider.value() / 100.0 * _TAME_SPAN,
            lightness_preserve=self.lightness_check.isChecked(),
        )

    def _schedule_render(self) -> None:
        if self._prev_starless is not None:
            self._render_timer.start()

    def _do_render(self) -> None:
        if self._prev_starless is None:
            return
        try:
            # has_stars=False only when a real split happened: without StarX the
            # base frame IS the 'starless' layer and its stars are still in it.
            params = self._params()
            nebula = render(self._prev_starless, params,
                            has_stars=self._prev_stars is None,
                            stats=self._stats_for(params))
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        # Screen the untouched stars back for the PREVIEW too, not only on Apply.
        # Showing the starless layer meant what you tuned against was never what
        # you got, which breaks the rule that a preview equals its export — and
        # it hid the tool's own promise, since you cannot watch stars stay
        # unaltered when they are not on screen.
        if self._prev_stars is None:
            self._last = nebula
        else:
            self._last = AstroImage(
                screen(nebula.data, np.clip(self._prev_stars.data, 0.0, 1.0)),
                is_linear=nebula.is_linear, metadata=dict(nebula.metadata))
        self._after_q = to_qimage(self._last)
        self._push_images()

    def _stats_for(self, params: NarrowbandParams):
        """The gold-and-blue statistics, measured once per split from the
        PREVIEW copy — the copy a full-size render measures them from too (core
        _stats_copy == ui.preview.downscale), so the preview's colours are the
        ones Apply and a replay commit. None for the other palettes."""
        if params.palette != GOLD_BLUE:
            return None
        if self._gb_stats is None:
            self._gb_stats = gold_blue_stats(self._prev_starless)
        return self._gb_stats

    def _push_images(self) -> None:
        """Hand the compare widget what is on screen. Zoomed in, both panes get
        the same crop of the preview-sized pictures: the render reads whole-image
        statistics, so re-rendering a crop would show colours Apply never makes.
        Wipe magnifies the whole frame itself, so it always gets the whole frame."""
        if self._after_q is None:
            return
        before, after = self._before_q, self._after_q
        if self.preview.mode() != "wipe" and self.preview.zoom_level() > 1.0:
            x0, y0, x1, y1 = self.preview.visible_rect((after.height(), after.width()))
            after = after.copy(x0, y0, x1 - x0, y1 - y0)
            if before is not None:
                before = before.copy(x0, y0, x1 - x0, y1 - y0)
        self.preview.set_images(before, after)
        self.zoom_label.setText(f"{self.preview.display_zoom():.1f}x")

    def preview_result(self) -> AstroImage:
        return self._last

    def apply(self) -> None:
        """Render at FULL resolution off the UI thread.

        Measured: 2.9 s on a 39.5 MP master, 8.4 s with Preserve lightness on,
        which round-trips through CIE Lab. Done inline that froze the window with
        nothing on screen to say why — while star removal, three times slower
        again, had run through run_async in this same dialog all along.
        """
        if self._starless is None:
            self.status.setText("Still separating stars…")
            return
        if self._applying:
            return
        self._applying = True
        params = self._params()
        stats = self._stats_for(params) if self._prev_starless is not None else None
        self._gate.close(self._side)
        self.status.setText("Applying at full resolution…")
        self.status_ring.set_indeterminate()
        self.status_ring.show()
        run_async(self._pool, lambda: self._compose_full(params, stats),
                  lambda result: self._on_applied(result, params),
                  self._on_apply_error)

    def _compose_full(self, params: NarrowbandParams, stats=None) -> AstroImage:
        """Full-resolution recolour plus the star recombine. Runs on the pool."""
        nebula = render(self._starless, params, has_stars=self._stars is None,
                        stats=stats)
        if self._stars is None:
            return nebula
        out = screen(nebula.data, np.clip(self._stars.data, 0.0, 1.0))
        return AstroImage(out, is_linear=False, metadata=dict(self._starless.metadata))

    def _on_applied(self, result: AstroImage, params: NarrowbandParams) -> None:
        self._applying = False
        if getattr(self, "_discarded", False):
            return
        self.status_ring.hide()
        if self._on_apply is not None:
            self._on_apply(result, params)
        self.accept()

    def reject(self) -> None:
        # Close, Esc and the close box all land here. A full-resolution Apply
        # cannot be stopped mid-render, so its result is DROPPED when it lands:
        # it used to be committed as a step after the user had cancelled
        # (progress-ring final review, 2026-10-04).
        self._discarded = True
        super().reject()

    def _on_apply_error(self, exc) -> None:
        self._applying = False
        self.status_ring.hide()
        self._release_controls()
        self.status.setText(f"Apply failed: {exc}")
