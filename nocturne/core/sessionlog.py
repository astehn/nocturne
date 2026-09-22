"""What Nocturne did this session, for a support ticket.

Its own file, deliberately NOT `nocturne.log`. That one is drizzle's phase
timings (`stacking/drizzle_stack.py` is its only writer) and is not part of a
support report. Andreas, 2026-09-22, having asked twice: *"i dont care really
about the number of files i care about getting the information i actually
need."*

TWO SESSIONS ARE KEPT, and the reason is the whole design. Deleting at quit was
proposed and rejected: the sequence is always app dies -> user relaunches ->
THEN they report, so a quit-wipe hands every crash report a fresh, healthy
session. The Share segfault of 2026-09-21 is the worked example. It is also the
ordinary human sequence — something goes wrong, the app is closed in
irritation, reopened later, and only then reported.
"""
from __future__ import annotations

import os
import threading

# ~1 MB. A step line is about 80 bytes and a busy session is a few hundred
# lines (Andreas's 16-step session was 694 bytes of history), so this is three
# orders of magnitude of headroom -- it exists to bound a pathological case (a
# tool looping on stderr), not to trim normal use.
MAX_BYTES = 1_000_000

# Every filesystem call here is wrapped in this pair rather than OSError alone.
# ValueError is not a theoretical extra: a path carrying a NUL byte raises
# `ValueError: embedded null character in path` from os.makedirs, before any
# OSError can happen. A log is a diagnostic, never a reason for the app to
# misbehave, so the contract is "never raises" and not "never raises OSError".
_CANNOT = (OSError, ValueError)

_lock = threading.Lock()
_active: str | None = None


def _dir(home: str | None) -> str:
    return os.path.join(home if home is not None else os.path.expanduser("~"),
                        ".nocturne")


def session_path(home: str | None = None) -> str:
    return os.path.join(_dir(home), "session.log")


def previous_path(home: str | None = None) -> str:
    return os.path.join(_dir(home), "session.prev.log")


def start_session(home: str | None = None) -> str | None:
    """Rotate the last session aside and begin a new one.

    Returns the path in use, or None if it could not be opened. Never raises:
    a log file is a diagnostic, never a reason for the app not to start.
    """
    global _active
    target, prev = session_path(home), previous_path(home)
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.exists(target):
            os.replace(target, prev)      # atomic; drops the one before it
        with open(target, "w", encoding="utf-8"):
            pass
    except _CANNOT:
        _active = None
        return None
    _active = target
    return target


def write(line: str) -> None:
    """Append one line. Never raises, for the reason in start_session."""
    if _active is None:
        return
    with _lock:
        try:
            with open(_active, "a", encoding="utf-8") as fh:
                fh.write(line.rstrip("\n") + "\n")
            if os.path.getsize(_active) > MAX_BYTES:
                _trim(_active)
        except _CANNOT:
            return


def _trim(path: str) -> None:
    """Drop the OLDEST lines. The interesting part of a log is what happened
    last, so truncating the tail would discard the failure and keep the
    startup."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        keep = text[-(MAX_BYTES // 2):]
        keep = keep[keep.find("\n") + 1:]          # never a half line
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(keep)
    except _CANNOT:
        return


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except _CANNOT:
        return ""


def read_session(home: str | None = None) -> str:
    return _read(session_path(home))


def read_previous(home: str | None = None) -> str:
    return _read(previous_path(home))
