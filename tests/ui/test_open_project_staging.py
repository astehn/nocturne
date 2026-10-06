"""Opening a project loads into a staging folder, never the live cache.

Found while moving image opens off the UI thread (2026-10-06): load_project
wrote state_0..N.npy into the SAME cache folder the current picture's history
lives in, while it was still the current picture. During a slow load, and for
good after a failed one, peek / Before-After / undo read the other bundle's
pixels — and Cmd-S wrote them into the user's own bundle.
"""
import os
import threading

import numpy as np
import pytest
from PySide6.QtCore import QThreadPool

from nocturne.history.project_store import load_project, save_project
from tests.ui.test_open_image_async import _fits, _idle
from tests.ui.test_main_window import _window


def _cache_bytes(win):
    d = win._cache_dir
    return {n: open(os.path.join(d, n), "rb").read()
            for n in sorted(os.listdir(d)) if n.startswith("state_")}


def _states(win):
    return [win.project.state_at(i).data.copy() for i in range(len(win.project._paths))]


def _live(win):
    return dict(files=_cache_bytes(win), states=_states(win),
                current=win.project.current().data.copy(), project=win.project)


def _unchanged(before, win):
    assert win.project is before["project"]
    assert _cache_bytes(win) == before["files"], "the live cache was written to"
    after = _states(win)
    assert len(after) == len(before["states"])
    for a, b in zip(after, before["states"]):
        assert np.array_equal(a, b)
    assert np.array_equal(win.project.current().data, before["current"])


def _staged(win):
    d = win._staging_dir()
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def _bundle(qtbot, tmp_path):
    """A different picture, saved as a bundle with a SHORTER history than the
    open one (1 state against 2), so an old state left behind would show."""
    other = _window(qtbot, tmp_path / "other_settings")
    other.open_fits(_fits(tmp_path, "other"))
    path = str(tmp_path / "other.nocturne")
    save_project(other.project, path, source_label="other.fits")
    return path


@pytest.fixture
def setup(qtbot, tmp_path):
    (tmp_path / "other_settings").mkdir()
    bundle = _bundle(qtbot, tmp_path)
    win = _window(qtbot, tmp_path)
    win.show()
    win.open_fits(_fits(tmp_path, "mine"))
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.3, "linked": True})
    win._dirty = False                 # no unsaved-changes question
    win._async_enabled = True
    return win, bundle


class _Held:
    """The real load, run to the end (every state written) and then held."""

    def __init__(self, fail=False):
        self.gate = threading.Event()
        self.loaded = threading.Event()
        self.fail = fail
        self.dirs = []

    def __call__(self, path, cache_dir, on_progress=None):
        self.dirs.append(cache_dir)
        result = load_project(path, cache_dir, on_progress=on_progress)
        self.loaded.set()
        self.gate.wait(10)
        if self.fail:
            raise OSError("disk went away")
        return result


def test_while_a_project_loads_the_current_picture_is_untouched(qtbot, setup):
    win, bundle = setup
    held = _Held()
    win._load_project_fn = held
    before = _live(win)
    try:
        win._open_project(bundle)
        assert held.loaded.wait(10)
        assert os.listdir(held.dirs[0]), "precondition: the load has written its states"
        _unchanged(before, win)
        win._peek_before()                       # what peek reads mid-load
        _unchanged(before, win)
    finally:
        held.gate.set()
        _idle(qtbot, win)
    want = load_project(bundle, str(win._cache_dir) + "_check")
    assert win.project is not before["project"]
    assert np.array_equal(win.project.current().data, want.project.current().data)
    n = len(win.project._paths)
    assert sorted(_cache_bytes(win)) == sorted(f"state_{i}.npy" for i in range(n))
    for i in range(n):
        assert np.array_equal(win.project.state_at(i).data, want.project.state_at(i).data)
    assert _staged(win) == []


