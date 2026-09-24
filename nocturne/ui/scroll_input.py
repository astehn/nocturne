"""Telling a trackpad from a mouse wheel, for the two pan/zoom previews.

Both arrive as a QWheelEvent, and they mean different things. A wheel detent is
one deliberate zoom step. A two-finger swipe on a Mac trackpad is a STREAM of
small events — dozens per gesture, then more as momentum — and by macOS
convention it pans, as in Preview and Photos; pinch is what zooms. Treating the
stream as detents fired dozens of x1.25 steps per swipe, which is what made the
app unusable on a MacBook (TODO: "Trackpad zoom & pan").

On macOS the scroll PHASE is the only signal: a trackpad gesture is bracketed
by begin/update/end (and momentum), a wheel has none. Nothing else separates
them there. Measured on Andreas' desktop mouse, 2026-09-24, with an input trace
in a test build: every wheel event arrived with `device=TouchPad`,
`source=MouseEventSynthesizedBySystem` and pixel deltas of 12-205 — and
`phase=NoScrollPhase`. The first version also trusted the device type, and it
turned his scroll wheel into a pan. Do not trust the device type on macOS.
A Magic Mouse reports phases, so it pans; Preview does the same with one.

Linux (X11) is the other way round, measured on the build laptop the same
evening: a two-finger scroll carries NO phase — 211 events went down the wheel
path and zoomed 0.69 -> 0.145 in a second — but the devices are labelled
honestly, the Alps touchpad as TouchPad and a Logitech receiver as Mouse with
exactly +-120 per click. So off macOS, the label counts too.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QInputDevice

_MACOS = sys.platform == "darwin"


def is_trackpad_scroll(event) -> bool:
    if event.phase() != Qt.ScrollPhase.NoScrollPhase:
        return True
    if _MACOS:
        return False
    dev = event.pointingDevice()
    return dev is not None and dev.type() == QInputDevice.DeviceType.TouchPad


def pan_delta(event) -> QPointF:
    """How far the content should move, in screen pixels, following the fingers.

    macOS has already applied the user's natural-scrolling setting to both
    deltas, so they are used as they come. Angle delta is the fallback for a
    platform that sends a phased scroll without pixel deltas; 1/8 of a degree
    per pixel is Qt's own scroll-area conversion."""
    px = event.pixelDelta()
    if not px.isNull():
        return QPointF(px)
    ang = event.angleDelta()
    return QPointF(ang.x() / 8.0, ang.y() / 8.0)
