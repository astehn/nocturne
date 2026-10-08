"""Every route that hands the window a new picture writes its first snapshot
off the UI thread (open-routes, 2026-10-08).

`no-freezes` moved the File > Open route; five more still let Project write
state_0 on the UI thread — ~1.1 s of frozen window for a Reset or a TIFF
verdict switch on the 33 MP M 8 drizzle. Each write here is HELD on the worker
(`_Saves`) so "while it writes" can be inspected.
"""
import io
import os
import threading

import numpy as np
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

import nocturne.ui.combine_dialog as combine_dialog_module
import nocturne.ui.main_window as mw
from nocturne.core.image import AstroImage
from nocturne.history.project import Project
from nocturne.history.project_store import load_project, save_project
from tests.ui.test_main_window import _window
from tests.ui.test_open_image_async import _fits, _idle, _incoming

_REAL_SAVE = np.save


class _Saves:
    """Stands in for np.save. Once armed (after the route's own setup, which
    opens a picture too), each write into the staging folder waits for its own
    gate, or fails when asked; every other write goes straight through. Any
    write at all made on the UI thread while armed is recorded."""

    def __init__(self):
        self.armed = False
        self.fail = False
        self.released = False
        self.gates = []
        self.reached = threading.Event()
        self.ui_writes = []

    def release(self, i=None):
        if i is None:
            self.released = True
            for g in self.gates:
                g.set()
        else:
            self.gates[i].set()

    def __call__(self, path, arr, *a, **k):
        if self.armed and threading.current_thread() is threading.main_thread():
            self.ui_writes.append(str(path))
        if self.armed and isinstance(path, str) and os.sep + "incoming" + os.sep in path:
            gate = threading.Event()
            self.gates.append(gate)
            self.reached.set()
            if not self.released:
                gate.wait(10)
            if self.fail:
                _REAL_SAVE(path, arr[:1], *a, **k)    # half a file, then the disk fills
                raise OSError("disk full")
        return _REAL_SAVE(path, arr, *a, **k)


@pytest.fixture
def saves(monkeypatch):
    s = _Saves()
    monkeypatch.setattr(mw.np, "save", s)
    yield s
    s.release()


def _npy_bytes(arr):
    buf = io.BytesIO()
    _REAL_SAVE(buf, arr)
    return buf.getvalue()


def _cache_bytes(win):
    d = win._cache_dir
    if not os.path.isdir(d):
        return {}
    return {n: open(os.path.join(d, n), "rb").read()
            for n in sorted(os.listdir(d)) if n.startswith("state_")}


def _picture(qtbot, tmp_path, *, stretched=True):
    win = _window(qtbot, tmp_path)
    win.show()
    win.open_fits(_fits(tmp_path, "first"))
    if stretched:
        win._go_to_id("stretch")
        win.apply_current({"amount": 0.3, "linked": True})
    win._dirty = False                     # no unsaved-changes question
    return win


def _state(win):
    """Everything an open replaces, the cache's bytes included."""
    p = win.project
    return dict(
        project=p,
        names=None if p is None else [n for n, _ in p.entries()],
        position=None if p is None else p.position,
        data=None if p is None else p.current().data.copy(),
        files=_cache_bytes(win),
        page=win._center_stack.currentWidget(),
        title=win.windowTitle(), label=getattr(win, "_source_label", None), path=win._project_path,
        stage=win.current_stage_id() if p is not None else None,
        dirty=win._dirty, gen=win._project_gen, tiff=win._opened_as_tiff,
    )


def _same(a, b):
    assert a["project"] is b["project"]
    for k in ("names", "position", "files", "page", "title", "label", "path", "stage",
              "dirty", "gen", "tiff"):
        assert a[k] == b[k], k
    if a["data"] is not None:
        assert np.array_equal(a["data"], b["data"])


