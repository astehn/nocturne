"""Apply, carrying its own status — so "not applied yet" lives in the thing you
press instead of a line that appeared and disappeared and moved the panel.

The label existed for a reason: Next used to drop unapplied changes silently
(step-commit work, 2026-09-11), and Andreas then asked for MORE prominence.
Here it is inside the button, in both trial looks he is choosing between
(2026-09-25): A = a second line, B = a chip. The losing look is removed before
merge. One colour rule everywhere: green = pressing this will change your image.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QPushButton

from .theme import BG_1, BG_2, SUCCESS, TEXT, TEXT_DIM, TEXT_FAINT, WARNING

STATES = ("pending", "not_run", "applied", "no_change", "busy")
_GREEN = {"pending", "not_run"}
_STATUS = {
    "pending": "● changes not applied",
    "not_run": "not run yet",
    "applied": "✓ applied",
    "no_change": "no changes",
    "busy": "",
}
_CHIP = {"pending": "not applied", "not_run": "not run", "applied": "✓ applied",
         "no_change": "no changes", "busy": ""}

# Review Focus 1: every chip in look B needs its OWN opaque fill — a chip with
# no fill just puts its text directly on the button body, and `not_run` sits
# on the SUCCESS green body the same as `pending`; TEXT_DIM-on-SUCCESS
# measured 1.27:1 there (pixel-sampled). (fill, text) below are all real
# theme.py tokens, chosen so `pending` is the loudest (amber, the only warm
# colour) and every pair clears WCAG 4.5:1 — verified by computing relative
# luminance from these exact hex values:
#   WARNING/#1a1d23 (pending)  8.67:1
#   #052611/TEXT     (not_run) 13.03:1  — #052611 is theme.py's own
#                                          on-green ink (QPushButton#primary's
#                                          `color:`), reused here as a dark
#                                          fill so not_run reads as "still the
#                                          green family" without competing
#                                          with pending's amber.
#   BG_2/SUCCESS      (applied) 5.81:1
#   BG_1/TEXT_DIM     (no_change) 5.12:1
# (busy's chip text is "" — nothing is painted, so no pair is needed.)
_ON_GREEN_INK = "#052611"
_DARK_INK = "#1a1d23"
_CHIP_STYLE = {
    "pending": (WARNING, _DARK_INK),
    "not_run": (_ON_GREEN_INK, TEXT),
    "applied": (BG_2, SUCCESS),
    "no_change": (BG_1, TEXT_DIM),
}

# theme.py's `QPushButton { padding: 8px 14px; }` (nocturne/ui/theme.py) is the
# only padding rule that reaches this button (QPushButton#primary does not
# override it). Measured directly against a real primary button's sizeHint
# under that stylesheet: fm.height() 17px -> sizeHint height 33px, i.e.
# fm.height() + 16 — the vertical 8px+8px, border excluded (the base
# QPushButton#primary rule is border: none; only the [pending="false"] rule
# adds a 1px border, and this button fixes its own height regardless of that).
_VPAD = 16
# The horizontal 14px half of that same padding rule, used as the label's left
# inset in look B so the text lines up with every other button's text inset.
_LABEL_INSET = 14
# Tuned, not derived from theme.py (chips are not a themed widget there): the
# gap between the label text and the chip, and the chip's own internal
# left/right text padding.
_CHIP_GAP = 10
_CHIP_HPAD = 9
_CHIP_RIGHT_MARGIN = 6


class ApplyButton(QPushButton):
    def __init__(self, label: str, look: str = "A", parent=None) -> None:
        super().__init__("", parent)
        self.setObjectName("primary")
        self._label = label
        self._state = "not_run"
        self._look = "A"
        self.set_look(look)
        self.set_state("not_run")

    # --- API ---
    def text(self) -> str:
        """The button paints its own text; callers that ask .text() for the
        step name (as provenance/help code elsewhere does) still get it."""
        return self._label

    def label_text(self) -> str:
        return self._label

    def status_text(self) -> str:
        return _STATUS[self._state]

    def state(self) -> str:
        return self._state

    def look(self) -> str:
        return self._look

    def set_look(self, look: str) -> None:
        if look not in ("A", "B"):
            raise ValueError(look)
        self._look = look
        fm = self.fontMetrics()
        if look == "B":
            # Today's button height: one line of the button font plus the
            # stylesheet's real vertical padding.
            height = fm.height() + _VPAD
        else:
            # Two real lines: the bold label line at the button's own font,
            # plus the smaller status line measured at ITS font (not guessed
            # off the label line's metrics), with a 1px gap between them.
            _, small_font = self._fonts()
            small_fm = QFontMetrics(small_font)
            height = fm.height() + small_fm.height() + 1 + _VPAD
        self.setFixedHeight(height)
        self.update()

    def set_state(self, state: str) -> None:
        if state not in STATES:
            raise ValueError(state)
        self._state = state
        green = state in _GREEN
        if self.property("pending") != ("true" if green else "false"):
            self.setProperty("pending", "true" if green else "false")
            self.style().unpolish(self); self.style().polish(self)
        self.setEnabled(state not in ("no_change", "busy"))
        self.setToolTip(f"{self._label} — {self.status_text()}" if self.status_text() else self._label)
        self.update()

    # --- shared geometry/fonts: paintEvent and label_fits() must never
    # measure with different fonts than they draw with (Review Focus 2: they
    # used to — label measured in the regular font but drawn bold, chip
    # measured at full size but drawn small — and the two errors happened to
    # cancel for the three names actually tested). ---
    def _fonts(self) -> tuple[QFont, QFont]:
        """(bold label font, small chip/status font), both derived from this
        widget's OWN current font so a font change is honoured everywhere."""
        bold = self.font(); bold.setBold(True)
        small = self.font(); small.setPointSizeF(max(8.0, small.pointSizeF() - 2))
        return bold, small

    def _chip_rect(self, r: QRect, small_fm: QFontMetrics) -> QRect | None:
        """Look B's chip pill, in `r`'s coordinates — None when the current
        state paints no chip (busy)."""
        chip = _CHIP[self._state]
        if not chip:
            return None
        cw = small_fm.horizontalAdvance(chip) + 2 * _CHIP_HPAD
        return QRect(r.right() - cw - _CHIP_RIGHT_MARGIN, r.center().y() - 10, cw, 20)

    def chip_geometry(self) -> QRect | None:
        """The chip's rect at the button's current size/state/font — public
        so a test can sample the ACTUAL painted pixels at the exact rect
        paintEvent draws into, rather than trust this class's own numbers."""
        _, small_font = self._fonts()
        return self._chip_rect(self.rect(), QFontMetrics(small_font))

    def label_fits(self) -> bool:
        """For look B: the name fits beside the chip without clipping."""
        if self._look != "B":
            return True
        bold_font, small_font = self._fonts()
        bold_fm = QFontMetrics(bold_font)
        small_fm = QFontMetrics(small_font)
        chip = _CHIP[self._state]
        chip_w = (small_fm.horizontalAdvance(chip) + 2 * _CHIP_HPAD) if chip else 0
        needed = _LABEL_INSET + bold_fm.horizontalAdvance(self._label) + _CHIP_GAP + chip_w + _CHIP_RIGHT_MARGIN
        return needed <= self.width()

    # --- the stylesheet arrives (and re-arrives) after construction; a fixed
    # height computed once in __init__ can go stale (Review Focus 3: 45px at
    # construction, 47px once the app stylesheet is actually applied). Same
    # pattern as Stepper._fit_height (nocturne/ui/stepper.py): recompute on
    # style/font change and on first polish. ---
    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().changeEvent(event)
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self.set_look(self._look)

    def event(self, event) -> bool:  # noqa: A003 (Qt override)
        result = super().event(event)
        if event.type() == QEvent.Type.Polish:
            self.set_look(self._look)
        return result

    # --- painting: the stylesheet draws the button body; we draw the text ---
    def paintEvent(self, event) -> None:
        super().paintEvent(event)                 # background/border from theme.py
        p = QPainter(self)
        r = self.rect()
        fm = self.fontMetrics()
        bold_font, small_font = self._fonts()
        small_fm = QFontMetrics(small_font)
        # palette().buttonText() tracks theme.py's #052611 (green states) or
        # TEXT (plain states) once the "pending" property has been polished —
        # legible against both the green and the plain body. Disabled states
        # (no_change/busy) fall back to TEXT_FAINT explicitly rather than
        # trusting a stylesheet re-polish that setEnabled() may not trigger.
        fg = self.palette().buttonText().color() if self.isEnabled() else QColor(TEXT_FAINT)
        if self._look == "A":
            top = QRect(r.x(), r.y() + 5, r.width(), fm.height())
            p.setPen(fg)
            p.setFont(bold_font)
            p.drawText(top, Qt.AlignmentFlag.AlignCenter, self._label)
            p.setFont(small_font)
            p.setPen(QColor(SUCCESS) if self._state == "applied" else fg)
            bottom = QRect(r.x(), top.bottom() + 1, r.width(), r.height() - top.height() - 6)
            p.drawText(bottom, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       self.status_text())
        else:
            p.setFont(bold_font); p.setPen(fg)
            p.drawText(r.adjusted(_LABEL_INSET, 0, 0, 0),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._label)
            cr = self._chip_rect(r, small_fm)
            if cr is not None:
                chip = _CHIP[self._state]
                fill, text_colour = _CHIP_STYLE[self._state]
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setBrush(QColor(fill)); p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(cr, 10, 10)
                p.setPen(QColor(text_colour))
                p.setFont(small_font)
                p.drawText(cr, Qt.AlignmentFlag.AlignCenter, chip)
        p.end()
