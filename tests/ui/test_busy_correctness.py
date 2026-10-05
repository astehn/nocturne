"""One job at a time, and nothing a running job did not ask for is lost.

Audit 2026-10-05 (docs/audit/2026-10-05-busy-controls-audit.md):
- the stepper stayed live during a run, so a second job could start; when it
  ended first it released busy for the FIRST job too, the UI went idle with
  Noise Reduction still on the worker, and a De-green applied then was wiped
  out of the pixels when NR landed (finding 2) — wrong data committed;
- toolbar tools stayed enabled while busy and dropped their OK silently;
- a slider moved during Apply was forgotten when the commit landed;
- `_fringe_prepare` mutated the shared split store on the worker thread, and a
  split that landed after the user left its step was thrown away.

Every run here is held on the worker (a patched `run_async`) until the test
releases it, so "during" is a real, inspectable state, not a race.
"""
import threading

import numpy as np
import pytest

import nocturne.ui.main_window as mw
from PySide6.QtWidgets import QMenu
from nocturne.core.image import AstroImage
from tests.ui.test_main_window import _window


class Holder:
    """Every run_async call waits on its own Event until released."""

    def __init__(self, monkeypatch):
        self.events = []
        real = mw.run_async

        def held(pool, fn, done, err=None, *a, **k):
            ev = threading.Event()
            self.events.append(ev)

            def wrapped():
                ev.wait(15)
                return fn()
            return real(pool, wrapped, done, err, *a, **k)
        monkeypatch.setattr(mw, "run_async", held)

    def release(self, i=None):
        for j, ev in enumerate(self.events):
            if i is None or j == i:
                ev.set()


def _make(qtbot, tmp_path, monkeypatch, *, hold=True):
    monkeypatch.setattr(mw, "preferred_splitter", lambda s: "starnet")

    def fake_split(self, base):
        d = base.data
        return (AstroImage(d * 0.9, is_linear=False, metadata={}),
                AstroImage(d * 0.1, is_linear=False, metadata={}), "StarNet2")
    monkeypatch.setattr(mw.MainWindow, "_split_tagged", fake_split)
    win = _window(qtbot, tmp_path)
    rng = np.random.default_rng(0)
    data = (0.2 + 0.1 * rng.random((64, 64, 3))).astype(np.float32)
    win.open_image(AstroImage(data, is_linear=False, metadata={}), "t")
    win.resize(1400, 900)
    win.show()
    qtbot.waitExposed(win)
    holder = Holder(monkeypatch) if hold else None
    win._async_enabled = True
    monkeypatch.setattr(win, "_ask_pending", lambda *a, **k: "discard")
    return win, holder


def _idle(qtbot, win):
    qtbot.waitUntil(lambda: not win._busy, timeout=8000)
    qtbot.wait(30)


def _names(win):
    return [n for n, _ in win.project.entries()]


def _index(win, sid):
    return next(i for i, s in enumerate(win._stages) if s.id == sid)


def _press_apply(win):
    assert win._panel.apply_btn.isEnabled(), "fixture: Apply is not enabled"
    win._panel.apply_btn.click()


# ---------------------------------------------------------------- A1: stepper
def test_stepper_refuses_a_click_while_a_step_runs(qtbot, tmp_path, monkeypatch):
    win, h = _make(qtbot, tmp_path, monkeypatch)
    win._go_to_id("local_contrast", user_initiated=False); qtbot.wait(20)
    win._panel.lc_slider.setValue(40); qtbot.wait(20)
    _press_apply(win); qtbot.wait(30)
    assert win._busy and len(h.events) == 1
    stage = win.current_stage_id()

    assert win.stepper.isEnabled() is False
    win.stepper.stageSelected.emit(_index(win, "curves"))
    qtbot.wait(30)
    assert win.current_stage_id() == stage
    assert len(h.events) == 1, "a second job started"

    h.release(); _idle(qtbot, win)
    assert win.stepper.isEnabled() is True


# ---------------------------------------------------------------- A1: toolbar
_LOCKED_TOOLBAR = ("Open Image", "Open Project", "Save Project", "Settings",
                   "Auto Enhance", "Stack…", "Ha/OIII…", "Combine…", "Narrowband…",
                   "Colour Balance", "Star Spikes…", "Starless Levels…", "Trim",
                   "Upscale Crop", "Share", "Save Recipe", "Batch…")
_LOCKED_MENU = ("Open Project…", "Save Project", "Save Project As…",
                "Recent Projects", "Close Project")
_LIVE_TOOLBAR = ("Before/After", "Fit", "100%")
_LIVE_MENU = ("Help…", "Activity", "Report a problem…")


def _toolbar(win, text):
    # all_actions, not toolbar.actions(): a tool in the More menu right now is
    # off the bar but is still the action its proxy triggers.
    hit = [a for a in win._overflow.all_actions if a.text() == text]
    assert len(hit) == 1, f"toolbar action {text!r}: {len(hit)} found"
    return hit[0]


