"""Async ordering for the step-commit model, driven by a REAL deferred
`_run_busy` rather than the synchronous stand-in the rest of the suite uses.

`_win` in test_step_commit_model.py builds windows through `_window`, which
sets `_async_enabled = False` so `apply_current` commits before it returns and
no test there ever sees a navigation land AFTER an Apply call returns. That
flag is documented in CLAUDE.md as making those tests "a different program"
from the shipped one — and this branch's entire defect class lives in exactly
the gap that difference hides: dispatch a truncation-confirmed apply, hold it
mid-flight, and check what a second navigation, a declined resume, or a source
that changes underneath the deferral leaves behind. Two of this branch's
Criticals (the async confirm racing dispatch, and a stale deferral landing on
the wrong target after a second nav) were invisible to the whole synchronous
suite for exactly that reason, and nothing else in `tests/ui/` exercises
`_run_busy`'s real call order — only this file's `Worker` does, by standing in
for the worker thread with the same order (`_set_busy(True)` at dispatch,
`on_result` then `_set_busy(False)` on landing) while letting the test choose
when landing happens.
"""
import numpy as np
import pytest

from nocturne.core.image import AstroImage


def _win(qtbot, tmp_path):
    from tests.ui.test_main_window import _window
    win = _window(qtbot, tmp_path)
    base = AstroImage(np.full((32, 32, 3), 0.25, np.float32),
                      is_linear=False, metadata={})
    win.open_image(base, "test")
    win.show()
    qtbot.waitExposed(win)
    return win


class Worker:
    """Stands in for `_run_busy`'s thread: same call ORDER as the real one —
    `_set_busy(True)` at dispatch, `on_result` then `_release`/`_set_busy(False)`
    when it lands — but the landing happens when the test says so."""

    def __init__(self, win, monkeypatch):
        from nocturne.ui import main_window as mw
        self.win = win
        self.queue = []

        def fake_run_busy(s, work, on_result, label, err_prefix):
            token = object()
            s._active_token = token
            s._busy_start = 0.0
            s._set_busy(True, label)
            self.queue.append((s, token, work, on_result, err_prefix))

        monkeypatch.setattr(mw.MainWindow, "_run_busy", fake_run_busy)

    def pending(self):
        return len(self.queue)

    def land(self, *, fail=False):
        s, token, work, on_result, err_prefix = self.queue.pop(0)
        try:
            if fail:
                s._show_warning(f"{err_prefix}: boom")
            else:
                on_result(work())
        finally:
            if s._active_token is token:
                s._active_token = None
                s._set_busy(False)


def _other_method(win):
    box = win._panel.method_box
    return next(box.itemText(i) for i in range(box.count())
                if box.itemText(i) != box.currentText())


def _answer(monkeypatch, which):
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_pending", lambda self, step: which)


def test_async_colour_sequence_commits_both_and_lands(qtbot, tmp_path, monkeypatch):
    """Method + tint pending, real deferral: one prompt, both commit, nav lands.
    No _ask_truncation stub -- the autouse fixture raises if one is opened."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    w = Worker(win, monkeypatch)
    win._panel.method_box.setCurrentText(_other_method(win))
    win._on_tint_change(0.2, 0.0)
    _answer(monkeypatch, "apply")
    stage = win.current_stage_id()
    seq_before = win._nav_seq

    win.go_next()

    # deferred, nothing committed yet, still on Colour
    assert win._busy is True
    assert w.pending() == 1
    assert [n for n, _ in win.project.entries()] == []
    assert win.current_stage_id() == stage
    assert win._deferred_nav is not None
    assert win._deferred_nav[0] == seq_before
    assert win._deferred_nav[2] == frozenset({"method", "tint"})

    w.land()

    assert [n for n, _ in win.project.entries()] == ["Color", "Colour Tint"]
    assert not win._has_pending()
    assert win.current_stage_id() != stage
    assert win._deferred_nav is None
    assert w.pending() == 0


def test_async_failed_apply_does_not_resume_or_navigate(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    w = Worker(win, monkeypatch)
    win._panel.method_box.setCurrentText(_other_method(win))
    win._on_tint_change(0.2, 0.0)
    _answer(monkeypatch, "apply")
    stage = win.current_stage_id()

    win.go_next()
    w.land(fail=True)

    assert [n for n, _ in win.project.entries()] == [], "committed on a failed apply"
    assert win.current_stage_id() == stage, "navigated past a failed apply"
    assert win._deferred_nav is None, "left a stale resume armed"
    assert w.pending() == 0, "resumed the sequence after a failure"
    assert win._tint_pending is not None, "lost the tint"


def test_async_declined_second_press_does_not_navigate(qtbot, tmp_path, monkeypatch):
    """The resumed press is declined at its truncation confirm."""
    from nocturne.ui import main_window as mw
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    w = Worker(win, monkeypatch)
    win._panel.method_box.setCurrentText(_other_method(win))
    win._on_tint_change(0.2, 0.0)
    _answer(monkeypatch, "apply")
    stage = win.current_stage_id()

    win.go_next()
    real = mw.MainWindow._truncate_for
    monkeypatch.setattr(mw.MainWindow, "_truncate_for",
                        lambda s, sid, verb: False if sid == "tint" else real(s, sid, verb))
    w.land()

    assert [n for n, _ in win.project.entries()] == ["Color"]
    assert win._tint_pending is not None
    assert win.current_stage_id() == stage, "navigated after a declined discard"
    assert win._deferred_nav is None


def test_async_second_navigation_drops_the_stale_resume(qtbot, tmp_path, monkeypatch):
    """User clicks a different stepper row while the apply is in flight."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    w = Worker(win, monkeypatch)
    win._panel.method_box.setCurrentText(_other_method(win))
    win._on_tint_change(0.2, 0.0)
    _answer(monkeypatch, "apply")
    target_was = win._deferred_nav
    win.go_next()
    assert win._deferred_nav is not None
    deferred_target = win._deferred_nav[1]

    # a second, completed navigation while still busy
    _answer(monkeypatch, "discard")
    win._go_to_id("curves")
    landed_on = win.current_stage_id()
    assert landed_on == "curves"

    w.land()

    assert win.current_stage_id() == landed_on, (
        "the stale deferral yanked the user to the first target")
    assert win._deferred_nav is None
    assert w.pending() == 0
    assert deferred_target is not None and target_was is None


