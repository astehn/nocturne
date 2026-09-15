"""`run_async` delivers its result, and its error, back on the main thread.

Both tests flush the event queue first, and that is not ceremony. Qt delivers
posted events IN ORDER, so a queued cross-thread signal waits behind whatever is
already in the queue — and by this point in a full run the queue holds every
`deleteLater` from the widgets of the preceding hundreds of tests. Measured
2026-09-15 on a run of 340 preceding tests:

    flushing the backlog        1.910 s
    delivery after the flush    0.011 s
    delivery WITHOUT the flush  1.907 s   (against a 2000 ms timeout)

That is why this test failed in roughly half of all full-suite runs while
passing every time on its own: the work took one millisecond and the answer sat
in a queue for 1.9 seconds. The app never sees this — its event loop runs
continuously and never accumulates a backlog of that size — so the fix belongs
here rather than in `run_async`.

Raising the timeout was the obvious alternative and is worse: it would keep the
confound and make a genuinely broken delivery take 30 seconds to report.
"""
import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool  # noqa: E402
from nocturne.ui.worker import run_async  # noqa: E402


@pytest.fixture
def drained(qtbot):
    """An empty event queue, so the timeouts below measure delivery and nothing
    else."""
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()
    return qtbot


def test_run_async_delivers_result(drained):
    got = []
    run_async(QThreadPool.globalInstance(), lambda: 21 * 2, got.append)
    drained.waitUntil(lambda: got == [42], timeout=2000)


def test_run_async_reports_error(drained):
    errs = []

    def boom():
        raise ValueError("nope")

    run_async(QThreadPool.globalInstance(), boom, lambda r: None, errs.append)
    drained.waitUntil(lambda: len(errs) == 1, timeout=2000)
    assert isinstance(errs[0], ValueError)
