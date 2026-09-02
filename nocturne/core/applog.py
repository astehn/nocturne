"""A log file on disk, because a packaged app has no console.

The stacking code has logged its phase timings since 2026-09-01
(`drizzle_stack` calls `logging.getLogger("nocturne.drizzle").info(...)` around
each pass). Nothing ever configured a handler for it, and Python's last-resort
handler only emits WARNING and above — so every one of those lines was dropped.
A 1233-frame NGC 281 drizzle ran overnight on 2026-09-02, took roughly four
times the estimate, and produced no record of where the time went.

Run from a terminal the messages would at least reach stderr with a
basicConfig; run as Nocturne.app there is no stderr to reach. A file is the
only destination that works in the case that actually matters — an overnight
run the user is not watching.

Deliberately small: one rotating file, INFO and above, no configuration UI.
This exists to answer "which phase was slow", not to become a logging system.
"""
from __future__ import annotations

import logging
import logging.handlers
import os

_MAX_BYTES = 2_000_000      # ~2 MB, a few long runs' worth
_BACKUPS = 2

_configured = False


def log_path(home: str | None = None) -> str:
    home = home if home is not None else os.path.expanduser("~")
    return os.path.join(home, ".nocturne", "nocturne.log")


def configure_logging(path: str | None = None) -> str | None:
    """Attach a rotating file handler to the `nocturne` logger tree.

    Returns the path in use, or None if it could not be opened — a log file is
    a diagnostic, never a reason for the app not to start.

    Idempotent: called once from main(), but a second call must not attach a
    second handler and write everything twice.
    """
    global _configured
    if _configured:
        return log_path() if path is None else path
    target = path or log_path()
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            target, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
    root = logging.getLogger("nocturne")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # Do NOT propagate to the root logger: under pytest that reaches caplog and
    # any handler the test runner installed, which turns a diagnostic into
    # noise in every unrelated test's output.
    root.propagate = False
    _configured = True
    return target