def _image(value=0.7, size=16):
    return AstroImage(np.full((size, size, 3), value, np.float32), is_linear=False,
                      metadata={"note": "handed over"})


# --- the five routes ---------------------------------------------------------
# Each: (window, trigger, the pixels that must land, what must hold after).
def _combine(qtbot, tmp_path, monkeypatch):
    captured = {}

    class _Fake:
        def __init__(self, settings, parent=None, on_master=None):
            captured["on_master"] = on_master

        def exec(self):
            pass

    monkeypatch.setattr(combine_dialog_module, "CombineDialog", _Fake)
    win = _picture(qtbot, tmp_path)
    img = _image()

    def go():
        win._open_combine()
        captured["on_master"](img)

    def after(win, before):
        assert win._source_label == "combined narrowband"
        assert win._project_path is None
    return win, go, img.data, after


def _master(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)          # nothing open: the master opens
    win.show()
    img = _image(0.4)
    path = str(tmp_path / "master.fits")

    def after(win, before):
        assert win._source_label == "stacked master"
    return win, lambda: win._on_foreground_master(img, "stacked master", path), img.data, after


def _tiff_switch(qtbot, tmp_path, monkeypatch):
    win = _picture(qtbot, tmp_path, stretched=False)
    assert win.project.current().is_linear
    expected = win.project.current().data.copy()

    def after(win, before):
        assert win.project.current().is_linear is False
        assert win._opened_as_tiff is True
        assert win._source_label == before["label"]
        assert win._panel.panel_kind == "import"
    return win, lambda: win._set_opened_as_linear(False), expected, after


def _reset(qtbot, tmp_path, monkeypatch):
    win = _picture(qtbot, tmp_path)
    bundle = str(tmp_path / "mine.nocturne")
    save_project(win.project, bundle, source_label=win._source_label)
    win._project_path = bundle
    win._dirty = False
    win._update_title()
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    expected = win.project.state_at(0).data.copy()

    def after(win, before):
        # What Reset kept before it ran in the background: the same bundle,
        # marked changed (the file still holds the discarded edits), the label.
        assert win._project_path == before["path"] == bundle
        assert win._dirty is True
        assert win.windowTitle() != before["title"] and "mine" in win.windowTitle()
        assert win._source_label == before["label"]
        assert win.project.entries() == []
    return win, win._reset_image, expected, after


def _upscale(qtbot, tmp_path, monkeypatch):
    win = _picture(qtbot, tmp_path)
    img = _image(0.2, 48)

    def after(win, before):
        assert win._source_label == "stack_2x"
    return win, lambda: win._open_upscaled(img), img.data, after


ROUTES = [_combine, _master, _tiff_switch, _reset, _upscale]
IDS = ["combine", "foreground-master", "tiff-switch", "reset", "upscale-copy"]


def _count_hooks(win, monkeypatch):
    """How many times each route's `after` work and open_image ran."""
    calls = {"after": 0, "open_image": 0}
    real_bg, real_open = win._open_in_background, win.open_image

    def bg(image, label, *, after=None, **k):
        def counted():
            calls["after"] += 1
            after()
        return real_bg(image, label, after=counted if after else None, **k)

    def open_image(*a, **k):
        calls["open_image"] += 1
        return real_open(*a, **k)

    monkeypatch.setattr(win, "_open_in_background", bg)
    monkeypatch.setattr(win, "open_image", open_image)
    return calls


