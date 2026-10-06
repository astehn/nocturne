"""Live previews off the UI thread, newest slider position wins (spec F1/F2,
2026-10-06).

Every live-preview step computed its effect inside the debounce timer, on the
UI thread: on a 33 MP drizzle one Recover Core tick froze the window for 7 s,
and nothing — not the slider, not a ring — could move meanwhile. Here the
effect runs on the pool and only the paint comes back.

One job at a time: a request while one runs replaces the one waiting, so a
drag of twenty ticks computes the first and the last, never the eighteen in
between. A result is painted only if its key is still the newest request;
anything older is dropped, so the canvas can never step back to a value the
slider has already left. `cancel()` (Apply, leaving the step, Undo, a new
picture) drops the running and the waiting result alike.

Not `_run_busy`: a preview is not "the step working" (F2). It locks nothing,
dims nothing, and has no Cancel.
"""
from __future__ import annotations

import logging

import shiboken6
from PySide6.QtCore import QObject, QThreadPool, Signal

from ..core import sessionlog
from .worker import run_async

_log = logging.getLogger(__name__)
_NOTHING = object()


class PreviewRunner(QObject):
    """One per MainWindow. request(key, compute, show): compute() runs on the pool;
    show(result) runs on the UI thread only if `key` is still the newest request
    when the result lands. One job in flight at a time; requests while busy
    replace the pending one (latest wins). cancel() drops pending and in-flight
    results.

    `keep(result)`, optional, runs on the UI thread for every result that was
    not cancelled, stale or not: what a job prepared for an old slider value
    (Recover Core's blur) is still good for the new one on the same base.

    `is_async()` False runs inline, exceptions and all — the tests' setting, so
    a test reads the canvas on the next line, as it always has."""

    busyChanged = Signal(bool)

    def __init__(self, parent=None, *, pool=None, is_async=None) -> None:
        super().__init__(parent)
        self._pool = pool if pool is not None else QThreadPool.globalInstance()
        self._is_async = is_async if is_async is not None else (lambda: True)
        self._newest = _NOTHING
        self._shown = _NOTHING      # key of the result on screen
        self._waiting = None        # (key, compute, show, keep)
        self._running = None        # (epoch, key) of the job on the pool
        self._epoch = 0             # bumped by cancel(): older landings are dropped
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def request(self, key, compute, show, keep=None) -> None:
        self._newest = key
        if not self._is_async():
            self._waiting = None
            result = compute()
            if keep is not None:
                keep(result)
            show(result)
            return
        if self._running is not None:
            # Dragged back to the value already computing: wait for that one.
            same = self._running == (self._epoch, key)
            self._waiting = None if same else (key, compute, show, keep)
            self._sync_busy()
            return
        if key == self._shown:
            return      # on screen already: the debounce timer after a direct render
        self._start(key, compute, show, keep)

    def cancel(self) -> None:
        self._epoch += 1
        self._waiting = None
        self._newest = self._shown = _NOTHING
        self._sync_busy()

    def forget(self) -> None:
        """The canvas was painted by someone else (Space, a repaint): a request
        for the key last shown must compute again, not be skipped."""
        self._shown = _NOTHING

    def _start(self, key, compute, show, keep) -> None:
        epoch = self._epoch
        self._running = (epoch, key)
        self._sync_busy()
        run_async(self._pool, compute,
                  lambda result: self._landed(epoch, key, show, keep, result, None),
                  lambda exc: self._landed(epoch, key, show, keep, None, exc))

    def _landed(self, epoch, key, show, keep, result, exc) -> None:
        if not shiboken6.isValid(self):
            return              # the window went while the job ran
        self._running = None
        try:
            if epoch != self._epoch:
                return                       # cancelled: nobody wants it
            if exc is not None:
                _log.error("Preview failed: %r", exc, exc_info=exc)
                sessionlog.write(f"ERROR preview: {exc!r}")
                return
            if keep is not None:
                keep(result)
            if key == self._newest:
                self._shown = _NOTHING      # a raising paint leaves nothing known on screen
                show(result)
                self._shown = key
        except Exception:                    # a bad paint must not stop the next one
            _log.exception("Preview could not be shown")
        finally:
            nxt, self._waiting = self._waiting, None
            if nxt is not None:
                self._start(*nxt)
            else:
                self._sync_busy()

    def _sync_busy(self) -> None:
        busy = self._waiting is not None or (
            self._running is not None and self._running[0] == self._epoch)
        if busy != self._busy:
            self._busy = busy
            self.busyChanged.emit(busy)
