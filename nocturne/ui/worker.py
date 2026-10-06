from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QTimer, Signal, Slot

from ..core.tasks import Cancelled, CancelToken, clear_ambient, set_ambient


class WorkerSignals(QObject):
    done = Signal(object)
    error = Signal(object)
    progress = Signal(int, int)


class Worker(QRunnable):
    def __init__(self, fn, wants_progress: bool = False, token=None) -> None:
        super().__init__()
        self._token = token
        self._fn = fn
        self._wants_progress = wants_progress
        self.signals = WorkerSignals()
        self._returned = False      # run() holds nothing of ours any more

    @staticmethod
    def _send(signals, name: str, value) -> None:
        """Report back, unless there is nobody left to tell: a window closed
        mid-run deletes the objects these signals live on, and the emit then
        raised out of the pool thread as a traceback (2026-10-01)."""
        try:
            getattr(signals, name).emit(value)
        except RuntimeError:
            pass

    @Slot()
    def run(self) -> None:
        # Publish an ambient token so work deep inside — an external tool
        # reporting a percentage — has somewhere to report to. Only when a
        # caller asked: without it `report_progress` finds nobody and costs
        # nothing, which is how every existing caller behaves.
        signals = self.signals
        token = self._token
        own_token = token is None and self._wants_progress
        if own_token:
            token = CancelToken()
        if token is not None:
            if self._wants_progress:
                token.on_progress = signals.progress.emit
            set_ambient(token)
        # What the job handed back — a result, or an exception whose traceback
        # holds the job's frames and, through their closure cells, maybe a
        # dialog's self. The UI side keeps its copy in `_landed` until this
        # returns, so dropping these here is never the last reference.
        result = None
        try:
            result = self._fn()
        except (Exception, Cancelled) as exc:  # surfaced to on_error on the main thread
            # Cancelled is a BaseException, so `except Exception` would miss it —
            # catch it here so a user cancel routes to the clean-stop handler.
            result = exc
            self._send(signals, "error", exc)
        else:
            self._send(signals, "done", result)
        finally:
            if token is not None:
                clear_ambient()
                if self._wants_progress:
                    token.on_progress = None    # it held `signals`
            # Nothing here may outlive this line holding the signals: the UI
            # thread releases them once it sees the flag (`_sweep`), so the
            # last reference to this GUI-thread QObject goes there.
            del signals, token, result
            self._returned = True


# Keep workers referenced until they finish; otherwise PySide may garbage-
# collect the QRunnable (and its signals) before QThreadPool runs it.
_pending: set = set()
# (worker, signals, args) landed on the UI side while run() may still be returning
# on the pool thread. The signals are a GUI-thread QObject; they are held here
# until run() has dropped its own reference, then released by the UI thread, so
# they are never finalised on a pool thread (review 2026-10-06: 7 of 200 were).
# The Worker itself is a QRunnable, not a QObject: the pool's own reference
# may still end it on a pool thread, which is harmless once it holds nothing.
_landed: list = []


def _sweep() -> None:
    """On the UI thread: release the signals of every job whose run() returned."""
    global _landed
    _landed = [pair for pair in _landed if not pair[0]._returned]
    if _landed:
        QTimer.singleShot(10, _sweep)


def run_async(pool, fn, on_done, on_error=None, on_progress=None, token=None) -> None:
    """`on_progress(done, total)` opts into progress from inside `fn`.

    A dialog that does its own background work — Narrowband's star split, say —
    otherwise has no way to hear a tool's percentage: `_run_busy` publishes the
    ambient token, and `run_async` did not, so the same split reported in one
    place and was silent in the other.

    `token` lets the caller cancel: Upscale Crop's Cancel button holds it.
    """
    worker = Worker(fn, wants_progress=on_progress is not None, token=token)
    _pending.add(worker)

    def _cleanup(*args):
        # Disconnected, not just discarded: this closure holds `worker` and is
        # connected to worker.signals, a cycle through the C++ connection that
        # gc cannot see, so every Worker lived for the session (review
        # 2026-10-06: 20 preview ticks of a 46 MB base, RSS 60 MB -> 1 GB).
        _pending.discard(worker)
        # The closure holds what the job was given — a preview's full-size
        # base. Released here, on the UI thread, not at the end of run(): it
        # can hold the last reference to a Qt object, which must not be
        # destroyed on a pool thread.
        worker._fn = None
        signals = worker.signals
        connected = [signals.done, signals.error]
        if on_progress is not None:
            connected.append(signals.progress)
        for sig in connected:          # only these: disconnecting a bare signal warns
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass                   # the window went first
        # Out of the Worker, into _landed: from here only run()'s local and
        # this list hold them, and _sweep drops this list's after run()'s.
        worker.signals = None
        worker._token = None
        # `args` too: the result or exception, which run() may still hold.
        _landed.append((worker, signals, args))
        del signals, connected, args
        _sweep()

    worker.signals.done.connect(on_done)
    worker.signals.done.connect(_cleanup)
    if on_error is not None:
        worker.signals.error.connect(on_error)
    worker.signals.error.connect(_cleanup)
    if on_progress is not None:
        worker.signals.progress.connect(on_progress)
    pool.start(worker)