@pytest.mark.parametrize("route", ROUTES, ids=IDS)
def test_while_the_snapshot_is_written_the_window_answers_and_nothing_changes(
        qtbot, tmp_path, monkeypatch, saves, route):
    win, go, expected, after = route(qtbot, tmp_path, monkeypatch)
    saves.armed = True
    win._async_enabled = True
    calls = _count_hooks(win, monkeypatch)
    before = _state(win)
    try:
        go()
        assert saves.reached.wait(5), "the snapshot was not written in the background"
        assert win._busy
        ticked = []
        QTimer.singleShot(0, lambda: ticked.append(1))
        qtbot.waitUntil(lambda: bool(ticked), timeout=2000)     # the event loop runs
        qtbot.wait(30)
        _same(before, _state(win))           # nothing replaced until the write lands
        assert calls["open_image"] == 0
    finally:
        saves.release()
        _idle(qtbot, win)
    assert win.project is not before["project"]
    assert np.array_equal(win.project.current().data, expected)
    # Byte for byte what Project would have written itself.
    with open(win.project._paths[0], "rb") as f:
        assert f.read() == _npy_bytes(expected)
    assert calls["open_image"] == 1
    assert saves.ui_writes == [], "a snapshot was written on the UI thread"
    assert calls["after"] in (0, 1)
    if route in (_tiff_switch, _reset):
        assert calls["after"] == 1, "the route's own work after the open ran once"
    after(win, before)
    assert win.current_stage_id() == "load"
    assert _incoming(win) == []
    assert not win._busy and win.stepper.isEnabled()


@pytest.mark.parametrize("route", ROUTES, ids=IDS)
def test_a_failed_write_leaves_the_workspace_history_and_cache_as_they_were(
        qtbot, tmp_path, monkeypatch, saves, route):
    win, go, _expected, _after = route(qtbot, tmp_path, monkeypatch)
    saves.armed = True
    win._async_enabled = True
    calls = _count_hooks(win, monkeypatch)
    saves.fail = True
    saves.release()
    before = _state(win)
    go()
    _idle(qtbot, win)
    _same(before, _state(win))
    assert calls == {"after": 0, "open_image": 0}
    assert "disk full" in win._warning.text()
    assert _incoming(win) == []


def test_a_master_that_fails_to_open_says_where_it_is(qtbot, tmp_path, monkeypatch, saves):
    win, go, _e, _a = _master(qtbot, tmp_path, monkeypatch)
    saves.armed = True
    win._async_enabled = True
    saves.fail = True
    saves.release()
    go()
    _idle(qtbot, win)
    assert str(tmp_path / "master.fits") in win._warning.text()


def test_the_routes_still_open_synchronously_when_async_is_off(qtbot, tmp_path, monkeypatch):
    """`_async_enabled = False` is how the rest of the suite drives them."""
    for i, route in enumerate(ROUTES):
        d = tmp_path / str(i)
        d.mkdir()
        win, go, expected, after = route(qtbot, d, monkeypatch)
        before = _state(win)
        go()
        assert not win._busy
        assert np.array_equal(win.project.current().data, expected), IDS[i]
        after(win, before)


# --- Cancel ------------------------------------------------------------------
def test_cancel_during_a_reset_keeps_every_edit(qtbot, tmp_path, monkeypatch, saves):
    win, go, _e, _a = _reset(qtbot, tmp_path, monkeypatch)
    saves.armed = True
    win._async_enabled = True
    before = _state(win)
    try:
        go()
        assert saves.reached.wait(5)
        win._cancel_btn.click()
    finally:
        saves.release()
        _idle(qtbot, win)
    _same(before, _state(win))
    assert "Cancelled" in win.output_panel.toPlainText()
    assert _incoming(win) == []


@pytest.mark.parametrize("route", [_combine, _master, _upscale],
                         ids=["combine", "foreground-master", "upscale-copy"])
def test_cancel_does_not_throw_away_a_result_that_exists_nowhere_else(
        qtbot, tmp_path, monkeypatch, saves, route):
    """Cancel stops EVERY running op: pressed for a step running alongside, it
    must not take the finished result with it."""
    win, go, expected, _a = route(qtbot, tmp_path, monkeypatch)
    saves.armed = True
    win._async_enabled = True
    try:
        go()
        assert saves.reached.wait(5)
        win._cancel_active()
    finally:
        saves.release()
        _idle(qtbot, win)
    assert np.array_equal(win.project.current().data, expected)
    assert _incoming(win) == []


