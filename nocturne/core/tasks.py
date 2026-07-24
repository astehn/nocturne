from __future__ import annotations

import os
import signal
import threading


class Cancelled(BaseException):
    """Raised to unwind an operation the user cancelled (never an error).

    Deliberately a BaseException, not an Exception, so it propagates cleanly
    through the app's pervasive `except Exception` fallback/resilience handlers
    (a cancel must never be swallowed and turned into a silent fallback). The
    worker (ui/worker.py) catches it explicitly and routes it to a clean stop."""


def kill_process(proc) -> None:
    """Terminate a Popen and its process group; never raises."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)     # POSIX: whole group
    except (AttributeError, ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate()
        except Exception:
            pass


class CancelToken:
    def __init__(self) -> None:
        self._ev = threading.Event()
        self._proc = None

    @property
    def cancelled(self) -> bool:
        return self._ev.is_set()

    def check(self) -> None:
        if self._ev.is_set():
            raise Cancelled()

    def bind_process(self, proc) -> None:
        self._proc = proc
        if self._ev.is_set():
            kill_process(proc)

    def cancel(self) -> None:
        self._ev.set()
        if self._proc is not None:
            kill_process(self._proc)


_ambient = threading.local()


def set_ambient(token: "CancelToken | None") -> None:
    _ambient.token = token


def clear_ambient() -> None:
    _ambient.token = None


def current() -> "CancelToken | None":
    return getattr(_ambient, "token", None)
