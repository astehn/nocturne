"""Opening an image reads the file off the UI thread (no-freezes F4).

The M 8 drizzle took 4.1 s to open with no sign of life (2026-10-06); opening a
project already ran in the background. Every load here is HELD on the worker
(`_Loads`) so "while it reads" can be inspected.
"""
import threading
from contextlib import contextmanager

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

import nocturne.ui.main_window as mw
from nocturne.ui import file_dialogs
from tests.ui.test_file_drop import _drop, _enter, _mime
from tests.ui.test_main_window import _make_fits, _window


class _Loads:
    """Stands in for `load_fits`: records each read, and holds the ones asked
    to be held until released. Never touches the window."""

    def __init__(self, real):
        self.real = real
        self.calls = []
        self.gates = {}

    def hold(self, path):
        self.gates[path] = threading.Event()

    def release(self, path=None):
        for p, ev in self.gates.items():
            if path is None or p == path:
                ev.set()

    def __call__(self, path):
        self.calls.append(path)
        gate = self.gates.get(path)
        if gate is not None:
            gate.wait(10)
        return self.real(path)


@pytest.fixture
def loads(monkeypatch):
    lo = _Loads(mw.load_fits)
    monkeypatch.setattr(mw, "load_fits", lo)
    yield lo
    lo.release()