# --- busy-time arrival ---------------------------------------------------------
@pytest.mark.parametrize("route", [_combine, _master], ids=["combine", "foreground-master"])
def test_a_result_arriving_while_a_step_runs_is_opened_not_lost(qtbot, tmp_path, monkeypatch,
                                                                route):
    win, go, expected, _a = route(qtbot, tmp_path, monkeypatch)
    win._async_enabled = True
    step_gate = threading.Event()
    landed = []
    win._run_busy(lambda: step_gate.wait(10), lambda r: landed.append(r),
                  "Running a step…", "Step failed")
    try:
        assert win._busy
        go()                                   # arrives mid-step
        qtbot.waitUntil(lambda: win.project is not None
                        and np.array_equal(win.project.current().data, expected),
                        timeout=5000)
    finally:
        step_gate.set()
        _idle(qtbot, win)
    assert np.array_equal(win.project.current().data, expected)
    assert landed == [], "the step belonged to the replaced picture; its result is dropped"
    assert _incoming(win) == []


def test_the_latest_open_wins_over_a_route(qtbot, tmp_path, monkeypatch, saves):
    """A route's open and a file open share `_open_seq`: the one asked for last
    lands, whichever finishes first."""
    win, go, _expected, _a = _upscale(qtbot, tmp_path, monkeypatch)
    saves.armed = True
    win._async_enabled = True
    second = _fits(tmp_path, "second")
    try:
        go()
        assert saves.reached.wait(5)
        saves.reached.clear()
        win.open_any(second)                   # code can; every door refuses while busy
        assert saves.reached.wait(5)
        saves.release(0)                       # the route's write finishes FIRST
        qtbot.waitUntil(lambda: len(win._running) == 1, timeout=5000)
        qtbot.wait(20)
        assert win._source_label == "stack.fits", "the superseded copy landed"
        assert _incoming(win) == [], "the superseded write removes its own file"
    finally:
        saves.release()
        _idle(qtbot, win)
    assert np.array_equal(win.project.current().data, mw.load_fits(second).data)
    assert _incoming(win) == []


# --- Cancel during a project load -----------------------------------------------
def _long_bundle(tmp_path, steps=4):
    """A bundle whose history replays one restored state at a time."""
    d = tmp_path / "bundle_cache"
    p = Project(_image(0.1, 24), str(d))
    for i in range(steps):
        p.record_precomputed("Star Spikes", "", _image(0.2 + 0.1 * i, 24))
    path = str(tmp_path / "long.nocturne")
    save_project(p, path, source_label="long.fits")
    return path


class _HeldAtStep:
    """The real load, held after its first step until released."""

    def __init__(self):
        self.at_step = threading.Event()
        self.gate = threading.Event()
        self.progress = []
        self.dirs = []

    def __call__(self, path, cache_dir, on_progress=None):
        self.dirs.append(cache_dir)

        def held(done, total):
            self.progress.append(done)
            if done == 1:
                self.at_step.set()
                self.gate.wait(10)
            if on_progress is not None:
                on_progress(done, total)
        return load_project(path, cache_dir, on_progress=held)


@pytest.mark.parametrize("button", ["right-panel", "start-page"])
def test_cancel_during_a_project_load_lands_within_one_step(qtbot, tmp_path, button):
    if button == "start-page":
        win = _window(qtbot, tmp_path)
        win.show()
    else:
        win = _picture(qtbot, tmp_path)
    bundle = _long_bundle(tmp_path)
    win._async_enabled = True
    held = _HeldAtStep()
    win._load_project_fn = held
    before = _state(win)
    try:
        win._open_project(bundle)
        assert held.at_step.wait(10)
        qtbot.waitUntil(lambda: win._busy_shown, timeout=3000)
        btn = win._welcome.busy_cancel if button == "start-page" else win._cancel_btn
        assert btn.isVisible() and btn.isEnabled()
        btn.click()
    finally:
        held.gate.set()
        _idle(qtbot, win)
    assert held.progress == [1], f"the load ran on past the Cancel: {held.progress}"
    _same(before, _state(win))
    assert "Cancelled" in win.output_panel.toPlainText()
    assert not os.path.exists(held.dirs[0]), "the staging folder is removed"
    assert _incoming(win) == []


