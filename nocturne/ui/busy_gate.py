"""Dim a surface's controls while it works, and give back exactly what it took.

One rule instead of a list. The main window used to name the buttons it gated,
then swept push buttons only — and every slider, dropdown, checkbox and the
curve editor stayed live while their step ran (audit 2026-10-05: a De-green
slider movable mid-split, values moved mid-Apply, a panel rebuilt mid-run never
swept at all). Sweeping every input type under a root is a rule that cannot go
stale as panels grow controls.

Only widgets that were ENABLED are disabled, and only those are restored: a
control that was legitimately off (Apply with GraXpert unconfigured) must not
come back on because an unrelated job finished. Whoever owns the controls
re-derives real enablement after `open()` either way.
"""
from __future__ import annotations

import shiboken6
from PySide6.QtWidgets import (QAbstractButton, QAbstractSlider, QAbstractSpinBox,
                               QComboBox, QLineEdit, QWidget)

from .curve_editor import CurveEditor

KEEP_LIVE = "busyGateKeepLive"          # dynamic property name; True → never disabled
INPUT_TYPES = (QAbstractSlider, QAbstractButton, QComboBox, QAbstractSpinBox, QLineEdit,
               CurveEditor)


def keep_live(widget: QWidget) -> QWidget:
    """Opt a widget out of every gate — Cancel and Close must work during the
    very job they exist to stop."""
    widget.setProperty(KEEP_LIVE, True)
    return widget


def _inputs(root: QWidget) -> list:
    found = [root] if isinstance(root, INPUT_TYPES) else []
    return found + [w for w in root.findChildren(QWidget) if isinstance(w, INPUT_TYPES)]


class BusyGate:
    """Disables every ENABLED input widget under the given roots, remembers exactly those,
    restores only those. Nesting-safe: close() while closed ADDS newly found widgets."""

    def __init__(self) -> None:
        self._taken: list = []
        self._closed = False

    @property
    def is_closed(self) -> bool:
        return self._closed

    def close(self, *roots: QWidget) -> None:
        """Adds to the record, never replaces it: a second sweep (a panel built
        while closed) replacing it lost the first sweep's widgets, which then
        stayed off for good."""
        self._closed = True
        for root in roots:
            if root is None or not shiboken6.isValid(root):
                continue
            for w in _inputs(root):
                if w.property(KEEP_LIVE) or not w.isEnabled():
                    continue
                w.setEnabled(False)
                if not any(w is t for t, _ in self._taken):
                    self._taken.append((w, w.window()))

    def open(self) -> None:
        """Gives back what close() took. A panel can be rebuilt while closed:
        the old one is detached at once and deleted later, so skip a widget
        that is gone or no longer in the window it was taken from — writing
        to a discarded panel is pointless at best, a use-after-free at worst."""
        taken, self._taken = self._taken, []
        self._closed = False
        for w, window in taken:
            if shiboken6.isValid(w) and w.window() is window:
                w.setEnabled(True)
