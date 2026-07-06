from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    done = Signal(object)
    error = Signal(object)


class Worker(QRunnable):
    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # surfaced to on_error on the main thread
            self.signals.error.emit(exc)
        else:
            self.signals.done.emit(result)


# Keep workers referenced until they finish; otherwise PySide may garbage-
# collect the QRunnable (and its signals) before QThreadPool runs it.
_pending: set = set()


def run_async(pool, fn, on_done, on_error=None) -> None:
    worker = Worker(fn)
    _pending.add(worker)

    def _cleanup(*_):
        _pending.discard(worker)

    worker.signals.done.connect(on_done)
    worker.signals.done.connect(_cleanup)
    if on_error is not None:
        worker.signals.error.connect(on_error)
    worker.signals.error.connect(_cleanup)
    pool.start(worker)