def test_load_project_polls_the_ambient_token(tmp_path):
    """The store itself, without the window: a cancelled token stops the replay."""
    from nocturne.core import tasks
    bundle = _long_bundle(tmp_path)
    tok = tasks.CancelToken()
    seen = []

    def progress(done, total):
        seen.append(done)
        if done == 2:
            tok.cancel()

    tasks.set_ambient(tok)
    try:
        with pytest.raises(tasks.Cancelled):
            load_project(bundle, str(tmp_path / "out"), on_progress=progress)
    finally:
        tasks.clear_ambient()
    assert seen == [1, 2]


# --- review round 1 ------------------------------------------------------------
def _linear_tiff_window(qtbot, tmp_path):
    from tests.ui.test_open_tiff import _write_linear_tiff
    win = _window(qtbot, tmp_path)
    win.show()
    win.open_any(_write_linear_tiff(tmp_path))
    win._dirty = False
    assert win.project.current().is_linear and win._panel.opened_as_linear.isChecked()
    return win


def _stretched_radio(win):
    return next(b for b in win._panel._opened_group.buttons()
                if b is not win._panel.opened_as_linear)


@pytest.mark.parametrize("outcome", ["cancel", "failed-write"])
def test_the_reading_switch_snaps_back_when_the_reread_does_not_land(qtbot, tmp_path, saves,
                                                                     outcome):
    win = _linear_tiff_window(qtbot, tmp_path)
    win._async_enabled = True
    saves.armed = True
    saves.fail = outcome == "failed-write"
    try:
        _stretched_radio(win).click()
        assert saves.reached.wait(5)
        if outcome == "cancel":
            win._cancel_btn.click()
    finally:
        saves.release()
        _idle(qtbot, win)
    assert win.project.current().is_linear is True
    assert win._panel.opened_as_linear.isChecked() == win.project.current().is_linear
    # And the switch still works: the click starts a re-read again.
    saves.fail = False
    saves.reached.clear()
    _stretched_radio(win).click()
    assert saves.reached.wait(5)
    _idle(qtbot, win)
    assert win.project.current().is_linear is False
    assert win._panel.opened_as_linear.isChecked() is False


def _held_open_any(qtbot, tmp_path, monkeypatch, saves, *, bundle):
    """A dirty picture with a cancellable open (File > Open) held mid-write."""
    win = _picture(qtbot, tmp_path)
    win._async_enabled = True
    if bundle:
        save_project(win.project, bundle, source_label=win._source_label)
        win._project_path = bundle
    saves.armed = True
    win.open_any(_fits(tmp_path, "second"))
    assert saves.reached.wait(5)
    win._dirty = True                  # edits made since; the open asked before them
    return win


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def test_quit_with_an_open_in_flight_does_not_lose_a_requested_save(qtbot, tmp_path,
                                                                    monkeypatch, saves):
    """The open lands inside the save's wait, replaces the workspace and drops
    the save. Quit must not go ahead as though it had saved."""
    bundle = str(tmp_path / "mine.nocturne")
    win = _held_open_any(qtbot, tmp_path, monkeypatch, saves, bundle=bundle)
    before = _bytes(bundle)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Save)
    save_gate = threading.Event()
    real_save_project = mw.save_project

    def held_save(*a, **k):
        save_gate.wait(10)
        return real_save_project(*a, **k)

    monkeypatch.setattr(mw, "save_project", held_save)
    try:
        QTimer.singleShot(100, saves.release)       # the open lands mid-wait
        QTimer.singleShot(400, save_gate.set)        # then the save runs on
        win.close()
    finally:
        saves.release()
        save_gate.set()
        _idle(qtbot, win)
    assert win.isVisible(), "quit went ahead without the save it was asked for"
    assert _bytes(bundle) == before
    assert "was not saved" in win._warning.text()
    assert _incoming(win) == []


