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

from dataclasses import dataclass
from typing import Callable

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QPixmap
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


def preview_edge(available: QSize, chrome: QSize, rows: int) -> int:
    """The largest square one preview may occupy for the grid to fit on screen.

    The dialog first shipped sizing itself from `_PREVIEW_MAX` alone: six 640 px
    panels in a 3x2 grid is about 1950x1450 before chrome, which overflowed a
    large monitor and would have been unusable on the 1280x800 floor this app
    targets. `chrome` is MEASURED from the real widgets rather than estimated,
    so this cannot drift the next time the dialog gains a line of text.
    """
    per_col = (available.width() - chrome.width()) // max(_COLUMNS, 1)
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
    options: Callable[[dict], list[tuple[str, float, AstroImage]]]


def brightness_pick(base: AstroImage) -> Pick:
    """How bright should the background be? The only pick today."""
    small = downscale(base, _PREVIEW_MAX)      # once, not per panel

    def options(_state: dict):
        return [(name, amount, apply_stretch(small, amount))
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
        rows = -(-len(options) // _COLUMNS)
        edge = preview_edge(self._available(), self._chrome(rows), rows)
        self._grid_host = QWidget()
        grid = QGridLayout(self._grid_host)
        for i, (name, value, img) in enumerate(options):
            grid.addWidget(self._panel(i, name, value, img, edge),
                           i // _COLUMNS, i % _COLUMNS)
        old = self._scroll.takeWidget()
        self._scroll.setWidget(self._grid_host)
        if old is not None:
            old.deleteLater()      # or every re-render leaks a grid of previews
        # Sized explicitly, NOT by adjustSize(): a QScrollArea's size hint does
        # not grow with its contents, so asking the layout would open a window
        # smaller than the grid it just fitted and hand the user scrollbars on a
        # screen with room to spare. The scroll area is the backstop for a
        # screen too small for _PREVIEW_MIN, not the thing that picks the size.
        chrome = self._chrome(rows)
        self.resize(chrome.width() + _COLUMNS * edge,
                    chrome.height() + rows * edge)

    def _panel(self, index: int, name: str, value: float,
               img: AstroImage, edge: int) -> QWidget:
        holder = QWidget()
        lay = QVBoxLayout(holder)
        shot = QLabel()
        # Rendered at _PREVIEW_MAX and scaled DOWN here, rather than rendered at
        # `edge`: the render is the expensive half and its cost does not change,
        # while scaling from the larger pixmap keeps a small panel sharp.
        shot.setPixmap(QPixmap.fromImage(to_qimage(img)).scaled(
            edge, edge, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        shot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(shot)
        # Name AND numbers. The name is a handle to think with; the number is
        # the slider value you land on and can nudge from, so a name can never
        # drift away from what it actually does.
        caption = QLabel(f"{name}\n{value:.2f} · sky {_sky(img):.3f}")
        caption.setObjectName("stepDesc")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(caption)
        button = QPushButton("Use this one")
        button.clicked.connect(lambda _checked=False, i=index: self.choose(i))
        lay.addWidget(button)
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

    def _chrome(self, rows: int) -> QSize:
        """Everything in the dialog that is not a preview, MEASURED.

        Estimating this is how it goes stale: the numbers below all come from
        the real widgets' size hints, so adding a line of explanatory text
        shrinks the previews to match instead of pushing the window off screen.
        """
        margins = self._root.contentsMargins()
        spacing = self._root.spacing()
        caption = QLabel("Name\n0.00 \u00b7 sky 0.000")
        caption.setObjectName("stepDesc")
        per_row = (caption.sizeHint().height()
                   + QPushButton("Use this one").sizeHint().height()
                   + 3 * spacing)
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