def test_async_round_trip_back_to_colour_still_drops_the_deferral(
        qtbot, tmp_path, monkeypatch):
    """_nav_seq's job: two navigations that end back on Colour must NOT let the
    deferral land by index coincidence."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    w = Worker(win, monkeypatch)
    win._panel.method_box.setCurrentText(_other_method(win))
    win._on_tint_change(0.2, 0.0)
    _answer(monkeypatch, "apply")
    stage_index = win._stage

    win.go_next()
    _answer(monkeypatch, "discard")
    win._go_to_id("curves")
    win._go_to_id("color")
    assert win._stage == stage_index

    w.land()

    assert win.current_stage_id() == "color", "the stale deferral landed anyway"
    assert win._deferred_nav is None
    assert w.pending() == 0


def test_async_three_sources_all_commit_method_first(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    w = Worker(win, monkeypatch)
    win._panel.method_box.setCurrentText(_other_method(win))
    win._on_tint_change(0.2, 0.0)
    win._on_removegreen_change(0.4)
    _answer(monkeypatch, "apply")
    assert win._pending_sources() == frozenset({"method", "tint", "remove_green"})

    win.go_next()
    w.land()

    assert [n for n, _ in win.project.entries()] == [
        "Color", "Colour Tint", "Remove Green"]
    assert not win._has_pending()
    assert win.current_stage_id() != "color"


def test_async_apply_color_over_a_committed_tint_asks_before_the_worker_starts(
        qtbot, tmp_path, monkeypatch):
    """The Critical, on the async path: the confirm must precede _run_busy, so a
    decline never dispatches work at all."""
    from nocturne.ui import main_window as mw
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    w = Worker(win, monkeypatch)
    win._panel.apply_btn.click()
    w.land()
    win._apply_tint_step(0.2, 0.0)
    before = list(win.project.entries())
    assert [n for n, _ in before] == ["Color", "Colour Tint"]

    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda s, names, label, verb, **kw:
                        seen.append(list(names)) or False)
    win._panel.method_box.setCurrentText(_other_method(win))
    win._panel.apply_btn.click()

    assert seen == [["Colour Tint"]], seen
    assert w.pending() == 0, "dispatched work for an apply the user declined"
    assert list(win.project.entries()) == before


def test_async_a_new_pending_source_arriving_mid_flight_bails_safely(
        qtbot, tmp_path, monkeypatch):
    """The tint slider is NOT disabled during a busy op, so a source can appear
    between arming the deferral and landing it. `left < was` is then False and
    the nav is dropped — silent, but it must not press Apply again or lose the
    tint."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    w = Worker(win, monkeypatch)
    win._panel.method_box.setCurrentText(_other_method(win))
    _answer(monkeypatch, "apply")
    stage = win.current_stage_id()

    win.go_next()
    assert win._deferred_nav[2] == frozenset({"method"})
    win._on_tint_change(0.2, 0.0)          # user drags the tint while busy

    w.land()

    assert [n for n, _ in win.project.entries()] == ["Color"]
    assert win._tint_pending is not None, "lost the tint the user just set"
    assert win.current_stage_id() == stage
    assert win._deferred_nav is None
    assert w.pending() == 0