def test_an_open_landing_inside_the_quit_question_does_not_take_the_answer(
        qtbot, tmp_path, monkeypatch, saves):
    """The question is a nested event loop. "Save" answered about the picture
    the user was looking at must not save the one that replaced it."""
    bundle = str(tmp_path / "mine.nocturne")
    win = _held_open_any(qtbot, tmp_path, monkeypatch, saves, bundle=bundle)
    before = _bytes(bundle)
    old = win.project
    dialogs = []
    monkeypatch.setattr(mw.file_dialogs, "save_file",
                        lambda *a, **k: (dialogs.append(a), ("", ""))[1])

    def answer(*a, **k):
        saves.release()
        qtbot.waitUntil(lambda: win.project is not old, timeout=5000)   # it lands here
        return QMessageBox.StandardButton.Save

    monkeypatch.setattr(QMessageBox, "question", answer)
    try:
        win.close()
    finally:
        saves.release()
        _idle(qtbot, win)
    assert win.project is not old, "precondition: the open landed inside the question"
    assert win.isVisible()
    assert "another picture opened" in win._warning.text()
    assert _bytes(bundle) == before
    assert dialogs == [], "no Save As for the picture nobody was asked about"
    assert [n for n in os.listdir(tmp_path) if n.endswith(".nocturne")] == ["mine.nocturne"]


def test_an_open_landing_inside_save_as_writes_nothing(qtbot, tmp_path, monkeypatch, saves):
    win = _held_open_any(qtbot, tmp_path, monkeypatch, saves, bundle=None)
    old = win.project
    target = str(tmp_path / "chosen.nocturne")
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Save)

    def choose(*a, **k):
        saves.release()
        qtbot.waitUntil(lambda: win.project is not old, timeout=5000)
        return target, ""

    monkeypatch.setattr(mw.file_dialogs, "save_file", choose)
    try:
        win.close()
    finally:
        saves.release()
        _idle(qtbot, win)
    assert win.project is not old
    assert win.isVisible()
    assert not os.path.exists(target), "the new picture was saved under the old intent"
    assert "Not saved" in win._warning.text()


def test_quit_waits_for_a_result_that_cannot_be_cancelled(qtbot, tmp_path, monkeypatch, saves):
    win, go, expected, _a = _combine(qtbot, tmp_path, monkeypatch)
    win._async_enabled = True
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: (asked.append(1), QMessageBox.StandardButton.Discard)[1])
    saves.armed = True
    try:
        go()
        assert saves.reached.wait(5)
        win._dirty = True                  # so a question WOULD be asked
        win.close()
        assert win.isVisible() and asked == [], "refused before any question"
        assert "Finishing" in win._warning.text()
    finally:
        saves.release()
        _idle(qtbot, win)
    assert np.array_equal(win.project.current().data, expected)
    win._dirty = False
    win.close()
    assert not win.isVisible()
    assert _incoming(win) == []


def test_combine_asks_before_replacing_unsaved_edits(qtbot, tmp_path, monkeypatch):
    win, go, expected, _a = _combine(qtbot, tmp_path, monkeypatch)
    win._dirty = True
    old = win.project
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Cancel)
    go()
    assert win.project is old and win._dirty
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Discard)
    go()
    assert np.array_equal(win.project.current().data, expected)