def test_a_load_that_fails_after_writing_leaves_the_live_cache_exactly_as_it_was(qtbot, setup,
                                                                                tmp_path):
    win, bundle = setup
    held = _Held(fail=True)
    win._load_project_fn = held
    before = _live(win)
    win._open_project(bundle)
    assert held.loaded.wait(10)
    held.gate.set()
    _idle(qtbot, win)
    _unchanged(before, win)
    assert win._warning.text().startswith("Could not open project")
    assert _staged(win) == []
    # What Cmd-S would write is THIS picture's pixels.
    out = str(tmp_path / "mine.nocturne")
    save_project(win.project, out)
    back = load_project(out, str(tmp_path / "back"))
    assert np.array_equal(back.project.state_at(0).data, before["states"][0])
    assert np.array_equal(back.project.current().data, before["current"])


def test_a_corrupt_bundle_changes_nothing(qtbot, setup, tmp_path):
    win, _bundle_path = setup
    bad = tmp_path / "bad.nocturne"
    bad.write_bytes(b"not a zip")
    before = _live(win)
    win._open_project(str(bad))
    _idle(qtbot, win)
    _unchanged(before, win)
    assert win._warning.text().startswith("Could not open project")
    assert _staged(win) == []


def test_cancel_and_supersede_remove_their_staging(qtbot, setup):
    win, bundle = setup
    held = _Held()
    win._load_project_fn = held
    before = _live(win)
    win._open_project(bundle)
    assert held.loaded.wait(10)
    win._cancel_active()
    held.gate.set()
    _idle(qtbot, win)
    _unchanged(before, win)
    assert _staged(win) == []

    first, second = _Held(), _Held()
    calls = iter([first, second])
    win._load_project_fn = lambda *a, **k: next(calls)(*a, **k)
    try:
        win._open_project(bundle)
        win._open_project(bundle)
        assert first.loaded.wait(10) and second.loaded.wait(10)
        first.gate.set()                         # the older one lands first: dropped
        qtbot.waitUntil(lambda: len(win._running) == 1, timeout=5000)
        qtbot.wait(20)
        _unchanged(before, win)
        assert _staged(win) == [os.path.basename(second.dirs[0])]
    finally:
        first.gate.set()
        second.gate.set()
        _idle(qtbot, win)
    assert _staged(win) == []
    assert win.project is not before["project"]


def test_a_project_open_paints_once(qtbot, setup, monkeypatch):
    win, bundle = setup
    painted = []
    real = win._set_canvas
    monkeypatch.setattr(win, "_set_canvas", lambda img, *a, **k: (painted.append(1),
                                                                   real(img, *a, **k)))
    win._open_project(bundle)
    _idle(qtbot, win)
    assert len(painted) == 1
    shown = win.image_view._item.pixmap().toImage().copy()
    win._refresh()
    assert win.image_view._item.pixmap().toImage() == shown