def _menu(win, text):
    # findChildren, not menuBar().actions()[i].menu(): that wrapper chain let
    # PySide delete a QMenu under the test.
    hit = [a for menu in win.menuBar().findChildren(QMenu)
           for a in menu.actions() if a.text() == text]
    assert len(hit) == 1, f"menu action {text!r}: {len(hit)} found"
    return hit[0]


def _locked_controls(win):
    out = {f"tb:{t}": _toolbar(win, t) for t in _LOCKED_TOOLBAR}
    out.update({f"menu:{t}": _menu(win, t) for t in _LOCKED_MENU})
    for t in _LOCKED_TOOLBAR:          # the More menu's copy must not stay live
        act = _toolbar(win, t)
        if act in win._overflow._proxy:
            out[f"more:{t}"] = win._overflow.proxy_for(act)
    out["welcome:open"] = win._welcome.open_btn
    out["welcome:stack"] = win._welcome.stack_btn
    return out


def _live_controls(win):
    out = {f"tb:{t}": _toolbar(win, t) for t in _LIVE_TOOLBAR}
    out.update({f"menu:{t}": _menu(win, t) for t in _LIVE_MENU})
    out["menu:About"] = win._about_act
    out["cancel"] = win._cancel_btn
    return out


def test_tools_settings_and_open_close_are_locked_while_busy(qtbot, tmp_path, monkeypatch):
    win, h = _make(qtbot, tmp_path, monkeypatch)
    win._go_to_id("local_contrast", user_initiated=False); qtbot.wait(20)
    locked = _locked_controls(win)
    before = {k: w.isEnabled() for k, w in locked.items()}
    assert sum(before.values()) >= 10, f"fixture: too few tools on to prove anything {before}"
    live = _live_controls(win)
    live_before = {k: w.isEnabled() for k, w in live.items()}

    win._panel.lc_slider.setValue(40); qtbot.wait(20)
    _press_apply(win); qtbot.wait(30)
    assert win._busy
    during = {k: w.isEnabled() for k, w in locked.items()}
    assert [k for k, on in during.items() if on] == []
    # The view and help stay usable: locking is for what can start work.
    assert {k: w.isEnabled() for k, w in live.items()} == live_before

    h.release(); _idle(qtbot, win)
    assert {k: w.isEnabled() for k, w in locked.items()} == before


def test_an_action_that_was_off_stays_off_after_the_run(qtbot, tmp_path, monkeypatch):
    win, h = _make(qtbot, tmp_path, monkeypatch)
    win._go_to_id("local_contrast", user_initiated=False); qtbot.wait(20)
    win._share_act.setEnabled(False)      # legitimately off, whatever the reason
    win._panel.lc_slider.setValue(40); qtbot.wait(20)
    win._refresh = lambda: None           # nothing re-derives it in between
    _press_apply(win); qtbot.wait(30)
    h.release(); _idle(qtbot, win)
    assert win._share_act.isEnabled() is False


# ---------------------------------------------------------------- A2: busy is a set
def test_one_jobs_end_never_releases_anothers_busy(qtbot, tmp_path, monkeypatch):
    win, h = _make(qtbot, tmp_path, monkeypatch)
    win._go_to_id("local_contrast", user_initiated=False); qtbot.wait(20)
    win._panel.lc_slider.setValue(40); qtbot.wait(20)
    _press_apply(win); qtbot.wait(30)
    job1 = win._active_token
    assert job1 is not None
    landed = []
    win._run_busy(lambda: 2, landed.append, "job 2", "Failed")   # forced past every gate
    qtbot.wait(mw.BUSY_DELAY_MS + 150)
    assert not win._cancel_btn.isHidden()

    h.release(1)
    qtbot.waitUntil(lambda: landed == [2], timeout=5000)
    qtbot.wait(30)
    assert win._busy is True, "job 2's end released job 1's busy"
    assert not win._cancel_btn.isHidden()
    assert win._active_token is job1
    assert getattr(win, "_running", None) == {job1}

    h.release(0); _idle(qtbot, win)
    assert win._running == set()
    assert win._active_token is None
    assert _names(win) == ["Local Contrast"]


def test_cancel_with_two_jobs_running_cancels_both(qtbot, tmp_path, monkeypatch):
    win, h = _make(qtbot, tmp_path, monkeypatch)
    win._run_busy(lambda: 1, lambda r: None, "job 1", "Failed")
    job1 = win._active_token
    win._run_busy(lambda: 2, lambda r: None, "job 2", "Failed")
    job2 = win._active_token
    assert job1 is not job2
    win._cancel_active()
    assert job1.cancelled and job2.cancelled
    h.release(); _idle(qtbot, win)


