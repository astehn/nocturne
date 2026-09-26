"""Apply, carrying its own status — so "not applied yet" lives in the thing you
press instead of a line that appeared and disappeared and moved the panel.

The label existed for a reason: Next used to drop unapplied changes silently
(step-commit work, 2026-09-11), and Andreas then asked for MORE prominence.
The button paints two lines: the bold label, and a status line under it. One
colour rule everywhere: green = pressing this will change your image.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QLabel, QPushButton

from .theme import SUCCESS, TEXT_FAINT

STATES = ("pending", "not_run", "applied", "no_change", "busy")
_GREEN = {"pending", "not_run"}
# States in which pressing would do nothing (or nothing yet): the button is off.
# `applied` is off too, but only when the caller has VERIFIED that the controls
# are exactly what was committed (`set_state(..., unchanged=True)`; Andreas,
# 2026-09-25 23:27): pressing then re-ran the tool on the same image and logged
# an identical second line — minutes of RC-Astro for Noise Reduction. An
# unverified `applied` stays live (ruling R13): failing closed blocked real edits
# the comparison could not see, failing open costs at most an identical re-run.
_OFF = {"no_change", "busy"}
# No "busy" entries: busy keeps the previous state's words (`_shown`, R9).
_STATUS = {
    "pending": "● changes not applied",
    "not_run": "not run yet",
    "applied": "✓ applied",
    "no_change": "no changes",
}

# theme.py's `QPushButton { padding: 8px 14px; }` (nocturne/ui/theme.py) is the
# only padding rule that reaches this button (QPushButton#primary does not
# override it). Measured directly against a real primary button's sizeHint
# under that stylesheet: fm.height() 17px -> sizeHint height 33px, i.e.
# fm.height() + 16 — the vertical 8px+8px, border excluded (the base
# QPushButton#primary rule is border: none; only the [pending="false"] rule
# adds a 1px border, and this button fixes its own height regardless of that).
_VPAD = 16


class ApplyButton(QPushButton):
    def __init__(self, label: str, parent=None) -> None:
        super().__init__("", parent)
        self.setObjectName("primary")
        self._label = label
        self._state = "not_run"
        # What the words say. Busy (spec §4: "unchanged text") keeps the last
        # real state's status — only the enablement changes.
        self._shown = "not_run"
        self._available = True
        self._desc_size = self._read_desc_size()
        self._fit_height()
        self.set_state("not_run")

    # --- API ---
    def text(self) -> str:
        """The button paints its own text; callers that ask .text() for the
        step name (as provenance/help code elsewhere does) still get it."""
        return self._label

    def label_text(self) -> str:
        return self._label

    def status_text(self) -> str:
        return _STATUS[self._shown]

    def state(self) -> str:
        return self._state

    def _fit_height(self) -> None:
        """The button's fixed height: two real lines — the bold label at the
        button's own font, plus the status line measured at ITS font (the
        description's size, not guessed off the label line's metrics), 1px
        apart — plus the stylesheet's real vertical padding."""
        self._desc_size = self._read_desc_size()
        fm = self.fontMetrics()
        _, small_font = self._fonts()
        small_fm = QFontMetrics(small_font)
        height = fm.height() + small_fm.height() + 1 + _VPAD
        self.setFixedHeight(height)
        self.update()

    def set_state(self, state: str, *, unchanged: bool = False) -> None:
        """`unchanged` is only for "applied": True when the caller has verified
        the controls equal the commit, which is what switches the button off."""
        if state not in STATES:
            raise ValueError(state)
        if unchanged and state != "applied":
            raise ValueError(f"unchanged only qualifies 'applied', not {state!r}")
        self._state = state
        if state != "busy":
            self._shown = state
        green = state in _GREEN
        if self.property("pending") != ("true" if green else "false"):
            self.setProperty("pending", "true" if green else "false")
            self.style().unpolish(self); self.style().polish(self)
        super().setEnabled(self._available and state not in _OFF and not unchanged)
        self.setToolTip(f"{self._label} — {self.status_text()}" if self.status_text() else self._label)
        self.update()

    # --- enablement: two independent reasons to be off. The STATE says whether
    # pressing would do anything (no_change, busy); the caller's own
    # setEnabled says whether the tool can run at all (GraXpert unconfigured,
    # a star split still running, no crop box yet). Let set_state write
    # enablement outright and a refreshed "not_run" switched on an Apply whose
    # tool is missing; so the caller's flag is remembered and set_state only
    # ever narrows it. An explicit setEnabled still takes effect at once, as Qt
    # callers expect, until the next set_state.
    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 (Qt API)
        self._available = bool(enabled)
        super().setEnabled(bool(enabled))

    def setDisabled(self, disabled: bool) -> None:  # noqa: N802 (Qt API)
        self.setEnabled(not disabled)

    # --- shared geometry/fonts: paintEvent and _fit_height must never
    # measure with different fonts than they draw with (Review Focus 2: they
    # used to — the label measured in the regular font but drawn bold — and
    # the two errors happened to cancel for the three names actually tested). ---
    def _fonts(self) -> tuple[QFont, QFont]:
        """(bold label font, status font). The label follows this widget's
        own font; the status line is drawn at the step description's size
        (`_desc_size`), refreshed with the height in `_fit_height`."""
        bold = self.font(); bold.setBold(True)
        # Normal weight, not the button's inherited 600: two equally heavy
        # lines in one ink read as two headlines (Andreas, 2026-09-26). The
        # hierarchy comes from weight, not a lighter ink — on the green fill a
        # lighter ink would drop under 4.5:1.
        small = self.font(); small.setWeight(QFont.Weight.Normal)
        px, pt = self._desc_size
        if px > 0:
            small.setPixelSize(px)
        elif pt > 0:
            small.setPointSizeF(pt)
        return bold, small

    @staticmethod
    def _read_desc_size() -> tuple[int, float]:
        """The size `QLabel#stepDesc` gets from whatever stylesheet is live, as
        (pixelSize, pointSizeF) — one of them is -1, as Qt reports it.

        D1 (Andreas, 2026-09-26): the status used to be the button font minus
        2 pt, floored at 8. Under the app stylesheet the button font is set in
        PIXELS (14px), so pointSizeF() is -1 and the floor won: 8 pt, about
        7 px of ink in his real window — "very hard to read regardless of
        button style or screen size". The description under the step title is
        the text he reads anyway, so the status matches it. Read from a probe
        label, not copied from theme.py, so it follows the stylesheet (and the
        bare style, where it is simply the app font)."""
        probe = QLabel()
        probe.setObjectName("stepDesc")
        probe.ensurePolished()
        f = probe.font()
        return f.pixelSize(), f.pointSizeF()

    # --- the stylesheet arrives (and re-arrives) after construction; a fixed
    # height computed once in __init__ can go stale (Review Focus 3: 45px at
    # construction, 47px once the app stylesheet is actually applied). Same
    # pattern as Stepper._fit_height (nocturne/ui/stepper.py): recompute on
    # style/font change and on first polish. ---
    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().changeEvent(event)
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self._fit_height()

    def event(self, event) -> bool:  # noqa: A003 (Qt override)
        result = super().event(event)
        if event.type() == QEvent.Type.Polish:
            self._fit_height()
        return result

    # --- painting: the stylesheet draws the button body; we draw the text ---
    def paintEvent(self, event) -> None:
        super().paintEvent(event)                 # background/border from theme.py
        p = QPainter(self)
        r = self.rect()
        fm = self.fontMetrics()
        bold_font, small_font = self._fonts()
        # palette().buttonText() tracks theme.py's #052611 (green states) or
        # TEXT (plain states) once the "pending" property has been polished —
        # legible against both the green and the plain body. Disabled states
        # (no_change, busy, an unchanged applied) fall back to TEXT_FAINT
        # explicitly rather than trusting a stylesheet re-polish that
        # setEnabled() may not trigger.
        fg = self.palette().buttonText().color() if self.isEnabled() else QColor(TEXT_FAINT)
        top = QRect(r.x(), r.y() + 5, r.width(), fm.height())
        p.setPen(fg)
        p.setFont(bold_font)
        p.drawText(top, Qt.AlignmentFlag.AlignCenter, self._label)
        p.setFont(small_font)
        # SUCCESS only while pressable: a disabled "✓ applied" is plain and
        # dim (spec §4), or its green reads as "press me".
        p.setPen(QColor(SUCCESS) if self._state == "applied" and self.isEnabled() else fg)
        bottom = QRect(r.x(), top.bottom() + 1, r.width(), r.height() - top.height() - 6)
        p.drawText(bottom, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   self.status_text())
        p.end()
