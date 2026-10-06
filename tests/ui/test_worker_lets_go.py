"""A finished background job must let go of what it captured (review of the
no-freezes Task 2, 2026-10-06). `run_async`'s cleanup closure held the Worker
through its own signal connection — a cycle through C++ that gc cannot break —
so every job, and the full-size base array its closure captured, lived for the
rest of the session: 20 preview ticks of a 46 MB base took RSS from 60 MB to
1 GB. Previews made it one job per slider tick."""
import gc
import weakref

import numpy as np
from PySide6.QtCore import QThreadPool

from nocturne.ui.preview_runner import PreviewRunner
from nocturne.ui.worker import run_async


def _gone(qtbot, pool, ref):
    pool.waitForDone(5000)
    qtbot.wait(20)
    gc.collect()
    return ref() is None


def test_run_async_lets_go_of_its_closure(qtbot):
    pool = QThreadPool()
    arr = np.zeros((64, 64), np.float32)
    ref = weakref.ref(arr)
    done = []
    run_async(pool, lambda a=arr: float(a.sum()), done.append)
    del arr
    qtbot.waitUntil(lambda: done == [0.0])
    assert _gone(qtbot, pool, ref), "the job's captured array outlived the job"


def test_run_async_lets_go_after_an_error(qtbot):
    pool = QThreadPool()
    arr = np.zeros((64, 64), np.float32)
    ref = weakref.ref(arr)
    errs = []

    def boom(a=arr):
        raise ValueError("x")
    run_async(pool, boom, lambda r: None, errs.append)
    del arr, boom
    qtbot.waitUntil(lambda: len(errs) == 1)
    errs.clear()
    assert _gone(qtbot, pool, ref)


def test_a_preview_lets_go_of_its_base_and_result(qtbot):
    pool = QThreadPool()
    r = PreviewRunner(pool=pool)
    bases, outs = [], []
    for i in range(5):
        base = np.full((64, 64), float(i), np.float32)
        bases.append(weakref.ref(base))
        r.request(i, lambda b=base: b * 2, lambda out: outs.append(weakref.ref(out)))
        del base
        qtbot.waitUntil(lambda: not r.busy and r._running is None)
    pool.waitForDone(5000)
    qtbot.wait(20)
    gc.collect()
    assert sum(b() is not None for b in bases) == 0
    assert sum(o() is not None for o in outs) == 0


def test_an_async_apply_lets_go_of_its_base(qtbot, tmp_path, monkeypatch):
    """The same cycle held every Apply's base (`_run_busy` -> run_async)."""
    from tests.ui.test_live_previews_async import _open
    win = _open(qtbot, tmp_path, monkeypatch)
    win._go_to_id("levels")
    seen = []
    real = win._step_for

    class Spy:
        def __init__(self, step):
            self._step = step

        def apply(self, base, option):
            seen.append(weakref.ref(base.data))
            return self._step.apply(base, option)

        def __getattr__(self, name):
            return getattr(self._step, name)
    monkeypatch.setattr(win, "_step_for", lambda sid: Spy(real(sid)))
    win._panel.gamma_slider.setValue(150)
    win._async_enabled = True
    n = len(win.project.entries())
    win._apply_current_step()
    qtbot.waitUntil(lambda: not win._busy and len(win.project.entries()) == n + 1)
    assert len(seen) == 1
    assert _gone(qtbot, QThreadPool.globalInstance(), seen[0]), \
        "the committed step's base outlived the Apply"


def test_what_a_job_held_is_released_on_the_ui_thread(qtbot):
    """Released at the end of run(), the closure died on the pool thread — and
    a dialog it held was destroyed there, sending events through the window's
    app-wide event filter off the GUI thread: the segfault in the no-freezes
    full suite (Python-2026-10-06-162453.ips, thread 52:
    QRunnableWrapper::run -> func_dealloc -> ~QDialogWrapper -> ~QPushButton).
    A sentinel stands in for the dialog: where it dies is where the dialog would."""
    import threading
    where = []

    class Sentinel:
        def __del__(self):
            where.append(threading.current_thread() is threading.main_thread())
    pool = QThreadPool()
    done = []
    s = Sentinel()
    run_async(pool, lambda held=s: 1, done.append)
    del s
    qtbot.waitUntil(lambda: done == [1])
    pool.waitForDone(5000)
    qtbot.wait(20)
    gc.collect()
    assert where == [True], "the job's closure was released off the UI thread"