# --- closing while an image opens ------------------------------------------------
def test_closing_while_an_image_opens_leaves_nothing_staged(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    gate, read_done = threading.Event(), threading.Event()
    real = mw.load_fits

    def held(path):
        read_done.set()
        gate.wait(10)
        return real(path)

    win = _window(qtbot, tmp_path)
    win.show()
    win.open_fits(_fits(tmp_path, "mine"))
    win._async_enabled = True
    monkeypatch.setattr(mw, "load_fits", held)
    opened = []
    real_open = win.open_image
    win.open_image = lambda *a, **k: (opened.append(a), real_open(*a, **k))
    win.open_any(_fits(tmp_path, "second"))
    assert read_done.wait(10)
    win._dirty = False
    win.close()
    gate.set()
    QThreadPool.globalInstance().waitForDone(10000)    # the worker has finished
    qtbot.wait(50)                                     # and its callback has run
    assert opened == [], "a load landing after close adopted nothing"
    assert _staged(win) == []


def test_a_staged_snapshot_gone_before_it_lands_is_written_again(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    win = _window(qtbot, tmp_path)
    win.show()
    win.open_fits(_fits(tmp_path, "mine"))
    win._async_enabled = True
    real_save = mw.np.save
    vanish = []

    def save_then_vanish(path, arr, *a, **k):
        real_save(path, arr, *a, **k)
        if "incoming" in str(path):
            os.remove(path)                    # pruned, or tidied away, before landing
            vanish.append(path)

    monkeypatch.setattr(mw.np, "save", save_then_vanish)
    second = _fits(tmp_path, "second")
    win.open_any(second)
    _idle(qtbot, win)
    assert vanish, "precondition: the staged file did vanish"
    assert win._source_label == "stack.fits"
    assert np.array_equal(np.load(win.project._paths[0]), mw.load_fits(second).data)
    assert not win._warning.text()


# --- final review: adoption, close, and the files-present guard -------------------
def _cache_states(win):
    d = win._cache_dir
    return sorted(n for n in os.listdir(d) if n.startswith("state_")) if os.path.isdir(d) else []


def test_a_project_load_landing_after_close_adopts_nothing(qtbot, setup):
    win, bundle = setup
    held = _Held()
    win._load_project_fn = held
    adopted = []
    real = win._apply_loaded_project
    win._apply_loaded_project = lambda *a, **k: (adopted.append(a), real(*a, **k))
    win._open_project(bundle)
    assert held.loaded.wait(10)
    assert _staged(win), "precondition: the load has staged its states"
    win.close()
    held.gate.set()
    QThreadPool.globalInstance().waitForDone(10000)
    qtbot.wait(50)
    assert adopted == [], "a load landing after close adopted nothing"
    assert _staged(win) == []
    assert _cache_states(win) == []


def test_working_files_gone_before_adoption_change_nothing(qtbot, setup):
    """The files_present() guard: a staged state removed before the result
    lands (pruned, tidied away) must not be adopted as a broken history."""
    win, bundle = setup
    held = _Held()
    win._load_project_fn = held
    before = _live(win)
    win._open_project(bundle)
    assert held.loaded.wait(10)
    for root, _dirs, files in os.walk(held.dirs[0]):
        for n in files:
            if n.startswith("state_"):
                os.remove(os.path.join(root, n))
    held.gate.set()
    _idle(qtbot, win)
    _unchanged(before, win)
    assert "disappeared while it loaded" in win._warning.text()
    assert _staged(win) == []


def test_adoption_that_fails_mid_move_lands_on_the_start_page(qtbot, setup, monkeypatch):
    from nocturne.history.project import Project
    win, bundle = setup
    real = Project.relocate
    moved = []

    def half_then_fail(self, cache_dir):
        src = self._paths[0]
        os.replace(src, os.path.join(cache_dir, "state_0.npy"))   # one file moved
        moved.append(src)
        raise OSError("disk went away")
    monkeypatch.setattr(Project, "relocate", half_then_fail)
    warned = []
    real_warn = win._show_warning
    monkeypatch.setattr(win, "_show_warning", lambda m: (warned.append(m), real_warn(m)))
    win._open_project(bundle)
    _idle(qtbot, win)
    assert moved, "precondition: the move started"
    assert win.project is None
    assert win._center_stack.currentWidget() is win._welcome
    assert not win.stepper.isVisible()
    assert warned == ["Could not open project: disk went away"]
    assert _staged(win) == [] and _cache_states(win) == []
    assert win._project_path is None and not win._dirty
    monkeypatch.setattr(Project, "relocate", real)


def test_adoption_prunes_what_superseded_opens_staged(qtbot, setup):
    win, bundle = setup
    stray = os.path.join(win._staging_dir(), "p999")
    os.makedirs(stray)
    open(os.path.join(stray, "state_0.npy"), "wb").close()
    win._open_project(bundle)
    _idle(qtbot, win)
    assert win._project_path == bundle
    assert _staged(win) == []


def test_startup_prunes_what_a_crash_staged(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    stray = os.path.join(win._staging_dir(), "i7")
    os.makedirs(stray)
    open(os.path.join(stray, "staged.npy"), "wb").close()
    again = _window(qtbot, tmp_path)
    assert again._staging_dir() == win._staging_dir()
    assert _staged(again) == []
