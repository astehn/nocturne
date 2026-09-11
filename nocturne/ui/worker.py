from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from ..core.tasks import Cancelled, CancelToken, clear_ambient, set_ambient


class WorkerSignals(QObject):
    done = Signal(object)
    error = Signal(object)
    progress = Signal(int, int)


class Worker(QRunnable):
    def __init__(self, fn, wants_progress: bool = False) -> None:
        super().__init__()
        self._fn = fn
        self._wants_progress = wants_progress
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        # Publish an ambient token so work deep inside — an external tool
        # reporting a percentage — has somewhere to report to. Only when a
        # caller asked: without it `report_progress` finds nobody and costs
        # nothing, which is how every existing caller behaves.
        token = None
        if self._wants_progress:
            token = CancelToken()
            token.on_progress = self.signals.progress.emit
            set_ambient(token)
        try:
            result = self._fn()
        except (Exception, Cancelled) as exc:  # surfaced to on_error on the main thread
            # Cancelled is a BaseException, so `except Exception` would miss it —
            # catch it here so a user cancel routes to the clean-stop handler.
            self.signals.error.emit(exc)
        else:
            self.signals.done.emit(result)
        finally:
            if token is not None:
                clear_ambient()


# Keep workers referenced until they finish; otherwise PySide may garbage-
# collect the QRunnable (and its signals) before QThreadPool runs it.
_pending: set = set()


def run_async(pool, fn, on_done, on_error=None, on_progress=None) -> None:
    """`on_progress(done, total)` opts into progress from inside `fn`.

    A dialog that does its own background work — Narrowband's star split, say —
    otherwise has no way to hear a tool's percentage: `_run_busy` publishes the
    ambient token, and `run_async` did not, so the same split reported in one
    place and was silent in the other.
    """
    worker = Worker(fn, wants_progress=on_progress is not None)
    _pending.add(worker)

    def _cleanup(*_):
        _pending.discard(worker)

    worker.signals.done.connect(on_done)
    worker.signals.done.connect(_cleanup)
    if on_error is not None:
        worker.signals.error.connect(on_error)
    worker.signals.error.connect(_cleanup)
    if on_progress is not None:
        worker.signals.progress.connect(on_progress)
    pool.start(worker)