def _fits(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    return _make_fits(d)


def _idle(qtbot, win):
    qtbot.waitUntil(lambda: not win._busy, timeout=10000)
    qtbot.wait(20)


@contextmanager
def _drained(qtbot, win, loads):
    """A failed assertion must not leave a held read to land on a closed window."""
    try:
        yield
    finally:
        loads.release()
        _idle(qtbot, win)


def _opened(qtbot, tmp_path):
    """A window with a picture already open (synchronously), then async on."""
    win = _window(qtbot, tmp_path)
    win.show()
    win.open_fits(_fits(tmp_path, "first"))
    win._async_enabled = True
    return win


def _state(win):
    """Everything an open replaces: captured before, compared after."""
    return dict(
        project=win.project,
        names=[n for n, _ in win.project.entries()],
        data=win.project.current().data.copy(),
        canvas=win.image_view._item.pixmap().toImage().copy(),
        title=win.windowTitle(),
        label=win._source_label,
        stage=win.current_stage_id(),
        log=win.log_panel.toPlainText() if hasattr(win.log_panel, "toPlainText") else None,
        dirty=win._dirty,
        # Bumped by every workspace swap: a swap before the read succeeded
        # would already have cancelled work and retired the plate solve.
        gen=win._project_gen,
        tiff=win._opened_as_tiff,
    )


def _same(a, b):
    assert a["project"] is b["project"]
    assert a["names"] == b["names"]
    assert np.array_equal(a["data"], b["data"])
    assert a["canvas"] == b["canvas"]
    for k in ("title", "label", "stage", "log", "dirty", "gen", "tiff"):
        assert a[k] == b[k], k


# --- the read runs in the background -------------------------------------------
def test_while_it_reads_the_window_answers_and_says_what_it_is_doing(qtbot, tmp_path, loads):
    win = _opened(qtbot, tmp_path)
    second = _fits(tmp_path, "second")
    loads.hold(second)
    before = _state(win)
    with _drained(qtbot, win, loads):
        win.open_any(second)
        assert win._busy, "returned at once, the read still running"
        _same(before, _state(win))          # nothing replaced until the read succeeds
        ticked = []
        QTimer.singleShot(0, lambda: ticked.append(1))
        qtbot.waitUntil(lambda: bool(ticked), timeout=2000)     # the event loop runs
        qtbot.waitUntil(lambda: win._busy_shown, timeout=3000)  # past BUSY_DELAY_MS
        assert win._busy_label.isVisible() and win._busy_ring.isVisible()
        assert win._busy_label_text == "Opening stack.fits…"
        assert not win.stepper.isEnabled()
        assert not win._open_image_act.isEnabled()
        assert not win._open_project_act.isEnabled()
    assert win.project is not before["project"]
    expected = mw.load_fits.real(second).data
    assert np.array_equal(win.project.current().data, expected)
    assert win.current_stage_id() == "load"
    assert win.stepper.isEnabled() and win._open_image_act.isEnabled()


def test_a_second_open_while_reading_is_refused(qtbot, tmp_path, loads):
    win = _opened(qtbot, tmp_path)
    second, third = _fits(tmp_path, "second"), _fits(tmp_path, "third")
    loads.hold(second)
    loads.calls.clear()                      # the first picture's own read
    warned = []
    real_warn = win._show_warning
    win._show_warning = lambda m: (warned.append(m), real_warn(m))
    with _drained(qtbot, win, loads):
        win.open_any(second)
        win.open_requested(third)                       # Finder / Open With
        mime = _mime(third)
        assert not _enter(win, mime).isAccepted()      # a drag
        # Handed to the handler, not sent through Qt: Qt never delivers a drop
        # after a refused enter, and a synthetic one sent to a SHOWN window
        # crashes inside Qt (segfault in sendEvent, 3 runs in 6, before any
        # Python handler ran).
        drop = QDropEvent(QPointF(200, 200), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        win.dropEvent(drop)
        win._open_finished_master(third)                # the jobs indicator
        assert not win._welcome.open_btn.isEnabled()    # the start page's button
        qtbot.wait(50)
        assert loads.calls == [second], "no second read started"
        assert len(warned) == 2 and all("Finish or cancel" in m for m in warned)
    assert win._source_label == "stack.fits"
    assert np.array_equal(win.project.current().data, mw.load_fits.real(second).data)


def test_a_failed_read_leaves_the_picture_exactly_as_it_was(qtbot, tmp_path):
    win = _opened(qtbot, tmp_path)
    win._go_to_id("stretch")
    win._async_enabled = False
    win.apply_current({"amount": 0.3, "linked": True})
    win._async_enabled = True
    win._dirty = False                         # no unsaved-changes question
    bad = tmp_path / "bad.fits"
    bad.write_text("not a fits file")
    before = _state(win)
    win.open_any(str(bad))
    _idle(qtbot, win)
    _same(before, _state(win))
    assert win._warning.text().startswith("Could not open file: ")


def test_cancel_during_the_read_keeps_the_picture(qtbot, tmp_path, loads, monkeypatch):
    win = _opened(qtbot, tmp_path)
    second = _fits(tmp_path, "second")
    loads.hold(second)
    saves = []
    real_save = mw.np.save
    monkeypatch.setattr(mw.np, "save", lambda *a, **k: (saves.append(a[0]), real_save(*a, **k)))
    before = _state(win)
    with _drained(qtbot, win, loads):
        win.open_any(second)
        win._cancel_active()
    _same(before, _state(win))
    assert "Cancelled" in win.output_panel.toPlainText()
    assert saves == [], "a cancelled read is not written to the cache as well"


def test_cancel_during_the_snapshot_write_keeps_the_picture(qtbot, tmp_path, monkeypatch):
    from nocturne.core import tasks
    win = _opened(qtbot, tmp_path)
    real_save = mw.np.save

    def save_then_cancel(*a, **k):
        real_save(*a, **k)
        tasks.current().cancel()             # Cancel arrives as the write finishes

    monkeypatch.setattr(mw.np, "save", save_then_cancel)
    before = _state(win)
    win.open_any(_fits(tmp_path, "second"))
    _idle(qtbot, win)
    _same(before, _state(win))
    assert _incoming(win) == [], "the half-made snapshot is removed"


def test_the_open_asked_for_last_wins(qtbot, tmp_path, loads):
    """Two reads in flight (only code can start the second): the older one
    finishing first must not land. The generation guard cannot see this — it
    bumps only when an open commits."""
    win = _opened(qtbot, tmp_path)
    older, newer = _fits(tmp_path, "older"), _fits(tmp_path, "newer")
    loads.hold(older)
    loads.hold(newer)
    before = _state(win)
    with _drained(qtbot, win, loads):
        win.open_any(older)
        win.open_any(newer)
        loads.release(older)
        qtbot.waitUntil(lambda: len(win._running) == 1, timeout=5000)
        qtbot.wait(20)
        _same(before, _state(win))           # the older read landed nowhere
    assert np.array_equal(win.project.current().data, mw.load_fits.real(newer).data)


def test_a_preview_armed_on_the_old_picture_is_stopped_by_the_open(qtbot, tmp_path, loads):
    win = _opened(qtbot, tmp_path)
    second = _fits(tmp_path, "second")
    win._levels_timer.start(60_000)          # a debounce waiting on the old picture
    win.open_any(second)
    _idle(qtbot, win)
    assert not win._levels_timer.isActive()
    assert win.current_stage_id() == "load"


# --- every door goes through it ------------------------------------------------
def _door_toolbar(win, path, monkeypatch):
    monkeypatch.setattr(file_dialogs, "open_file", lambda *a, **k: path)
    win._open_image_act.trigger()


def _door_start_page(win, path, monkeypatch):
    monkeypatch.setattr(file_dialogs, "open_file", lambda *a, **k: path)
    win._welcome.open_btn.click()


def _door_drop(win, path, monkeypatch):
    mime = _mime(path)
    _enter(win, mime)
    _drop(win, mime)


def _door_finder(win, path, monkeypatch):
    win.open_requested(path)


@pytest.mark.parametrize("door", [_door_toolbar, _door_start_page, _door_drop, _door_finder],
                         ids=["toolbar", "start-page", "drop", "finder"])
def test_every_door_opens_in_the_background(qtbot, tmp_path, loads, monkeypatch, door):
    win = _window(qtbot, tmp_path)
    win.show()
    win._async_enabled = True
    path = _fits(tmp_path, "pic")
    loads.hold(path)
    with _drained(qtbot, win, loads):
        door(win, path, monkeypatch)
        qtbot.waitUntil(lambda: loads.calls == [path], timeout=3000)
        assert win._busy and win._busy_label_text == "Opening stack.fits…"
        assert win.project is None, "the start page stays until the read is done"
    assert win.project is not None and win.current_stage_id() == "load"


def test_auto_enhance_from_the_start_page_carries_on_after_the_open(qtbot, tmp_path, loads,
                                                                    monkeypatch):
    win = _window(qtbot, tmp_path)
    win.show()
    win._async_enabled = True
    path = _fits(tmp_path, "pic")
    monkeypatch.setattr(file_dialogs, "open_file", lambda *a, **k: path)
    win._auto_enhance()
    _idle(qtbot, win)
    assert win.project is not None
    assert "Crop" in win._warning.text()
    assert win._after_open is None


# --- what stays on the UI thread -------------------------------------------------
def _incoming(win):
    import os
    d = win._staging_dir()
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def test_the_first_snapshot_is_written_off_the_ui_thread(qtbot, tmp_path, loads, monkeypatch):
    """Project's own np.save of the base was 2.1 s of the M 8 drizzle's open.
    The worker writes it; the UI thread only moves it into place."""
    win = _opened(qtbot, tmp_path)
    second = _fits(tmp_path, "second")
    ui = threading.current_thread()
    saved_on = []
    real_save = mw.np.save

    def spy(path, arr, *a, **k):
        saved_on.append((str(path), threading.current_thread() is ui))
        return real_save(path, arr, *a, **k)

    monkeypatch.setattr(mw.np, "save", spy)
    win.open_any(second)
    _idle(qtbot, win)
    assert saved_on and not any(on_ui for _p, on_ui in saved_on), saved_on
    assert np.array_equal(np.load(win.project._paths[0]), mw.load_fits.real(second).data)
    assert _incoming(win) == []


def test_no_staged_snapshot_is_left_behind(qtbot, tmp_path, loads):
    """Failure, Cancel and a superseded open each leave the cache as they found it."""
    win = _opened(qtbot, tmp_path)
    bad = tmp_path / "bad.fits"
    bad.write_text("not a fits file")
    win.open_any(str(bad))
    _idle(qtbot, win)
    assert _incoming(win) == []

    second = _fits(tmp_path, "second")
    loads.hold(second)
    with _drained(qtbot, win, loads):
        win.open_any(second)
        win._cancel_active()
    assert _incoming(win) == []

    older, newer = _fits(tmp_path, "older"), _fits(tmp_path, "newer")
    loads.hold(older)
    loads.hold(newer)
    with _drained(qtbot, win, loads):
        win.open_any(older)
        win.open_any(newer)
        loads.release(older)
        qtbot.waitUntil(lambda: len(win._running) == 1, timeout=5000)
        qtbot.wait(20)
        assert _incoming(win) == []
    assert _incoming(win) == []


def test_the_open_draws_its_picture_once_and_it_is_the_current_one(qtbot, tmp_path, loads,
                                                                   monkeypatch):
    win = _opened(qtbot, tmp_path)
    second = _fits(tmp_path, "second")
    painted = []
    real = win._set_canvas
    monkeypatch.setattr(win, "_set_canvas", lambda img, *a, **k: (painted.append(1),
                                                                   real(img, *a, **k)))
    win.open_any(second)
    _idle(qtbot, win)
    assert len(painted) == 1
    shown = win.image_view._item.pixmap().toImage().copy()
    hist = win.histogram_view.hist()
    win._refresh()                                     # a full repaint from scratch
    assert win.image_view._item.pixmap().toImage() == shown
    again = win.histogram_view.hist()
    assert hist.keys() == again.keys()
    for k in hist:
        assert np.array_equal(np.asarray(hist[k]), np.asarray(again[k])), k
    assert win._displayed is not None
    assert np.array_equal(win._displayed.data, win.project.current().data)


def test_a_stray_staged_snapshot_goes_at_the_next_open_and_at_quit(qtbot, tmp_path):
    """A superseded open's result is dropped by the generation guard without
    reaching its own clean-up; the stray must not outlive the session."""
    import os
    win = _opened(qtbot, tmp_path)
    os.makedirs(win._staging_dir(), exist_ok=True)
    stray = os.path.join(win._staging_dir(), "999.npy")
    np.save(stray, np.zeros(3))
    win.open_any(_fits(tmp_path, "second"))
    _idle(qtbot, win)
    assert _incoming(win) == []
    np.save(stray, np.zeros(3))
    win._dirty = False
    win.close()
    assert _incoming(win) == []
