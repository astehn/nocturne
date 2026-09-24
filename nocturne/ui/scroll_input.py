"""Telling a trackpad from a mouse wheel, for the two pan/zoom previews.

Both arrive as a QWheelEvent, and they mean different things. A wheel detent is
one deliberate zoom step. A two-finger swipe on a Mac trackpad is a STREAM of
small events — dozens per gesture, then more as momentum — and by macOS
convention it pans, as in Preview and Photos; pinch is what zooms. Treating the
stream as detents fired dozens of x1.25 steps per swipe, which is what made the
app unusable on a MacBook (TODO: "Trackpad zoom & pan").

`pixelDelta()` and `source()` do not separate the two on macOS: smooth-scrolling
mice report pixel deltas too, and the source is "not synthesized" for both. The
scroll PHASE does — a trackpad gesture is bracketed by begin/update/end (and
momentum), a detent wheel has none. The device type is checked as well because
it costs nothing, and some platforms set it where they omit the phase. A Magic
Mouse also reports phases, so it pans; Preview does the same with one.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QInputDevice

# One wheel detent, in Qt's eighths of a degree.
WHEEL_DETENT = 120.0

# --- TRACKPAD TEST BUILD ONLY — remove before merge --------------------------
# Nothing here can drive a real trackpad (macOS denies this terminal synthetic
# input), so the only evidence of what a MacBook actually sends is what the
# app writes down while Andreas uses it. One line per event, to
# ~/.nocturne/nocturne.log.
_TRACE = True
_trace_log = logging.getLogger("nocturne.input")


def trace(where: str, event, action: str) -> None:
    if not _TRACE:
        return
    try:
        dev = event.pointingDevice()
        dev_type = dev.type().name if dev is not None else "none"
        if hasattr(event, "angleDelta"):
            _trace_log.info(
                "%s wheel phase=%s device=%s pixel=(%d,%d) angle=(%d,%d) "
                "inverted=%s source=%s -> %s",
                where, event.phase().name, dev_type,
                event.pixelDelta().x(), event.pixelDelta().y(),
                event.angleDelta().x(), event.angleDelta().y(),
                event.inverted(), event.source().name, action)
        else:
            _trace_log.info("%s gesture %s value=%.4f device=%s -> %s",
                            where, event.gestureType().name, event.value(),
                            dev_type, action)
    except Exception:                                   # noqa: BLE001
        pass    # a diagnostic must never break input handling
# ------------------------------------------------------------------------------


def is_trackpad_scroll(event) -> bool:
    if event.phase() != Qt.ScrollPhase.NoScrollPhase:
        return True
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


def wheel_steps(event) -> float:
    """Detents turned, signed; fractional for a high-resolution wheel."""
    return event.angleDelta().y() / WHEEL_DETENT
