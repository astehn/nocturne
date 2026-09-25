"""Apply, carrying its own status — so "not applied yet" lives in the thing you
press instead of a line that appeared and disappeared and moved the panel.

The label existed for a reason: Next used to drop unapplied changes silently
(step-commit work, 2026-09-11), and Andreas then asked for MORE prominence.
Here it is inside the button, in both trial looks he is choosing between
(2026-09-25): A = a second line, B = a chip. The losing look is removed before
merge. One colour rule everywhere: green = pressing this will change your image.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QPushButton

from .theme import SUCCESS, TEXT_DIM, TEXT_FAINT, WARNING

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
            self.setFixedHeight(fm.height() + _VPAD)
        else:
            # Two real lines: the bold label line at the button's own font,
            # plus the smaller status line measured at ITS font (not guessed
            # off the label line's metrics), with a 1px gap between them.
            small = self.font()
            small.setPointSizeF(max(8.0, small.pointSizeF() - 2))
            small_fm = QFontMetrics(small)
            self.setFixedHeight(fm.height() + small_fm.height() + 1 + _VPAD)
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

    def label_fits(self) -> bool:
        """For look B: the name fits beside the chip without clipping."""
        if self._look != "B":
            return True
        fm = self.fontMetrics()
        chip = _CHIP[self._state]
        chip_w = (fm.horizontalAdvance(chip) + 2 * _CHIP_HPAD) if chip else 0
        needed = _LABEL_INSET + fm.horizontalAdvance(self._label) + _CHIP_GAP + chip_w + _CHIP_RIGHT_MARGIN
        return needed <= self.width()

    # --- painting: the stylesheet draws the button body; we draw the text ---
    def paintEvent(self, event) -> None:
        super().paintEvent(event)                 # background/border from theme.py
        p = QPainter(self)
        r = self.rect()
        fm = self.fontMetrics()
        # palette().buttonText() tracks theme.py's #052611 (green states) or
        # TEXT (plain states) once the "pending" property has been polished —
        # legible against both the green and the plain body. Disabled states
        # (no_change/busy) fall back to TEXT_FAINT explicitly rather than
        # trusting a stylesheet re-polish that setEnabled() may not trigger.
        fg = self.palette().buttonText().color() if self.isEnabled() else QColor(TEXT_FAINT)
        if self._look == "A":
            top = QRect(r.x(), r.y() + 5, r.width(), fm.height())
            p.setPen(fg)
            f = self.font(); f.setBold(True); p.setFont(f)
            p.drawText(top, Qt.AlignmentFlag.AlignCenter, self._label)
            small = self.font(); small.setPointSizeF(max(8.0, small.pointSizeF() - 2)); p.setFont(small)
            p.setPen(QColor(SUCCESS) if self._state == "applied" else fg)
            bottom = QRect(r.x(), top.bottom() + 1, r.width(), r.height() - top.height() - 6)
            p.drawText(bottom, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       self.status_text())
        else:
            f = self.font(); f.setBold(True); p.setFont(f); p.setPen(fg)
            p.drawText(r.adjusted(_LABEL_INSET, 0, 0, 0),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._label)
            chip = _CHIP[self._state]
            if chip:
                cw = fm.horizontalAdvance(chip) + 2 * _CHIP_HPAD
                cr = QRect(r.right() - cw - _CHIP_RIGHT_MARGIN, r.center().y() - 10, cw, 20)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                if self._state == "pending":
                    p.setBrush(QColor(WARNING)); p.setPen(Qt.PenStyle.NoPen)
                    p.drawRoundedRect(cr, 10, 10); p.setPen(QColor("#1a1d23"))
                else:
                    p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QColor(TEXT_DIM))
                    if self._state == "applied":
                        p.setPen(QColor(SUCCESS))
                small = self.font(); small.setPointSizeF(max(8.0, small.pointSizeF() - 2)); p.setFont(small)
                p.drawText(cr, Qt.AlignmentFlag.AlignCenter, chip)
        p.end()
