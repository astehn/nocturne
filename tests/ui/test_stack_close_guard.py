"""Esc, Close and the title-bar button closed the Stack window mid-run, and the
running work died at its next progress report — a stray Esc meant for another
window ended his 1517-frame grade (Andreas, 2026-10-01). While work runs,
closing now asks first, and Keep stacking is the default.
"""
import threading

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from nocturne.settings import Settings
from nocturne.ui.stack_dialog import StackDialog
from nocturne.ui.worker import Worker


def _running(qtbot):
    """A shown dialog with a REAL job in flight, held until released."""
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg.show()
    release = threading.Event()

    def work():
        release.wait(5)
        return None
    # As the real handlers do: a finished job clears busy.
    dlg._start(work, lambda r: dlg._set_busy(False), "Stacking…")
    assert dlg._busy, "fixture"
    return dlg, release


def _esc(dlg):
    for t in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QApplication.sendEvent(dlg, QKeyEvent(t, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))


def test_esc_while_running_asks_and_keeping_changes_nothing(qtbot):
    dlg, release = _running(qtbot)
    asked = []
    dlg._confirm_stop = lambda: asked.append(1) or False
    token = dlg._active_token
    _esc(dlg)
    assert asked, "Esc must ask, not close"
    assert dlg.isVisible()
    assert not token.cancelled
    release.set(); qtbot.waitUntil(lambda: not dlg._busy, timeout=3000)


def test_the_close_button_and_title_bar_ask_too(qtbot):
    dlg, release = _running(qtbot)
    asked = []
    dlg._confirm_stop = lambda: asked.append(1) or False
    dlg.reject()                     # the Close button's own slot
    dlg.close()                      # the title-bar button
    assert len(asked) == 2 and dlg.isVisible()
    release.set(); qtbot.waitUntil(lambda: not dlg._busy, timeout=3000)


def test_choosing_to_stop_cancels_the_work_and_closes(qtbot):
    dlg, release = _running(qtbot)
    dlg._confirm_stop = lambda: True
    token = dlg._active_token
    _esc(dlg)
    assert token.cancelled
    assert not dlg.isVisible()
    release.set()


def test_esc_with_nothing_running_still_just_closes(qtbot):
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg.show()
    asked = []
    dlg._confirm_stop = lambda: asked.append(1) or True
    _esc(dlg)
    assert not asked and not dlg.isVisible()


def test_a_worker_whose_signals_are_gone_ends_quietly():
    """The second traceback: reporting to a deleted signal object raised out of
    the pool thread. Gone means nobody is listening — finish quietly."""
    import shiboken6
    for fn in (lambda: 1, lambda: (_ for _ in ()).throw(ValueError("x"))):
        w = Worker(fn)
        shiboken6.delete(w.signals)
        w.run()                      # must not raise


def test_progress_to_a_closed_window_stops_the_work(qtbot):
    """Not just silence: work whose window is gone should stop, not grind on
    through 1517 frames for nobody."""
    from nocturne.core.tasks import Cancelled
    import pytest
    dlg = StackDialog(Settings())
    report = dlg._progress_reporter()
    import shiboken6
    shiboken6.delete(dlg._signals)
    with pytest.raises(Cancelled):
        report(1, 10, "Measuring")


def test_a_stack_that_finishes_while_asking_is_not_closed_twice(qtbot):
    """The question runs its own event loop; the stack can complete under it,
    hand the master over and accept(). 'Stop and close' then must not reject
    a dialog that already finished (review 2026-10-01)."""
    from PySide6.QtWidgets import QDialog
    dlg, release = _running(qtbot)

    def finished_meanwhile():
        dlg._set_busy(False)
        dlg.accept()
        return True
    dlg._confirm_stop = finished_meanwhile
    rejected = []
    dlg.rejected.connect(lambda: rejected.append(1))
    dlg.reject()
    assert not rejected
    assert dlg.result() == QDialog.DialogCode.Accepted
    release.set()