def test_the_wrong_picture_scenario_cannot_happen(qtbot, tmp_path, monkeypatch):
    """Audit R/S2: Apply Noise Reduction, click De-green in the stepper. The
    split it started landed first and released NR's busy; a De-green applied
    then was erased from the pixels when NR landed on the base it captured."""
    win, h = _make(qtbot, tmp_path, monkeypatch)
    win._go_to_id("noise_sharpen", user_initiated=False); qtbot.wait(20)
    orig = win.project.current().copy()
    _press_apply(win); qtbot.wait(30)
    assert win._busy and len(h.events) == 1

    win.stepper.stageSelected.emit(_index(win, "green_fringe"))
    qtbot.wait(30)
    assert win.current_stage_id() == "noise_sharpen"
    assert len(h.events) == 1

    h.release(); _idle(qtbot, win)
    assert _names(win) == ["Noise Reduction"]
    _, opt = win.project.entries()[-1]
    expect = win._step_for("noise_sharpen").apply(orig, opt).data
    assert np.allclose(win.project.current().data, expect)


# ---------------------------------------------------------------- A3: mid-Apply edits kept
def _held_apply_then(qtbot, win, h, setup, change):
    setup(); qtbot.wait(150)
    _press_apply(win); qtbot.wait(30)
    assert win._busy
    pressed = win.project.entries()
    change(); qtbot.wait(150)
    h.release(); _idle(qtbot, win)
    assert len(win.project.entries()) == len(pressed) + 1, "the Apply did not commit"


def test_local_contrast_moved_during_apply_stays_pending(qtbot, tmp_path, monkeypatch):
    win, h = _make(qtbot, tmp_path, monkeypatch)
    win._go_to_id("local_contrast", user_initiated=False); qtbot.wait(20)
    _held_apply_then(qtbot, win, h,
                     lambda: win._panel.lc_slider.setValue(40),
                     lambda: win._panel.lc_slider.setValue(90))
    name, opt = win.project.entries()[-1]
    assert name == "Local Contrast" and opt == pytest.approx(0.40)
    assert win._has_pending() is True
    assert win._panel.apply_btn.state() == "pending"


def test_levels_moved_during_apply_stays_pending(qtbot, tmp_path, monkeypatch):
    win, h = _make(qtbot, tmp_path, monkeypatch)
    win._go_to_id("levels", user_initiated=False); qtbot.wait(20)
    _held_apply_then(qtbot, win, h,
                     lambda: win._panel.white_slider.setValue(80),
                     lambda: win._panel.white_slider.setValue(60))
    name, opt = win.project.entries()[-1]
    assert name == "Levels"
    assert win._has_pending() is True
    assert win._panel.apply_btn.state() == "pending"


def test_curves_nudged_during_apply_stays_pending(qtbot, tmp_path, monkeypatch):
    win, h = _make(qtbot, tmp_path, monkeypatch)
    win._go_to_id("curves", user_initiated=False); qtbot.wait(20)
    ed = win._panel.curve_editor
    _held_apply_then(qtbot, win, h,
                     lambda: ed.set_points([(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)]),
                     lambda: ed.set_points([(0.0, 0.0), (0.5, 0.4), (1.0, 1.0)]))
    assert _names(win)[-1] == "Curves"
    assert win._has_pending() is True
    assert win._panel.apply_btn.state() == "pending"


def test_untouched_during_apply_is_not_pending(qtbot, tmp_path, monkeypatch):
    """The control case: A3 must not leave every async Apply reading pending."""
    win, h = _make(qtbot, tmp_path, monkeypatch)
    win._go_to_id("local_contrast", user_initiated=False); qtbot.wait(20)
    _held_apply_then(qtbot, win, h,
                     lambda: win._panel.lc_slider.setValue(40),
                     lambda: None)
    assert win._has_pending() is False
    assert win._lc_pending is None


# ---------------------------------------------------------------- A4: splits
def test_fringe_split_is_remembered_on_the_ui_thread(qtbot, tmp_path, monkeypatch):
    win, h = _make(qtbot, tmp_path, monkeypatch, hold=False)
    on_main = []
    real = mw.MainWindow._remember_split

    def spy(self, *a, **k):
        on_main.append(threading.current_thread() is threading.main_thread())
        return real(self, *a, **k)
    monkeypatch.setattr(mw.MainWindow, "_remember_split", spy)
    win._go_to_id("green_fringe", user_initiated=False)
    _idle(qtbot, win)
    assert on_main and all(on_main), on_main
    assert win._fringe_ready


@pytest.mark.parametrize("callback", ["_on_sr_split", "_on_sat_split"])
def test_a_split_landing_after_the_user_left_is_still_remembered(
        qtbot, tmp_path, monkeypatch, callback):
    win, _h = _make(qtbot, tmp_path, monkeypatch, hold=False)
    win._go_to_id("curves", user_initiated=False); qtbot.wait(20)
    base = win._sr_base()
    sig = win._sr_sig(base)
    assert sig not in win._splits
    layers = (AstroImage(base.data * 0.9, is_linear=False, metadata={}),
              AstroImage(base.data * 0.1, is_linear=False, metadata={}), "StarNet2")
    getattr(win, callback)(sig, layers)
    assert sig in win._splits
    starless, stars, tag = win._splits[sig]
    assert starless is layers[0] and stars is layers[1] and tag == "StarNet2"
