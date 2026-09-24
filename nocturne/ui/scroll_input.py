"""Telling a trackpad from a mouse wheel, for the two pan/zoom previews.

Both arrive as a QWheelEvent, and they mean different things. A wheel detent is
one deliberate zoom step. A two-finger swipe on a Mac trackpad is a STREAM of
small events — dozens per gesture, then more as momentum — and by macOS
convention it pans, as in Preview and Photos; pinch is what zooms. Treating the
stream as detents fired dozens of x1.25 steps per swipe, which is what made the
app unusable on a MacBook (TODO: "Trackpad zoom & pan").

The scroll PHASE is the only signal: a trackpad gesture is bracketed by
begin/update/end (and momentum), a wheel has none. Nothing else separates them
on macOS. Measured on Andreas' desktop mouse, 2026-09-24, from this module's own
trace: every wheel event arrived with `device=TouchPad`,
`source=MouseEventSynthesizedBySystem` and pixel deltas of 12-205 — and
`phase=NoScrollPhase`. The first version also trusted the device type, and it
turned his scroll wheel into a pan. Do not add the device type back.
A Magic Mouse reports phases, so it pans; Preview does the same with one.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QPointF, Qt

# --- TRACKPAD TEST BUILD ONLY — remove before merge --------------------------
# Nothing here can drive a real trackpad (macOS denies this terminal synthetic
# input), so the only evidence of what a MacBook actually sends is what the
# app writes down while Andreas uses it. One line per event, to its OWN file,
# ~/.nocturne/input-trace.log: a momentum swipe is ~100 events a second, which
# would roll the 2 MB main log over in minutes and push out the first swipes.
# Attached only once the app has configured its log (never under pytest, where
# it would write into the real home directory).
_TRACE = True
_TRACE_BYTES = 20_000_000
_trace_log = logging.getLogger("nocturne.input")
_trace_ready = False


def _attach_trace_file() -> bool:
    global _trace_ready
    if _trace_ready:
        return True
    from ..core import applog
    if not applog._configured:
        return False
    import logging.handlers
    import os
    path = os.path.join(os.path.dirname(applog.log_path()), "input-trace.log")
    h = logging.handlers.RotatingFileHandler(path, maxBytes=_TRACE_BYTES,
                                             backupCount=1, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s",
                                     "%Y-%m-%d %H:%M:%S"))
    _trace_log.addHandler(h)
    _trace_log.setLevel(logging.INFO)
    _trace_log.propagate = False
    _trace_ready = True
    return True


def trace(where: str, event, action: str) -> None:
    if not _TRACE:
        return
    try:
        if not _attach_trace_file():
            return
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
    return event.phase() != Qt.ScrollPhase.NoScrollPhase


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
