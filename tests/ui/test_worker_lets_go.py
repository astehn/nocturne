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
