"""A live preview runs off the UI thread, and only the newest slider position is
ever painted (spec F1, 2026-10-06). The runner on its own: held workers stand in
for a slow effect, so ordering is decided by the test, not by timing."""
import logging
import threading

import pytest
from PySide6.QtCore import QThreadPool

from nocturne.ui.preview_runner import PreviewRunner


class Held:
    """compute() functions that block until the test releases them."""

    def __init__(self):
        self.started = []
        self.gates = {}

    def job(self, value, *, fail=False):
        gate = self.gates.setdefault(value, threading.Event())

        def compute():
            self.started.append(value)
            assert gate.wait(10), "a held job was never released"
            if fail:
                raise RuntimeError(f"boom {value}")
            return value
        return compute

    def release(self, value):
        self.gates.setdefault(value, threading.Event()).set()


@pytest.fixture
def pool():
    p = QThreadPool()
    p.setMaxThreadCount(4)
    yield p
    p.waitForDone(5000)


@pytest.fixture
def held(pool):
    """Torn down before `pool`: every gate opens, so no worker outlives a test."""
    h = Held()
    yield h
    for gate in h.gates.values():
        gate.set()


def _runner(qtbot, pool, is_async=True):
    r = PreviewRunner(pool=pool, is_async=lambda: is_async)
    return r


def test_three_requests_while_one_is_held_compute_only_the_last(qtbot, pool, held):
    r = _runner(qtbot, pool)
    shown = []
    r.request("A", held.job("A"), shown.append)
    qtbot.waitUntil(lambda: held.started == ["A"])
    for v in ("B", "C", "D"):
        r.request(v, held.job(v), shown.append)
    held.release("A")
    qtbot.waitUntil(lambda: held.started == ["A", "D"])
    held.release("D")
    qtbot.waitUntil(lambda: shown == ["D"])
    qtbot.wait(50)
    assert held.started == ["A", "D"], "B and C were never wanted"
    assert shown == ["D"], "A landed after B was asked for: it must not be painted"
    assert not r.busy


def test_a_stale_result_is_never_shown_even_when_it_lands_last(qtbot, pool, held):
    """B is asked for while A runs; A's result arrives — and is dropped."""
    r = _runner(qtbot, pool)
    shown = []
    r.request("A", held.job("A"), shown.append)
    qtbot.waitUntil(lambda: held.started == ["A"])
    r.request("B", held.job("B"), shown.append)
    held.release("A")
    qtbot.waitUntil(lambda: held.started == ["A", "B"])
    assert shown == [], "A's result reached the canvas after B was asked for"
    held.release("B")
    qtbot.waitUntil(lambda: shown == ["B"])


def test_returning_to_the_running_value_waits_for_it_not_a_rerun(qtbot, pool, held):
    r = _runner(qtbot, pool)
    shown = []
    r.request("A", held.job("A"), shown.append)
    qtbot.waitUntil(lambda: held.started == ["A"])
    r.request("B", held.job("B"), shown.append)
    r.request("A", held.job("A"), shown.append)     # dragged back
    held.release("A")
    qtbot.waitUntil(lambda: shown == ["A"])
    qtbot.wait(50)
    assert held.started == ["A"]


def test_cancel_drops_the_running_and_the_waiting_result(qtbot, pool, held):
    r = _runner(qtbot, pool)
    shown, kept = [], []
    r.request("A", held.job("A"), shown.append, kept.append)
    qtbot.waitUntil(lambda: held.started == ["A"])
    r.request("B", held.job("B"), shown.append, kept.append)
    assert r.busy
    r.cancel()
    assert not r.busy, "a dropped job is nobody's work: no ring for it"
    held.release("A")
    held.release("B")
    qtbot.wait(100)
    assert shown == [] and kept == []
    assert held.started == ["A"], "the waiting request was dropped, not run"
    r.request("C", held.job("C"), shown.append)
    held.release("C")
    qtbot.waitUntil(lambda: shown == ["C"])