def test_worker_signals_die_on_the_ui_thread(qtbot, monkeypatch):
    """`_cleanup` runs on the UI thread as soon as `done` is delivered, which
    can be before run() has returned on the pool thread; the pool's last
    reference then took the Worker — and its parentless GUI-thread
    WorkerSignals, a QObject — down on the pool thread (review probe: 7 of 200).
    Over many jobs, some quick and some not, every WorkerSignals must die on
    the UI thread."""
    import threading
    import time

    from nocturne.ui import worker as W
    where = {"signals": []}
    on_main = lambda: threading.current_thread() is threading.main_thread()  # noqa: E731
    monkeypatch.setattr(W.WorkerSignals, "__del__",
                        lambda self: where["signals"].append(on_main()), raising=False)
    pool = QThreadPool()
    pool.setMaxThreadCount(4)
    done = []

    def job(i):
        def f():
            time.sleep(0.002 if i % 2 else 0.0)
            return i
        return f
    n = 200
    for i in range(n):
        run_async(pool, job(i), done.append)
    qtbot.waitUntil(lambda: len(done) == n, timeout=10000)
    pool.waitForDone(5000)
    qtbot.waitUntil(lambda: len(where["signals"]) == n, timeout=5000)
    assert all(where["signals"]), \
        f"{where['signals'].count(False)} WorkerSignals died on a pool thread"
    # The Worker (a QRunnable, not a QObject) may still end on a pool thread
    # through the pool's own reference; what matters is that by then it holds
    # nothing — no signals, no closure, no token — which _cleanup sees to.


def test_a_failed_jobs_traceback_dies_on_the_ui_thread(qtbot, monkeypatch):
    """The error path: the exception's traceback holds the job's frames, and
    their closure cells can hold a dialog's self (color_balance_dialog,
    narrowband_dialog). The UI side keeps the exception until run() has
    returned, so the pool thread never drops the last reference. Made
    deterministic by holding run() just after the emit, until the UI thread
    has handled the error and let go of its own copy."""
    import threading
    import time

    from nocturne.ui import worker as W
    where = []

    class Sentinel:
        def __del__(self):
            where.append(threading.current_thread() is threading.main_thread())

    real_send = W.Worker._send

    def slow_send(signals, name, value):
        real_send(signals, name, value)
        time.sleep(0.3)                    # the UI thread handles it meanwhile
    monkeypatch.setattr(W.Worker, "_send", staticmethod(slow_send))

    def job():
        held = Sentinel()                  # only the traceback's frame keeps it
        raise RuntimeError(f"boom {id(held)}")
    pool = QThreadPool()
    errors = []
    run_async(pool, job, lambda r: None, lambda e: errors.append(type(e)))
    qtbot.waitUntil(lambda: errors == [RuntimeError], timeout=5000)
    pool.waitForDone(5000)
    qtbot.waitUntil(lambda: where != [], timeout=5000)
    gc.collect()
    assert where == [True], "the traceback was released on the pool thread"


def test_a_jobs_result_dies_on_the_ui_thread(qtbot, monkeypatch):
    """The done path: run()'s own `result` must not outlive the UI side's copy."""
    import threading
    import time

    from nocturne.ui import worker as W
    where = []

    class Sentinel:
        def __del__(self):
            where.append(threading.current_thread() is threading.main_thread())

    real_send = W.Worker._send

    def slow_send(signals, name, value):
        real_send(signals, name, value)
        time.sleep(0.3)
    monkeypatch.setattr(W.Worker, "_send", staticmethod(slow_send))
    pool = QThreadPool()
    done = []
    run_async(pool, Sentinel, lambda r: done.append(1))
    qtbot.waitUntil(lambda: done == [1], timeout=5000)
    pool.waitForDone(5000)
    qtbot.waitUntil(lambda: where != [], timeout=5000)
    assert where == [True], "the result was released on the pool thread"