def test_a_declined_combine_keeps_the_dialog_open_and_says_why(qtbot):
    from nocturne.settings import Settings
    from nocturne.ui.combine_dialog import CombineDialog
    d = CombineDialog(Settings(), on_master=lambda img: False)
    qtbot.addWidget(d)
    accepted = []
    d.accepted.connect(lambda: accepted.append(1))
    d._on_done(_image())
    assert accepted == []
    assert "Not opened" in d.status.text() and "Combine again" in d.status.text()


def test_a_write_dropped_by_a_replaced_workspace_removes_its_file(qtbot, tmp_path,
                                                                  monkeypatch, saves):
    """Its result reaches only _run_busy's generation check, which used to drop
    it without a word — leaving 400 MB at 33 MP in cache/incoming."""
    win, go, _expected, _a = _combine(qtbot, tmp_path, monkeypatch)
    win._async_enabled = True
    monkeypatch.setattr(mw, "current_token", lambda: None)   # only the landing can clean up
    saves.armed = True
    try:
        go()
        assert saves.reached.wait(5)
        win._swap_workspace()                  # what quit and every other open do
    finally:
        saves.release()
        _idle(qtbot, win)
    assert _incoming(win) == []


@pytest.mark.parametrize("route", [_combine, _master, _upscale],
                         ids=["combine", "foreground-master", "upscale-copy"])
def test_cancel_is_not_offered_for_a_write_it_would_not_stop(qtbot, tmp_path, monkeypatch,
                                                             saves, route):
    win, go, _expected, _a = route(qtbot, tmp_path, monkeypatch)
    win._async_enabled = True
    saves.armed = True
    step_gate = threading.Event()
    try:
        go()
        assert saves.reached.wait(5)
        qtbot.waitUntil(lambda: win._busy_shown, timeout=3000)
        for btn in (win._cancel_btn, win._welcome.busy_cancel):
            assert not btn.isEnabled() and btn.text() == "Finishing…"
        # A step running beside it: Cancel is for the step again.
        win._run_busy(lambda: step_gate.wait(10), lambda r: None, "Running a step…", "Step")
        for btn in (win._cancel_btn, win._welcome.busy_cancel):
            assert btn.isEnabled() and btn.text() == "Cancel"
        step_gate.set()
        qtbot.waitUntil(lambda: len(win._running) == 1, timeout=5000)
        assert not win._cancel_btn.isEnabled()
    finally:
        step_gate.set()
        saves.release()
        _idle(qtbot, win)
    # The next op offers Cancel as usual.
    held = threading.Event()
    win._run_busy(lambda: held.wait(10), lambda r: None, "Another step…", "Step")
    try:
        assert win._cancel_btn.isEnabled() and win._cancel_btn.text() == "Cancel"
    finally:
        held.set()
        _idle(qtbot, win)


def _ui_loads(monkeypatch):
    seen = []
    real = Project._load

    def spy(self, i):
        if threading.current_thread() is threading.main_thread():
            seen.append(i)
        return real(self, i)

    monkeypatch.setattr(Project, "_load", spy)
    return seen


@pytest.mark.parametrize("route", [_reset, _tiff_switch], ids=["reset", "tiff-switch"])
def test_a_route_reads_the_pixels_once_on_the_ui_thread_to_paint_them(qtbot, tmp_path,
                                                                      monkeypatch, route):
    """Reset of the M 8 drizzle reloaded the whole state ten times on the UI
    thread (TIFF switch: twelve) for booleans, metadata and a shape."""
    win, go, _expected, _a = route(qtbot, tmp_path, monkeypatch)
    win._async_enabled = True
    seen = _ui_loads(monkeypatch)
    go()
    _idle(qtbot, win)
    assert seen == [0], seen


def test_a_step_click_reads_the_pixels_once(qtbot, tmp_path, monkeypatch):
    win = _picture(qtbot, tmp_path)
    win._go_to_id("load")
    seen = _ui_loads(monkeypatch)
    win._go_to_id("background")
    assert len(seen) == 1, seen