def test_a_request_after_cancel_waits_for_the_dropped_job(qtbot, pool, held):
    """One job in flight at a time, even when the running one is unwanted: two
    prepares of one 33 MP blur side by side would hold two full-size arrays."""
    r = _runner(qtbot, pool)
    shown = []
    r.request("A", held.job("A"), shown.append)
    qtbot.waitUntil(lambda: held.started == ["A"])
    r.cancel()
    r.request("B", held.job("B"), shown.append)
    assert r.busy
    qtbot.wait(50)
    assert held.started == ["A"]
    held.release("A")
    qtbot.waitUntil(lambda: held.started == ["A", "B"])
    held.release("B")
    qtbot.waitUntil(lambda: shown == ["B"])


def test_keep_sees_a_stale_result_that_show_never_does(qtbot, pool, held):
    """The amount-independent part prepared for A is good for B on the same
    base: it is kept even though A's picture is not shown."""
    r = _runner(qtbot, pool)
    shown, kept = [], []
    r.request("A", held.job("A"), shown.append, kept.append)
    qtbot.waitUntil(lambda: held.started == ["A"])
    r.request("B", held.job("B"), shown.append, kept.append)
    held.release("A")
    qtbot.waitUntil(lambda: kept == ["A"])
    held.release("B")
    qtbot.waitUntil(lambda: shown == ["B"])
    assert kept == ["A", "B"]


def test_an_exception_is_logged_and_does_not_wedge_the_runner(qtbot, pool, held, caplog):
    r = _runner(qtbot, pool)
    shown = []
    with caplog.at_level(logging.ERROR):
        r.request("A", held.job("A", fail=True), shown.append)
        held.release("A")
        qtbot.waitUntil(lambda: not r.busy)
    assert any("boom A" in rec.getMessage() or "boom A" in str(rec.exc_info)
               for rec in caplog.records)
    r.request("B", held.job("B"), shown.append)
    held.release("B")
    qtbot.waitUntil(lambda: shown == ["B"])


def test_a_raising_show_does_not_wedge_the_runner(qtbot, pool, held):
    r = _runner(qtbot, pool)
    shown = []

    def bad(_):
        raise RuntimeError("paint failed")
    r.request("A", held.job("A"), bad)
    r.request("B", held.job("B"), shown.append)
    held.release("A")
    held.release("B")
    qtbot.waitUntil(lambda: shown == ["B"])
    r.request("C", held.job("C"), bad)
    held.release("C")
    qtbot.waitUntil(lambda: not r.busy)
    r.request("D", held.job("D"), shown.append)
    held.release("D")
    qtbot.waitUntil(lambda: shown == ["B", "D"])


def test_busy_changed_reports_the_ring(qtbot, pool, held):
    r = _runner(qtbot, pool)
    seen = []
    r.busyChanged.connect(seen.append)
    r.request("A", held.job("A"), lambda _: None)
    assert r.busy and seen == [True]
    held.release("A")
    qtbot.waitUntil(lambda: seen == [True, False])


def test_synchronous_mode_runs_inline(qtbot, pool):
    """`_async_enabled = False` (every existing test): computed and shown before
    request() returns, so a test reads the canvas on the next line."""
    r = _runner(qtbot, pool, is_async=False)
    shown, kept = [], []
    seen = []
    r.busyChanged.connect(seen.append)
    r.request("A", lambda: "A", shown.append, kept.append)
    assert shown == ["A"] and kept == ["A"]
    assert seen == [] and not r.busy


def test_synchronous_mode_lets_an_exception_through(qtbot, pool):
    """As before the runner: a broken effect fails the test that drives it."""
    r = _runner(qtbot, pool, is_async=False)

    def boom():
        raise ValueError("x")
    with pytest.raises(ValueError):
        r.request("A", boom, lambda _: None)


def test_asking_again_for_the_picture_on_screen_computes_nothing(qtbot, pool, held):
    """The debounce timer fires after a direct render with the same value."""
    r = _runner(qtbot, pool)
    shown = []
    r.request("A", held.job("A"), shown.append)
    held.release("A")
    qtbot.waitUntil(lambda: shown == ["A"])
    r.request("A", held.job("A"), shown.append)
    qtbot.wait(30)
    assert held.started == ["A"] and shown == ["A"] and not r.busy
    r.cancel()                                   # the canvas was repainted
    r.request("A", held.job("A"), shown.append)
    qtbot.waitUntil(lambda: shown == ["A", "A"])
