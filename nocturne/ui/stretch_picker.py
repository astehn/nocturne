"""Pick a stretch by looking at it, rather than by guessing a number.

Why this exists. Two days of measurement established that Nocturne's stretch was
leaving the sky about twice as bright as AstroWizard's, which is why its images
looked "cleaner" — identical noise is far more visible on a lifted grey sky. The
default came down 0.43 -> 0.30 as a result. But the ladders that produced that
number DISAGREE WITH EACH OTHER:

    M 16  0.10     M 33  0.10     IC 1396A  0.10
    M 45  0.20-0.30   - at 0.10 "too much of the nebulosity is not visible"

One number cannot serve 0.10 and 0.30, so a default can only ever be a best
guess. This is the tool for beating it.

It also resolves the long-open "genuinely automatic stretch" question, which
stalled on a real objection: Levels' auto works because a black point is a FACT
derivable from the data, while a background target is a PREFERENCE — no
measurement makes 0.24 more correct than 0.31. The answer is not to compute it
better. It is to stop computing it and show the options.

See docs/superpowers/specs/2026-09-14-visual-stretch-picker-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog, QGridLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

from ..core.image import AstroImage
from ..core.stretch import apply_stretch
from .preview import downscale, to_qimage, to_rgb8

# Six panels, even steps. This is the ladder Andreas made all four of his
# decisions from, so it is evidence rather than a guess.
#
# Even spacing rather than fine steps concentrated over 0.00-0.30 where every
# one of his answers landed, because THE PICK IS NOT FINAL: it lands on the real
# slider, which has a live preview. The picker's job is the right neighbourhood;
# the slider does the fine adjustment. Even spacing also bakes in no assumption
# about whose taste generalises. Nothing usable lives above 0.60.
#
# The names describe the RESULT, never the subject. That is the whole difference
# between this and the Target dropdown deleted on 2026-09-13: "Darker" is a
# description of the picture in front of you, "Nebula" was a claim about what
# you photographed, and a claim can be wrong.
STRETCH_PICKS: list[tuple[str, float]] = [
    ("Darkest", 0.00),
    ("Darker", 0.12),
    ("Balanced", 0.24),
    ("Brighter", 0.36),
    ("Bright", 0.48),
    ("Brightest", 0.60),
]

_PREVIEW_MAX = 640      # as curves_dialog and color_balance_dialog
_PREVIEW_MIN = 160      # smaller than this and faint nebulosity cannot be
                        # judged, which is the whole point of looking
_COLUMNS = 3
_SCREEN_USE = 0.9       # leave the dock and menu bar visible


# Cold naming on purpose. A descriptive name ("Warmer sky") is a claim about one
# image and will be wrong on another; "Unlinked" describes the mechanism and
# stays true forever — the property that made the brightness numbers safe beside
# their names. It is also what Siril, PixInsight and AstroWizard all call it, so
# it transfers to every tutorial the user will ever read, and the app already
# ships a harder word than this as a step name ("Deconvolution").
#
# NEITHER may be labelled the correct one. The five-capture table in
# neutral_stretch favours linked on colour drift; sky neutrality measured over
# four of Andreas's masters favours unlinked; they measure different quantities
# and the first has never been reproduced. A correctness label would ship a
# claim we cannot support.
COLOUR_PICKS: list[tuple[str, bool, str]] = [
    ("Linked", True, "keeps the sky's own colour"),
    ("Unlinked", False, "evens the channels out"),
]

# An unlinked stretch does not weaken a photometric calibration, it ANNIHILATES
# it: a per-channel normalisation is exactly what removes a per-channel gain.
# Measured on IC 1396A at 0.0004 of an 8-bit level, at every gain tested.
_SPCC_CAVEAT = "Photometric calibration will be discarded"

# The brightness at which BOTH colour panels are rendered. Mid-ladder, so the
# picture is representative of what follows without the pick accidentally
# becoming a brightness decision too.
_COLOUR_TARGET = 0.24


def preview_edge(available: QSize, chrome: QSize, rows: int,
                 columns: int = _COLUMNS) -> int:
    """The largest square one preview may occupy for the grid to fit on screen.

    The dialog first shipped sizing itself from `_PREVIEW_MAX` alone: six 640 px
    panels in a 3x2 grid is about 1950x1450 before chrome, which overflowed a
    large monitor and would have been unusable on the 1280x800 floor this app
    targets. `chrome` is MEASURED from the real widgets rather than estimated,
    so this cannot drift the next time the dialog gains a line of text.
    """
    per_col = (available.width() - chrome.width()) // max(columns, 1)
    per_row = (available.height() - chrome.height()) // max(rows, 1)
    return max(_PREVIEW_MIN, min(per_col, per_row, _PREVIEW_MAX))


@dataclass
class Pick:
    """One question in the sequence.

    `options` TAKES the answers so far, even where it ignores them. A linked and
    an unlinked stretch produce different pictures at the same brightness, so a
    colour pick prepended later has to be able to change what the brightness
    panels show. That is the one property here which cannot be retrofitted
    cheaply, which is why it is carried before there is a second pick to need it.
    """
    title: str
    key: str
    options: Callable[[dict], list[tuple[str, object, AstroImage]]]
    caption: Callable[[str, object, AstroImage], str] = None
    caveats: dict = field(default_factory=dict)
    columns: int = _COLUMNS

    def __post_init__(self):
        if self.caption is None:
            self.caption = _amount_caption


def _amount_caption(name: str, value, img: AstroImage) -> str:
    """Name AND numbers: the name is a handle to think with, the number is the
    slider value you land on and can nudge from, so a name can never drift away
    from what it actually does."""
    return f"{name} \u00b7 {value:.2f} \u00b7 sky {_sky(img):.3f}"


def _colour_caption(name: str, value, img: AstroImage) -> str:
    """No number: unlike brightness there is no control to land on, so a figure
    here would be decoration. The subtitle carries the meaning instead."""
    sub = dict((n, s) for n, _v, s in COLOUR_PICKS)[name]
    return f"{name}\n{sub}"


def colour_pick(base: AstroImage, *, spcc_applied: bool = False) -> Pick | None:
    """Linked or unlinked? Returns None for mono, which has no colour to pick.

    Both panels are rendered at the SAME target so only colour varies — one
    variable per question, which is the decomposition AstroWizard gets right
    ("ignore brightness - depth is the next pick"). Two columns rather than
    three, because judging colour wants the larger picture.
    """
    if base.data.ndim != 3 or base.data.shape[-1] < 3:
        return None
    small = downscale(base, _PREVIEW_MAX)
    at = _COLOUR_TARGET

    def options(_state: dict):
        return [(name, linked, apply_stretch(small, at, linked=linked))
                for name, linked, _sub in COLOUR_PICKS]

    return Pick(title="How should the colour be balanced?",
                key="linked", options=options, caption=_colour_caption,
                caveats={False: _SPCC_CAVEAT} if spcc_applied else {},
                columns=2)


def brightness_pick(base: AstroImage) -> Pick:
    """How bright should the background be?"""
    small = downscale(base, _PREVIEW_MAX)      # once, not per panel

    def options(state: dict):
        # Rendered THROUGH the colour answer, which is the entire reason
        # options() takes the accumulated state: a linked and an unlinked
        # stretch are different pictures at the same brightness.
        linked = bool(state.get("linked", True))
        return [(name, amount, apply_stretch(small, amount, linked=linked))
                for name, amount in STRETCH_PICKS]

    return Pick(title="How bright should the background be?",
                key="amount", options=options)


class StretchPickerDialog(QDialog):
    """Pick a stretch by looking at six versions of your own image.

    Choosing SETS THE SLIDER; it does not commit. Apply remains the only thing
    in Nocturne that commits — the rule the step-commit model established — and
    this would otherwise be its sole exception. AstroWizard's equivalent does
    commit ("You leave this step with your stretch applied - done"); that was
    considered and rejected for consistency.
    """

    def __init__(self, base: AstroImage, parent=None, picks=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Visual stretch")
        self._picks = list(picks) if picks is not None else [brightness_pick(base)]
        self._state: dict = {}
        self._index = 0
        self._result: dict | None = None

        self._root = QVBoxLayout(self)
        self._title = QLabel("")
        self._title.setObjectName("stageTitle")
        self._root.addWidget(self._title)
        self._hint = QLabel(
            "Click the one you like. This only moves the slider — you still "
            "press Apply, and you can nudge it first.")
        self._hint.setObjectName("stepDesc")
        self._hint.setWordWrap(True)
        self._root.addWidget(self._hint)
        self._grid_host = QWidget()
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setWidget(self._grid_host)
        self._root.addWidget(self._scroll)
        self._cancel = QPushButton("Cancel")
        self._cancel.clicked.connect(self.reject)
        self._root.addWidget(self._cancel)
        self._render()

    # --- state ---------------------------------------------------------
    def panels(self) -> list[tuple[str, float, AstroImage]]:
        """The current pick's options: (name, value, rendered image)."""
        return self._picks[self._index].options(dict(self._state))

    def result_option(self) -> dict | None:
        """The accumulated answers, or None if nothing was chosen.

        None and "the first panel" have to be distinguishable, or cancelling
        would silently mean picking the darkest.
        """
        return self._result

    def choose(self, index: int) -> None:
        """Answer the current pick: advance, or finish on the last one."""
        pick = self._picks[self._index]
        _name, value, _img = pick.options(dict(self._state))[index]
        self._state[pick.key] = value
        if self._index + 1 < len(self._picks):
            self._index += 1
            self._render()
            return
        self._result = dict(self._state)
        self.accept()

    # --- view ----------------------------------------------------------
    def _render(self) -> None:
        pick = self._picks[self._index]
        self._title.setText(pick.title)
        options = pick.options(dict(self._state))
        columns = pick.columns
        rows = -(-len(options) // max(columns, 1))
        # Probe with the caption this pick will ACTUALLY draw, not a stand-in:
        # the colour pick's caption is two lines to the brightness pick's one,
        # and a one-line stand-in undercounted the chrome by exactly that and
        # overflowed the single-row grid by 3 px.
        sample = pick.caption(*options[0]) if options else ""
        edge = preview_edge(self._available(),
                            self._chrome(rows, sample), rows, columns)
        self._grid_host = QWidget()
        grid = QGridLayout(self._grid_host)
        # Zeroed so the fit has no unmeasured term: _chrome counts the layout
        # spacing between cells, and a stray default margin here would be the
        # difference between fitting and a scrollbar.
        grid.setContentsMargins(0, 0, 0, 0)
        for i, (name, value, img) in enumerate(options):
            grid.addWidget(self._panel(i, name, value, img, edge, pick),
                           i // columns, i % columns)
        old = self._scroll.takeWidget()
        self._scroll.setWidget(self._grid_host)
        if old is not None:
            old.deleteLater()      # or every re-render leaks a grid of previews
        # Sized explicitly, NOT by adjustSize(): a QScrollArea's size hint does
        # not grow with its contents, so asking the layout would open a window
        # smaller than the grid it just fitted and hand the user scrollbars on a
        # screen with room to spare. The scroll area is the backstop for a
        # screen too small for _PREVIEW_MIN, not the thing that picks the size.
        chrome = self._chrome(rows, sample)
        self.resize(chrome.width() + columns * edge,
                    chrome.height() + rows * edge)

    def _panel(self, index: int, name: str, value, img: AstroImage,
               edge: int, pick: "Pick") -> QWidget:
        """One preview. The PICTURE is the button.

        It started as an image above a "Use this one" button, which is a row of
        chrome per row of previews and was what tipped the grid off the bottom
        of a 1440 px screen. AstroWizard's equivalent has no button either: you
        click the one you want. Clicking the thing you are choosing between is
        the more obvious gesture anyway — the button only ever restated it.
        """
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        # A QPushButton rather than a clickable QLabel, so the picture keeps a
        # button's hover, focus ring and keyboard activation for free.
        shot = QPushButton()
        shot.setObjectName("pickPanel")
        shot.setFlat(True)
        shot.setCursor(Qt.CursorShape.PointingHandCursor)
        shot.setToolTip(f"Use {name}")
        # Rendered at _PREVIEW_MAX and scaled DOWN here, rather than rendered at
        # `edge`: the render is the expensive half and its cost does not change,
        # while scaling from the larger pixmap keeps a small panel sharp.
        pix = QPixmap.fromImage(to_qimage(img)).scaled(
            edge, edge, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        shot.setIcon(QIcon(pix))
        shot.setIconSize(pix.size())
        shot.setFixedSize(pix.width() + 8, pix.height() + 8)
        shot.clicked.connect(lambda _checked=False, i=index: self.choose(i))
        lay.addWidget(shot, alignment=Qt.AlignmentFlag.AlignCenter)
        # Name AND numbers, on ONE line: the name is a handle to think with, the
        # number is the slider value you land on and can nudge from, so a name
        # can never drift away from what it actually does.
        caption = QLabel(pick.caption(name, value, img))
        caption.setObjectName("stepDesc")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(caption)
        note = pick.caveats.get(value)
        if note:
            warn = QLabel(note)
            warn.setObjectName("pickCaveat")
            warn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            warn.setWordWrap(True)
            lay.addWidget(warn)
        return holder

    # --- fitting ---------------------------------------------------------
    def _available(self) -> QSize:
        """How much screen this dialog may occupy."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:                     # offscreen platform in tests
            return QSize(1280, 800)            # the size floor the app targets
        size = screen.availableGeometry().size()
        return QSize(int(size.width() * _SCREEN_USE),
                     int(size.height() * _SCREEN_USE))

    def _chrome(self, rows: int, caption_text: str = "Name") -> QSize:
        """Everything in the dialog that is not a preview, MEASURED.

        Estimating this is how it goes stale: the numbers below all come from
        the real widgets' size hints, so adding a line of explanatory text
        shrinks the previews to match instead of pushing the window off screen.
        """
        margins = self._root.contentsMargins()
        spacing = self._root.spacing()
        caption = QLabel(caption_text)
        caption.setObjectName("stepDesc")
        per_row = caption.sizeHint().height() + 8 + 2 * spacing
        if any(p.caveats for p in self._picks):
            per_row += caption.sizeHint().height() + spacing
        width = (margins.left() + margins.right()
                 + self._scroll.verticalScrollBar().sizeHint().width()
                 + (_COLUMNS + 1) * spacing)
        height = (margins.top() + margins.bottom()
                  + self._title.sizeHint().height()
                  + self._hint.heightForWidth(self._available().width())
                  + self._cancel.sizeHint().height()
                  + 4 * spacing
                  + rows * per_row)
        return QSize(width, height)


def _sky(img: AstroImage) -> float:
    """The background level this panel lands on — the number this whole feature
    turned out to be about. The 35th percentile, because sky dominates the
    frame and a plain median is pulled by any large object in it."""
    lum = to_rgb8(img).mean(axis=2) / 255.0
    return float(np.percentile(lum, 35))
