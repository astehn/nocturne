"""Cyclic garbage is collected on the GUI thread only (2026-10-06).

Python runs a collection in whichever thread happens to allocate past the
threshold. Live previews run Python on pool threads every slider tick, so a
QDialog left in a reference cycle could be destroyed on a pool thread — shown
by experiment, and the same off-thread destruction behind a suite segfault
(crash report 162453). install() turns automatic collection off and collects
from a GUI-thread timer instead."""
import gc
import threading

import pytest
from PySide6.QtCore import QThreadPool

from nocturne.ui import gc_guard
from nocturne.ui.worker import run_async


class _Cycle:
    """An object only gc can free, which says on which thread it was."""

    def __init__(self, where):
        self.me = self
        self.where = where

    def __del__(self):
        self.where.append(threading.current_thread() is threading.main_thread())


@pytest.fixture
def guard(qapp):
    """A fresh guard with a short interval; the suite's own one is restored after."""
    previous = gc_guard.uninstall(qapp)
    g = gc_guard.install(qapp, interval_ms=20)
    yield g
    gc_guard.uninstall(qapp)
    if previous is not None:
        gc_guard.install(qapp)


def _collect_in_a_pool_job(qtbot):
    """What a preview's compute can do: allocate enough to trigger automatic gc."""
    done = []

    def churn():
        # Tracked objects kept alive (a result): past the 2000 threshold,
        # automatic gc would run HERE, on the pool thread.
        return [[] for _ in range(5000)]
    run_async(QThreadPool.globalInstance(), churn, done.append)
    qtbot.waitUntil(lambda: len(done) == 1)
    return done


def test_a_cycle_is_finalised_on_the_gui_thread(qtbot, guard):
    where = []
    _Cycle(where)
    held = _collect_in_a_pool_job(qtbot)    # kept: the count stays past the threshold
    assert where == [], "collected inside the pool job"
    qtbot.waitUntil(lambda: where == [True], timeout=3000)
    del held


def test_without_the_guard_a_pool_job_collects_it(qtbot, qapp):
    """The control: the hazard is real, so the test above has teeth."""
    previous = gc_guard.uninstall(qapp)
    try:
        assert gc.isenabled()
        where = []
        _Cycle(where)
        held = _collect_in_a_pool_job(qtbot)
        assert where == [False], "the cycle died on the pool thread"
    finally:
        if previous is not None:
            gc_guard.install(qapp)


def test_cycles_are_still_collected_while_it_runs(qtbot, guard):
    assert not gc.isenabled()
    where = []
    for _ in range(5000):
        _Cycle(where)
    assert gc.get_count()[0] > gc.get_threshold()[0]
    qtbot.waitUntil(lambda: len(where) == 5000, timeout=5000)
    assert all(where)
    assert gc.get_count()[0] < gc.get_threshold()[0]


def test_quitting_collects(qtbot, guard, qapp):
    where = []
    _Cycle(where)
    guard._timer.stop()                 # only aboutToQuit can collect it now
    qapp.aboutToQuit.emit()
    assert where == [True]


def test_install_is_once_per_app(qapp, guard):
    assert gc_guard.install(qapp) is guard


def test_the_app_installs_it_only_in_the_gui_process():
    """After the QApplication, and below the --stack-job / --check-* exits."""
    import inspect

    import nocturne.__main__ as entry
    src = inspect.getsource(entry.main)
    app_at = src.index("app = QApplication(sys.argv)")
    install_at = src.index("gc_guard.install(app)")
    assert app_at < install_at
    for exit_flag in ('"--stack-job"', '"--check-network"', '"--check-codecs"'):
        assert src.index(exit_flag) < app_at
