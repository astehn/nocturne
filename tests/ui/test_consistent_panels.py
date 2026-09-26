"""Consistent panels, Task 5: the pinned action, Apply's state decided in ONE
place (MainWindow._step_state), Colour's single Apply, and Next kept in place
on Export."""
import numpy as np
import pytest
from PySide6.QtCore import QPoint

from tests.ui.test_main_window import _make_fits, _window


def _open(qtbot, tmp_path, size=(1400, 900)):
    win = _window(qtbot, tmp_path)
    win._ask_geometry = lambda *a: True
    win.open_fits(_make_fits(tmp_path))
    win.resize(*size); win.show(); qtbot.waitExposed(win)
    return win


def _stretched(qtbot, tmp_path):
    """Levels and everything after it need a stretched image."""
    win = _open(qtbot, tmp_path)
    win._go_to_id("stretch", user_initiated=False); qtbot.wait(20)
    win._panel.apply_btn.click(); qtbot.wait(50)
    assert not win.project.current().is_linear, "fixture: stretch did not commit"
    return win


def test_the_action_is_pinned_in_the_side_panel_on_every_step(qtbot, tmp_path):
    win = _open(qtbot, tmp_path)
    ys = set()
    for i, st in enumerate(list(win._stages)):
        if not st.enabled:
            continue
        win._go_to(i, user_initiated=False); qtbot.wait(20)
        ys.add(win._side.action_slot.mapTo(win, QPoint(0, 0)).y())
        pa = win._panel.primary_action
        if pa is not None:
            assert win._side.action_slot.isAncestorOf(pa), st.id
    assert len(ys) == 1


def test_moving_a_slider_makes_apply_pending_and_next_still_asks(qtbot, tmp_path):
    """Review Focus 2: the reason 'not applied' exists."""
    win = _open(qtbot, tmp_path)
    win._go_to_id("levels", user_initiated=False); qtbot.wait(20)
    s = win._panel.black_slider
    s.setValue(s.value() + 3); qtbot.wait(120)
    assert win._panel.apply_btn.state() == "pending"
    asked = []
    win._ask_pending = lambda label: asked.append(label) or "cancel"
    win.go_next()
    assert asked, "Next dropped an unapplied edit without asking"


def test_colour_single_apply_commits_method_and_tint_in_order(qtbot, tmp_path):
    win = _open(qtbot, tmp_path)
    win._go_to_id("color", user_initiated=False); qtbot.wait(20)
    p = win._panel
    p.tint_slider.setValue(20); qtbot.wait(120)
    # A DIFFERENT method, so the method is really pending and the order is
    # really exercised (index 0 is the default and changed nothing).
    p.method_box.setCurrentIndex(1)
    assert p.method_box.currentText() != p.method_baseline, "fixture: method not moved"
    before = [n for n, _ in win.project.entries()]
    p.apply_btn.click(); qtbot.wait(50)
    after = [n for n, _ in win.project.entries()][len(before):]
    # "Colour Tint" is the history name _apply_tint_step commits under
    # (_PrecomputedStep("Colour Tint", …); STEP_NAME["tint"]).
    assert "Colour Tint" in after, after
    assert after == ["Color", "Colour Tint"], after
    assert not win._has_pending()


def test_stretch_at_its_default_is_green(qtbot, tmp_path):
    """Pressing it would stretch the image — green by the one rule."""
    win = _open(qtbot, tmp_path)
    win._go_to_id("stretch", user_initiated=False); qtbot.wait(20)
    assert win._panel.apply_btn.state() in ("not_run", "pending")


def test_next_stays_in_place_disabled_on_export(qtbot, tmp_path):
    win = _open(qtbot, tmp_path)
    win._go_to_id("stretch", user_initiated=False); qtbot.wait(20)
    back, nxt = win._back_btn.geometry(), win._next_btn.geometry()
    win._go_to_id("export", user_initiated=False); qtbot.wait(20)
    assert win._next_btn.isVisible() and not win._next_btn.isEnabled()
    assert win._back_btn.geometry() == back and win._next_btn.geometry() == nxt


@pytest.mark.parametrize("sid", sorted(__import__("nocturne.ui.main_window", fromlist=["x"]).NOOP_AT_DEFAULT))
def test_no_change_really_is_a_no_op(qtbot, tmp_path, sid):
    """Review Focus 3: a disabled Apply must never block a real edit. Commit
    the untouched panel through the real path and measure the change."""
    win = _open(qtbot, tmp_path)
    # Star Reduction's split may launch StarXTerminator. At 0 it must never be
    # asked for one: once armed, any separator call fails the test loudly.
    armed, calls = [False], []
    real_split = win._split_tagged

    def guarded_split(img):
        calls.append(armed[0])
        if armed[0]:
            raise AssertionError(f"{sid}: a star separator ran for a no-op Apply")
        return real_split(img)

    win._split_tagged = guarded_split
    win._go_to_id("stretch", user_initiated=False); win._panel.apply_btn.click(); qtbot.wait(50)
    win._go_to_id(sid, user_initiated=False); qtbot.wait(20)
    assert win._panel.apply_btn.state() == "no_change"
    base = win.project.current().data.copy()
    n = len(win.project.entries())
    armed[0] = True
    win._panel.apply_btn.setEnabled(True); win._panel.apply_btn.click(); qtbot.wait(50)
    assert True not in calls, f"{sid}: a star separator ran for a no-op Apply"
    # The click must really have committed, or the comparison below is vacuous.
    assert len(win.project.entries()) == n + 1, f"{sid}: the Apply did not commit"
    import numpy as np
    assert np.array_equal(win.project.current().data, base), f"{sid}: its default is NOT a no-op"


# --- the state decision, spec §4 -------------------------------------------

def test_recover_core_untouched_and_never_applied_is_no_change(qtbot, tmp_path):
    win = _stretched(qtbot, tmp_path)
    win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
    btn = win._panel.apply_btn
    assert btn.state() == "no_change"
    assert not btn.isEnabled(), "no_change must be disabled: no Δ0.0% step recorded"


def test_a_slider_move_is_pending_and_apply_makes_it_applied(qtbot, tmp_path):
    win = _stretched(qtbot, tmp_path)
    win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
    win._panel.recover_slider.setValue(30); qtbot.wait(20)
    btn = win._panel.apply_btn
    assert btn.state() == "pending" and btn.isEnabled()
    n = len(win.project.entries())
    btn.click(); qtbot.wait(20)
    assert len(win.project.entries()) == n + 1, "fixture: Apply did not commit"
    assert btn.state() == "applied"
    # Off since 2026-09-25 (Andreas): pressing it again only re-ran the tool
    # on the same image. Change a control, or Reset step.
    assert not btn.isEnabled(), "an applied, unchanged step must not re-run"


def test_applied_then_dragged_back_to_the_no_op_value_is_pending(qtbot, tmp_path):
    """Spec §4: pressing Apply now would UNDO the earlier edit, so the button
    must be green (pending) and enabled, and Next must ask — not no_change,
    and not 'applied' because the slider happens to sit at its default."""
    win = _stretched(qtbot, tmp_path)
    win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
    s = win._panel.recover_slider
    s.setValue(30); qtbot.wait(20)
    win._panel.apply_btn.click(); qtbot.wait(20)
    assert win._panel.apply_btn.state() == "applied", "precondition"
    s.setValue(0); qtbot.wait(20)
    btn = win._panel.apply_btn
    assert btn.state() == "pending"
    assert btn.isEnabled()
    assert win._has_pending(), "the button and Next's prompt must agree"


def test_a_never_applied_step_that_would_change_the_image_is_not_run(qtbot, tmp_path):
    win = _stretched(qtbot, tmp_path)
    win._go_to_id("green_fringe", user_initiated=False); qtbot.wait(20)
    assert win._panel.apply_btn.state() == "not_run"


def test_state_does_not_override_tool_availability(qtbot, tmp_path):
    """Background with GraXpert unconfigured is disabled for a reason of its
    own. 'not_run' says pressing would change the image — it must not switch
    the button on and hand the user a press that does nothing."""
    win = _open(qtbot, tmp_path)
    win._go_to_id("background", user_initiated=False); qtbot.wait(20)
    btn = win._panel.apply_btn
    assert btn.state() == "not_run"
    assert not btn.isEnabled()
    win._sync_step_controls()
    assert not btn.isEnabled()


# --- busy vs state ------------------------------------------------------------

def test_busy_end_leaves_a_no_change_apply_disabled(qtbot, tmp_path):
    win = _stretched(qtbot, tmp_path)
    win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
    btn = win._panel.apply_btn
    assert btn.state() == "no_change" and not btn.isEnabled(), "precondition"
    win._set_busy(True, "probe")
    assert not btn.isEnabled()
    win._set_busy(False)
    assert btn.state() == "no_change"
    assert not btn.isEnabled(), "the busy restore re-enabled a no_change Apply"


def test_busy_end_brings_a_pending_apply_back_enabled(qtbot, tmp_path):
    win = _stretched(qtbot, tmp_path)
    win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
    win._panel.recover_slider.setValue(30); qtbot.wait(20)
    btn = win._panel.apply_btn
    assert btn.state() == "pending" and btn.isEnabled(), "precondition"
    win._set_busy(True, "probe")
    assert not btn.isEnabled()
    win._set_busy(False)
    assert btn.state() == "pending"
    assert btn.isEnabled(), "a pending Apply stayed disabled after busy"


def test_state_changes_during_busy_land_correctly_when_busy_ends(qtbot, tmp_path):
    """No_change at the start of the busy op, pending by its end: the sweep never
    saw it enabled, so only the state decision can switch it back on."""
    win = _stretched(qtbot, tmp_path)
    win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
    btn = win._panel.apply_btn
    win._set_busy(True, "probe")
    win._panel.recover_slider.setValue(30); qtbot.wait(20)
    assert btn.state() == "busy" and not btn.isEnabled()
    win._set_busy(False)
    assert btn.state() == "pending" and btn.isEnabled()


def test_a_pending_apply_that_becomes_no_change_during_busy_ends_disabled(
        qtbot, tmp_path):
    """The sweep saw it ENABLED (pending) and restores it on; by then the
    slider is back at the no-op on a never-applied step. The restore must not
    have the last word."""
    win = _stretched(qtbot, tmp_path)
    win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
    s = win._panel.recover_slider
    s.setValue(30); qtbot.wait(20)
    btn = win._panel.apply_btn
    assert btn.state() == "pending" and btn.isEnabled(), "precondition"
    win._set_busy(True, "probe")
    s.setValue(0); qtbot.wait(20)
    win._set_busy(False)
    assert btn.state() == "no_change"
    assert not btn.isEnabled(), "the busy restore re-enabled a no_change Apply"


# --- Colour's single Apply -----------------------------------------------------

def test_colour_shows_one_apply(qtbot, tmp_path):
    win = _open(qtbot, tmp_path)
    win._go_to_id("color", user_initiated=False); qtbot.wait(20)
    from nocturne.ui.apply_button import ApplyButton
    visible = [b for b in win.findChildren(ApplyButton) if b.isVisible()]
    assert visible == [win._panel.apply_btn]
    assert not win._panel.apply_tint_btn.isVisible()


def test_colour_untouched_apply_commits_the_method(qtbot, tmp_path):
    """Never applied, nothing moved: the step is not_run (green), so pressing
    it must do something — commit the calibration method."""
    win = _open(qtbot, tmp_path)
    win._go_to_id("color", user_initiated=False); qtbot.wait(20)
    btn = win._panel.apply_btn
    assert btn.state() == "not_run"
    n = len(win.project.entries())
    btn.click(); qtbot.wait(50)
    assert [e for e, _ in win.project.entries()][n:] == ["Color"]
    assert btn.state() == "applied"


def test_colour_tint_pending_marks_the_one_apply(qtbot, tmp_path):
    win = _open(qtbot, tmp_path)
    win._go_to_id("color", user_initiated=False); qtbot.wait(20)
    win._panel.tint_slider.setValue(20); qtbot.wait(20)
    assert win._panel.apply_btn.state() == "pending"


def test_colour_method_and_tint_both_pending_commit_method_first(qtbot, tmp_path):
    """_apply_sequence's order: method ("Color") first, then the tint — the
    reverse would commit the tint and then ask to discard it."""
    win = _open(qtbot, tmp_path)
    win._go_to_id("color", user_initiated=False); qtbot.wait(20)
    p = win._panel
    p.method_box.setCurrentIndex(1)
    p.tint_slider.setValue(20); qtbot.wait(20)
    n = len(win.project.entries())
    p.apply_btn.click(); qtbot.wait(50)
    assert [e for e, _ in win.project.entries()][n:] == ["Color", "Colour Tint"]
    assert not win._has_pending()


# --- the action row -------------------------------------------------------------

def test_the_action_row_is_one_height_on_every_step(qtbot, tmp_path):
    win = _open(qtbot, tmp_path)
    heights, ys = set(), set()
    for i, st in enumerate(list(win._stages)):
        if not st.enabled:
            continue
        win._go_to(i, user_initiated=False); qtbot.wait(20)
        heights.add(win._side.action_slot.height())
        ys.add(win._side.action_slot.mapTo(win, QPoint(0, 0)).y())
        pa = win._panel.primary_action
        if pa is not None:
            assert pa.height() <= win._side.action_slot.height(), st.id
    assert len(heights) == 1 and len(ys) == 1, (heights, ys)


# --- fix round 1 ----------------------------------------------------------------

def test_revisited_applied_step_nudged_and_back_is_applied_not_pending(qtbot, tmp_path):
    """R10 (b), Andreas's 2026-09-13 rule: put a slider back where you found it
    and there is nothing to apply. A revisited step is rebuilt at its defaults,
    so "where you found it" is 0 even though 0.30 is committed."""
    win = _stretched(qtbot, tmp_path)
    win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
    win._panel.recover_slider.setValue(30); qtbot.wait(20)
    win._panel.apply_btn.click(); qtbot.wait(20)
    win._go_to_id("levels", user_initiated=False); qtbot.wait(20)
    win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
    s = win._panel.recover_slider
    assert s.value() == 0, "precondition: a revisited panel shows its defaults"
    s.setValue(10); qtbot.wait(20)
    assert win._panel.apply_btn.state() == "pending"
    s.setValue(0); qtbot.wait(20)
    assert not win._has_pending()
    assert win._panel.apply_btn.state() == "applied"
    asked = []
    win._ask_pending = lambda label: asked.append(label) or "cancel"
    win.go_next()
    assert not asked, "Next asked about a slider put back where it was found"


def test_applied_then_dragged_back_makes_next_ask(qtbot, tmp_path):
    """R10 (a): in the same visit, "where you found it" is the value just
    applied — so dragging from 0.30 to 0 is an edit, and Next must ask."""
    win = _stretched(qtbot, tmp_path)
    win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
    s = win._panel.recover_slider
    s.setValue(30); qtbot.wait(20)
    win._panel.apply_btn.click(); qtbot.wait(20)
    s.setValue(0); qtbot.wait(20)
    assert win._panel.apply_btn.state() == "pending"
    asked = []
    win._ask_pending = lambda label: asked.append(label) or "cancel"
    win.go_next()
    assert asked, "Next dropped the undo of an applied edit without asking"


def test_never_applied_nudged_and_back_is_no_change(qtbot, tmp_path):
    """R10 (c)."""
    win = _stretched(qtbot, tmp_path)
    win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
    s = win._panel.recover_slider
    s.setValue(10); qtbot.wait(20)
    assert win._panel.apply_btn.state() == "pending"
    s.setValue(0); qtbot.wait(20)
    assert win._panel.apply_btn.state() == "no_change"
    assert not win._panel.apply_btn.isEnabled()


def test_fresh_colour_tint_only_apply_runs_the_calibration_first(qtbot, tmp_path):
    """R11: a calibration that has never run is a real change, and the one
    Apply commits everything on the step — calibration, then tint."""
    win = _open(qtbot, tmp_path)
    win._go_to_id("color", user_initiated=False); qtbot.wait(20)
    p = win._panel
    assert p.method_box.currentText() == p.method_baseline, "fixture: method untouched"
    p.tint_slider.setValue(20); qtbot.wait(20)
    n = len(win.project.entries())
    p.apply_btn.click(); qtbot.wait(50)
    assert [e for e, _ in win.project.entries()][n:] == ["Color", "Colour Tint"]
    assert not win._has_pending()


def test_fresh_colour_next_apply_and_continue_runs_the_calibration_too(
        qtbot, tmp_path):
    """R11: Next's "Apply and continue" takes the same path as the Apply."""
    win = _open(qtbot, tmp_path)
    win._go_to_id("color", user_initiated=False); qtbot.wait(20)
    win._panel.tint_slider.setValue(20); qtbot.wait(20)
    n = len(win.project.entries())
    win._ask_pending = lambda label: "apply"
    win.go_next()
    qtbot.wait(50)
    assert [e for e, _ in win.project.entries()][n:] == ["Color", "Colour Tint"]


def test_a_tint_only_colour_does_not_re_run_the_calibration(qtbot, tmp_path):
    """The other side of R11: once the step holds its own tint commit it has
    run, and re-committing the method under it would truncate that tint."""
    win = _open(qtbot, tmp_path)
    win._go_to_id("color", user_initiated=False); qtbot.wait(20)
    win._apply_tint_step(0.1, 0.0)
    win._panel.tint_slider.setValue(20); qtbot.wait(20)
    before = [e for e, _ in win.project.entries()]
    assert before[-1] == "Colour Tint" and "Color" not in before, "precondition"
    win._panel.apply_btn.click(); qtbot.wait(50)
    # The tint REPLACES its own commit; no calibration is slipped in under it.
    assert [e for e, _ in win.project.entries()] == before
    assert win.project.entries()[-1][1] == (pytest.approx(0.2), pytest.approx(0.0))


def test_next_stays_disabled_on_export_after_a_busy_cycle(qtbot, tmp_path):
    """Export itself runs busy; ending it must not switch Next on."""
    win = _open(qtbot, tmp_path)
    win._go_to_id("export", user_initiated=False); qtbot.wait(20)
    assert not win._next_btn.isEnabled(), "precondition"
    win._set_busy(True, "Exporting…")
    win._set_busy(False)
    assert win._next_btn.isVisible() and not win._next_btn.isEnabled()


def test_next_comes_back_after_a_busy_cycle_elsewhere(qtbot, tmp_path):
    win = _open(qtbot, tmp_path)
    win._go_to_id("stretch", user_initiated=False); qtbot.wait(20)
    win._set_busy(True, "probe")
    assert not win._next_btn.isEnabled()
    win._set_busy(False)
    assert win._next_btn.isEnabled()


def _reveal_crop_box(win):
    """What the first click on the image does: show the box (cropBoxShown)."""
    win.image_view.show_crop_box()


def test_a_full_frame_crop_box_is_no_change(qtbot, tmp_path):
    """An untouched box covering the whole frame: Apply Crop commits nothing."""
    win = _open(qtbot, tmp_path)
    win._go_to_id("crop", user_initiated=False); qtbot.wait(20)
    h, w = win.project.current().data.shape[:2]
    win.image_view.set_crop_overlay(True, content_bounds=(0, h, 0, w), aspect_ratio=None)
    _reveal_crop_box(win)
    assert win.image_view.crop_bounds() == (0, h, 0, w), "precondition: full frame"
    assert win._panel.apply_btn.state() == "no_change"
    assert not win._panel.apply_btn.isEnabled()


def test_an_inset_crop_box_is_not_run(qtbot, tmp_path):
    win = _open(qtbot, tmp_path)
    win._go_to_id("crop", user_initiated=False); qtbot.wait(20)
    h, w = win.project.current().data.shape[:2]
    win.image_view.set_crop_overlay(True, content_bounds=(2, h - 2, 2, w - 2), aspect_ratio=None)
    _reveal_crop_box(win)
    assert win._panel.apply_btn.state() == "not_run"
    assert win._panel.apply_btn.isEnabled()


def test_after_a_crop_apply_reads_applied_not_pending(qtbot, tmp_path):
    win = _open(qtbot, tmp_path)
    win._go_to_id("crop", user_initiated=False); qtbot.wait(20)
    h, w = win.project.current().data.shape[:2]
    win.image_view.set_crop_overlay(True, content_bounds=(0, h, 0, w), aspect_ratio=None)
    _reveal_crop_box(win)
    win.image_view._set_bounds((2, h - 2, 2, w - 2))
    win.image_view._geometry_changed()
    assert win._panel.apply_btn.state() == "pending", "precondition"
    n = len(win.project.entries())
    win._panel.apply_btn.click(); qtbot.wait(20)
    assert [e for e, _ in win.project.entries()][n:] == ["Crop"], "fixture: crop did not commit"
    assert win._panel.apply_btn.state() == "applied"


def test_nested_busy_restores_the_first_sweeps_buttons(qtbot, tmp_path):
    """A run started while one is in flight: the second sweep must not throw
    away the first one's record, or its buttons stay off for good."""
    win = _stretched(qtbot, tmp_path)
    win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
    win._panel.recover_slider.setValue(30); qtbot.wait(20)
    btn, reset = win._panel.apply_btn, win._panel.reset_step_btn
    assert btn.isEnabled() and reset.isEnabled(), "precondition"
    win._set_busy(True, "first")
    win._set_busy(True, "second")
    win._set_busy(False)
    assert btn.isEnabled() and btn.state() == "pending"
    assert reset.isEnabled()


# --- Task 7: one activity line per applied step ------------------------------
# "Color · Δ0.0%" and "Noise Reduction (strong (NoiseX)) · Δ5.7%" each appeared
# twice in his 16:24 screenshot. `_log_step` has one caller, apply_current's
# on_result, straight after project.run_step — so a line is a commit. These pin
# that for every route to a commit, in BOTH threading modes: the fixture's
# `_async_enabled = False` is a different program, and a double that needs a
# worker's landing AND the synchronous path would not show up without the pool.

def _no_external_tool(*a, **k):
    raise AssertionError("a real external tool was reached from a UI test")


def _stub_denoise():
    from dataclasses import replace
    from nocturne.steps.noise_sharpen import NoiseSharpenStep

    class _StubNR(NoiseSharpenStep):
        """Reports NoiseX like the real RC-Astro path, never runs it."""
        def __init__(self):
            super().__init__(None, None)
            self._runner = _no_external_tool

        def apply(self, img, option):
            self.last_engine = "NoiseX"
            return replace(img, data=(img.data * 0.95).astype(img.data.dtype))
    return _StubNR()


def _commit_counting(win):
    commits = []
    real = win.project.run_step

    def run_step(step, option):
        commits.append(step.name)
        return real(step, option)
    win.project.run_step = run_step
    return commits


def _land(qtbot, win):
    qtbot.waitUntil(lambda: not win._busy, timeout=10000)
    qtbot.wait(30)                       # a deferred "Apply and continue" lands after busy
    qtbot.waitUntil(lambda: not win._busy, timeout=10000)


@pytest.mark.parametrize("async_", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("route", ["apply", "apply_then_next", "next_answers_apply"])
@pytest.mark.parametrize("sid", ["color", "noise_sharpen"])
def test_each_commit_writes_exactly_one_activity_step_line(
        qtbot, tmp_path, monkeypatch, sid, route, async_):
    import nocturne.steps.noise_sharpen as ns
    win = _open(qtbot, tmp_path)
    monkeypatch.setattr(ns, "run_cli", _no_external_tool)
    win._rc_runner = win._bg_runner = _no_external_tool
    real_step_for = win._step_for
    monkeypatch.setattr(win, "_step_for", lambda s: _stub_denoise()
                        if s == "noise_sharpen" else real_step_for(s))
    win._async_enabled = async_
    win._go_to_id(sid, user_initiated=False); qtbot.wait(20)
    p = win._panel
    if sid == "color":
        p.tint_slider.setValue(20); qtbot.wait(120)
        expected = ["Color", "Colour Tint"]     # R11: a fresh Colour calibrates too
    else:
        p.option_box.setCurrentIndex((p.option_box.currentIndex() + 1) % p.option_box.count())
        expected = ["Noise Reduction"]
    assert win._has_pending(), "fixture: nothing pending"
    commits = _commit_counting(win)
    lines_before = win.activity.entries("step")
    win._ask_pending = lambda label: "apply"
    if route in ("apply", "apply_then_next"):
        p.primary_action.click(); _land(qtbot, win)
    if route in ("apply_then_next", "next_answers_apply"):
        win.go_next(); _land(qtbot, win)
    assert commits == expected, commits
    new = win.activity.entries("step")[len(lines_before):]
    assert win.activity.entries("step")[:len(lines_before)] == lines_before
    # One line per commit, in commit order, and nothing else.
    assert len(new) == len(commits), new
    for line, name in zip(new, commits):
        assert line.split(" ", 1)[1].startswith(name + " "), (line, name)


# --- fix round 3: applied = disabled (Andreas, 2026-09-25 23:27) -------------
# Pressing an applied, unchanged Apply re-ran the tool on the same image and
# logged an identical line (Task 7) — minutes of RC-Astro for Noise Reduction.

def _with_stub_nr(win, monkeypatch):
    import nocturne.steps.noise_sharpen as ns
    monkeypatch.setattr(ns, "run_cli", _no_external_tool)
    win._rc_runner = win._bg_runner = _no_external_tool
    real_step_for = win._step_for
    monkeypatch.setattr(win, "_step_for", lambda s: _stub_denoise()
                        if s == "noise_sharpen" else real_step_for(s))


def _apply_and_land(qtbot, win):
    win._panel.apply_btn.click()
    _land(qtbot, win)


def _applied_recover_core(qtbot, tmp_path):
    win = _stretched(qtbot, tmp_path)
    win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
    win._panel.recover_slider.setValue(30); qtbot.wait(20)
    win._panel.apply_btn.click(); qtbot.wait(20)
    assert win._panel.apply_btn.state() == "applied", "fixture"
    return win


def test_an_applied_unchanged_step_is_disabled(qtbot, tmp_path):
    win = _applied_recover_core(qtbot, tmp_path)
    btn = win._panel.apply_btn
    assert not btn.isEnabled()
    assert "applied" in btn.status_text()        # same words, only dimmed
    assert btn.property("pending") == "false"


def test_an_applied_apply_stays_disabled_after_a_busy_cycle(qtbot, tmp_path):
    win = _applied_recover_core(qtbot, tmp_path)
    win._set_busy(True, "probe")
    win._set_busy(False)
    assert win._panel.apply_btn.state() == "applied"
    assert not win._panel.apply_btn.isEnabled()


def test_an_applied_unchanged_step_never_prompts_on_next(qtbot, tmp_path):
    win = _applied_recover_core(qtbot, tmp_path)
    asked = []
    win._ask_pending = lambda label: asked.append(label) or "cancel"
    win.go_next()
    assert not asked
    assert win.current_stage_id() != "recover_core"


def _move_slider(win, qtbot):
    win._panel.recover_slider.setValue(50); qtbot.wait(20)


@pytest.mark.parametrize("control", ["slider", "levels_auto", "combo", "colour_tint",
                                     "colour_method", "crop_box", "curves"])
def test_any_control_change_on_an_applied_step_re_enables_apply(
        qtbot, tmp_path, monkeypatch, control):
    if control == "slider":
        win = _applied_recover_core(qtbot, tmp_path)
        _move_slider(win, qtbot)
    elif control == "levels_auto":
        win = _stretched(qtbot, tmp_path)
        win._go_to_id("levels", user_initiated=False); qtbot.wait(20)
        win._panel.black_slider.setValue(3); qtbot.wait(20)
        win._panel.apply_btn.click(); qtbot.wait(20)
        assert win._panel.apply_btn.state() == "applied", "fixture"
        win._panel.auto_btn.click(); qtbot.wait(20)      # the checkable Auto
    elif control == "combo":
        win = _open(qtbot, tmp_path)
        _with_stub_nr(win, monkeypatch)
        win._go_to_id("noise_sharpen", user_initiated=False); qtbot.wait(20)
        win._panel.apply_btn.click(); qtbot.wait(20)
        assert win._panel.apply_btn.state() == "applied", "fixture"
        box = win._panel.option_box
        box.setCurrentIndex((box.currentIndex() + 1) % box.count()); qtbot.wait(20)
    elif control in ("colour_tint", "colour_method"):
        win = _open(qtbot, tmp_path)
        win._go_to_id("color", user_initiated=False); qtbot.wait(20)
        win._panel.apply_btn.click(); qtbot.wait(20)
        assert win._panel.apply_btn.state() == "applied", "fixture"
        assert not win._panel.apply_btn.isEnabled(), "applied + untouched Colour is off"
        if control == "colour_tint":
            win._panel.tint_slider.setValue(20); qtbot.wait(20)
        else:
            win._panel.method_box.setCurrentIndex(1); qtbot.wait(20)
    elif control == "curves":
        win = _open(qtbot, tmp_path)
        win._go_to_id("curves", user_initiated=False); qtbot.wait(20)
        editor = win._panel.curve_editor
        editor.set_points([(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)]); qtbot.wait(20)
        assert win._panel.apply_btn.state() == "pending", "fixture: curve edit not pending"
        win._panel.apply_btn.click(); qtbot.wait(20)
        assert win._panel.apply_btn.state() == "applied", "fixture"
        assert not win._panel.apply_btn.isEnabled(), "applied curve edit is off"
        editor.set_points([(0.0, 0.0), (0.3, 0.5), (1.0, 1.0)]); qtbot.wait(20)
    else:
        win = _open(qtbot, tmp_path)
        win._go_to_id("crop", user_initiated=False); qtbot.wait(20)
        h, w = win.project.current().data.shape[:2]
        win.image_view.set_crop_overlay(True, content_bounds=(0, h, 0, w), aspect_ratio=None)
        _reveal_crop_box(win)
        win.image_view._set_bounds((2, h - 2, 2, w - 2)); win.image_view._geometry_changed()
        win._panel.apply_btn.click(); qtbot.wait(20)
        assert win._panel.apply_btn.state() == "applied", "fixture"
        assert not win._panel.apply_btn.isEnabled(), "applied crop, box gone: off"
        h2, w2 = win.project.current().data.shape[:2]
        win.image_view.set_crop_overlay(True, content_bounds=(0, h2, 0, w2), aspect_ratio=None)
        _reveal_crop_box(win)
        # A full-frame box over an already-cropped image: pressing does nothing.
        # The step HAS a commit, so it reads "✓ applied" (the decision checks the
        # commit before the full-frame no-op) — off either way.
        assert win._panel.apply_btn.state() == "applied", "full-frame box after a crop"
        assert not win._panel.apply_btn.isEnabled()
        win.image_view._set_bounds((1, h2 - 1, 1, w2 - 1)); win.image_view._geometry_changed()
    btn = win._panel.apply_btn
    assert btn.state() == "pending", control
    assert btn.isEnabled(), control


def test_reset_step_still_works_on_an_applied_step(qtbot, tmp_path, monkeypatch):
    from nocturne.ui import main_window as mw
    win = _applied_recover_core(qtbot, tmp_path)
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: True)
    reset = win._panel.reset_step_btn
    assert reset.isEnabled()
    reset.click(); qtbot.wait(20)
    assert "Recover Core" not in [n for n, _ in win.project.entries()]
    assert win._panel.apply_btn.state() == "no_change"


def test_revisited_recover_core_at_its_default_over_a_commit_is_live_and_applies_it(
        qtbot, tmp_path):
    """Ruling R13, replacing the 23:27 reading of R10 (b). Applied at 0.30, the
    step is revisited and rebuilt at 0: that is NOT the commit, so Apply is
    live (plain — nothing is pending, and Next must not nag), and pressing it
    commits 0. Only a verified match switches Apply off."""
    win = _applied_recover_core(qtbot, tmp_path)
    win._go_to_id("levels", user_initiated=False); qtbot.wait(20)
    win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
    s = win._panel.recover_slider
    assert s.value() == 0, "precondition: a revisited panel shows its defaults"
    s.setValue(10); qtbot.wait(20)
    s.setValue(0); qtbot.wait(20)
    btn = win._panel.apply_btn
    assert btn.state() == "applied" and btn.property("pending") == "false"
    assert btn.isEnabled(), "0 over a 0.30 commit is a real edit; Apply was off"
    asked = []
    win._ask_pending = lambda label: asked.append(label) or "cancel"
    win.go_next()
    assert not asked, "R10: Next asked about a slider put back where it was found"
    assert win.current_stage_id() != "recover_core"
    win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
    win._panel.apply_btn.click(); qtbot.wait(20)
    assert win.project.entries()[-1] == ("Recover Core", pytest.approx(0.0))
    assert win._panel.apply_btn.state() == "applied"
    assert not win._panel.apply_btn.isEnabled(), "now verified: 0 is the commit"


def test_enhancements_and_export_have_no_state_driven_apply(qtbot, tmp_path):
    from nocturne.ui.apply_button import ApplyButton
    win = _open(qtbot, tmp_path)
    win._go_to_id("enhancements", user_initiated=False); qtbot.wait(20)
    assert win._panel.primary_action is None
    win._go_to_id("export", user_initiated=False); qtbot.wait(20)
    pa = win._panel.primary_action
    assert pa is not None and not isinstance(pa, ApplyButton)
    was = pa.isEnabled()
    win._sync_step_controls()
    assert pa.isEnabled() == was


@pytest.mark.parametrize("async_", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("sid", ["color", "noise_sharpen"])
def test_a_second_press_on_an_applied_step_commits_nothing(
        qtbot, tmp_path, monkeypatch, sid, async_):
    """The Task 7 reviewer's ask: apply once, the button is off, a second
    click() does nothing — exactly one commit and one activity step line."""
    win = _open(qtbot, tmp_path)
    _with_stub_nr(win, monkeypatch)
    win._async_enabled = async_
    win._go_to_id(sid, user_initiated=False); qtbot.wait(20)
    commits = _commit_counting(win)
    lines_before = win.activity.entries("step")
    _apply_and_land(qtbot, win)
    assert win._panel.apply_btn.state() == "applied"
    assert not win._panel.apply_btn.isEnabled()
    _apply_and_land(qtbot, win)
    assert commits == (["Color"] if sid == "color" else ["Noise Reduction"]), commits
    assert len(win.activity.entries("step")) == len(lines_before) + 1


# --- final review C1/I1/I2, ruling R13 --------------------------------------
# Apply is off in "applied" ONLY when the step's whole current option verifiably
# equals the committed one (`_controls_match_commit`). The pending check behind
# the colour never saw the engine box, a fresh crop box or the stretch linkage,
# and using it to disable Apply blocked those edits outright.

_PROCESS = ("background", "deconvolution", "noise_sharpen", "ai_denoise")
_MODELS = [("v6", "/nonexistent/v6.onnx"), ("v7", "/nonexistent/v7.onnx")]


def _no_tools(win, monkeypatch, *, engines=False, models=False):
    """Every external tool fails loudly if reached; the process steps compute
    a stub instead. `engines` configures GraXpert AND RC-Astro (the engine box
    exists); `models` installs two Nocturne NR models (Linear Denoise exists)."""
    from dataclasses import replace
    import nocturne.steps.noise_sharpen as ns
    import nocturne.ui.main_window as mw
    monkeypatch.setattr(ns, "run_cli", _no_external_tool)
    win._rc_runner = win._bg_runner = _no_external_tool
    if engines:
        monkeypatch.setattr(mw, "graxpert_valid", lambda s: True)
        monkeypatch.setattr(mw, "rcastro_valid", lambda s: True)
    if models:
        import nocturne.core.denoise_model as dm
        monkeypatch.setattr(dm, "usable_external_models", lambda: list(_MODELS))
        win._rebuild_stages()
    real_step_for = win._step_for

    def step_for(sid):
        step = real_step_for(sid)
        if sid in _PROCESS:
            def apply(img, option, _step=step):
                _step.last_engine = "stub"
                return replace(img, data=(img.data * 0.97).astype(img.data.dtype))
            step.apply = apply
            step._runner = _no_external_tool
        return step
    monkeypatch.setattr(win, "_step_for", step_for)


def _other_engine(win):
    """An engine entry that really runs something else. Not simply the next
    entry: "Default" and "RC-Astro" are the same engine under the default
    setting, and the button is right to stay off between them."""
    box = win._panel.engine_box
    items = [box.itemText(i) for i in range(box.count())]
    box.setCurrentText("GraXpert" if "GraXpert" in items else items[1])


def _off(btn):
    return btn.state() == "applied" and not btn.isEnabled()


@pytest.mark.parametrize("async_", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("sid", ["noise_sharpen", "ai_denoise"])
def test_switching_the_engine_after_an_apply_leaves_apply_live(
        qtbot, tmp_path, monkeypatch, sid, async_):
    """C1.1: apply, choose the other engine — Apply read "✓ applied" and was
    off, and nothing even re-read it. Pressing must commit the new engine."""
    win = _open(qtbot, tmp_path)
    _no_tools(win, monkeypatch, engines=True, models=True)
    win._async_enabled = async_
    win._go_to_id(sid, user_initiated=False); qtbot.wait(20)
    p = win._panel
    assert getattr(p, "engine_box", None) is not None and p.engine_box.count() >= 2, \
        "fixture: no engine box"
    commits = _commit_counting(win)
    _apply_and_land(qtbot, win)
    first = win.project.entries()[-1][1]
    assert _off(p.apply_btn), "fixture: an unchanged applied step must be off"
    _other_engine(win); qtbot.wait(20)
    assert p.apply_btn.isEnabled(), "a different engine is a real edit; Apply was off"
    assert p.apply_btn.state() == "applied"         # colour: nothing pending
    _apply_and_land(qtbot, win)
    name = "Noise Reduction" if sid == "noise_sharpen" else "Linear Denoise"
    assert commits == [name, name], commits
    second = win.project.entries()[-1][1]
    assert second["level"] == first["level"] and second["engine"] != first["engine"]
    assert _off(win._panel.apply_btn), "the new engine is now the commit"


def _crop_box(win, inset):
    h, w = win.project.current().data.shape[:2]
    win.image_view.set_crop_overlay(
        True, content_bounds=(inset, h - inset, inset, w - inset), aspect_ratio=None)
    _reveal_crop_box(win)


@pytest.mark.parametrize("first", ["Rotate", "Flip H", "Crop"])
def test_a_fresh_crop_box_after_a_crop_stage_commit_is_live_and_pending(
        qtbot, tmp_path, first):
    """C1.2: after Rotate, Flip or a first crop, the fresh (detected) box read
    "applied" and was off — the auto-detected crop could not be applied."""
    win = _open(qtbot, tmp_path)
    win._go_to_id("crop", user_initiated=False); qtbot.wait(20)
    if first == "Rotate":
        win._rotate()
    elif first == "Flip H":
        win._flip_h()
    else:
        _crop_box(win, 1)
        win._panel.apply_btn.click(); qtbot.wait(20)
    assert [n for n, _ in win.project.entries()] == [first], "fixture"
    _crop_box(win, 2)
    assert not win.image_view.crop_box_modified(), "fixture: an untouched fresh box"
    btn = win._panel.apply_btn
    assert btn.isEnabled(), f"a fresh inset box after {first} is a real crop; Apply was off"
    assert btn.state() == "pending"
    asked = []
    win._ask_pending = lambda label: asked.append(label) or "cancel"
    win.go_next()
    assert not asked, "an untouched fresh box still has no work to lose"
    win._go_to_id("crop", user_initiated=False); qtbot.wait(20)
    _crop_box(win, 2)
    h, w = win.project.current().data.shape[:2]
    win._panel.apply_btn.click(); qtbot.wait(20)
    assert [n for n, _ in win.project.entries()] == [first, "Crop"]
    assert win.project.current().data.shape[:2] == (h - 4, w - 4)


def test_a_full_frame_box_after_a_crop_is_off(qtbot, tmp_path):
    """The verified side for Crop: a whole-frame box over the committed image
    makes `_apply_crop` return, so there is nothing to press."""
    win = _open(qtbot, tmp_path)
    win._go_to_id("crop", user_initiated=False); qtbot.wait(20)
    win._rotate()
    _crop_box(win, 0)
    assert _off(win._panel.apply_btn)


@pytest.mark.parametrize("engines", [False, True], ids=["one_engine", "both_engines"])
def test_a_revisited_noise_reduction_shows_its_committed_level_and_engine(
        qtbot, tmp_path, monkeypatch, engines):
    """I1: the committed option is a dict, so the box fell back to the default
    ("medium") over an image holding "strong", under a disabled "✓ applied"."""
    win = _open(qtbot, tmp_path)
    _no_tools(win, monkeypatch, engines=engines)
    win._go_to_id("noise_sharpen", user_initiated=False); qtbot.wait(20)
    p = win._panel
    default = p.option_box.currentText()
    other = next(t for t in (p.option_box.itemText(i) for i in range(p.option_box.count()))
                 if t != default)
    p.option_box.setCurrentText(other)
    if engines:
        p.engine_box.setCurrentText("GraXpert")
    _apply_and_land(qtbot, win)
    win._go_to_id("stretch", user_initiated=False); qtbot.wait(20)
    win._go_to_id("noise_sharpen", user_initiated=False); qtbot.wait(20)
    p = win._panel
    assert p.option_box.currentText() == other, "the box misreports the committed level"
    if engines:
        assert p.engine_box.currentText() == "GraXpert"
    assert _off(p.apply_btn), "the controls ARE the commit"
    assert not win._has_pending()
    p.option_box.setCurrentText(default); qtbot.wait(20)
    assert p.apply_btn.isEnabled() and p.apply_btn.state() == "pending"


def test_stretch_linked_then_unlinked_leaves_apply_live(qtbot, tmp_path):
    """I2: the committed stretch carries `linked`; choosing Unlinked at Import
    and coming back read "applied" and off."""
    win = _open(qtbot, tmp_path)
    win._go_to_id("stretch", user_initiated=False); qtbot.wait(20)
    win._panel.apply_btn.click(); qtbot.wait(50)
    assert win.project.entries()[-1][1]["linked"] is True, "fixture"
    assert _off(win._panel.apply_btn)
    win._go_to_id("load", user_initiated=False); qtbot.wait(20)
    win._set_view_linked(False)
    win._go_to_id("stretch", user_initiated=False); qtbot.wait(20)
    btn = win._panel.apply_btn
    assert btn.isEnabled(), "an unlinked stretch over a linked commit is a real edit"
    btn.click(); qtbot.wait(50)
    assert win.project.entries()[-1][0] == "Stretch"
    assert win.project.entries()[-1][1]["linked"] is False
    assert _off(win._panel.apply_btn)


# The audit: every step, every control that feeds its commit. After an apply the
# controls ARE the commit (off); moving any one of them must leave Apply live.

def _stretch_first(win, qtbot):
    win._go_to_id("stretch", user_initiated=False); qtbot.wait(20)
    win._panel.apply_btn.click(); qtbot.wait(50)


def _pick(box):
    box.setCurrentIndex((box.currentIndex() + 1) % box.count())


def _curve_matrix_change(win):
    from nocturne.core.curves import curve_key
    pts = win._panel.curve_editor.points()
    win._on_curves_dialog_apply({curve_key("rgb", "all"): list(pts),
                                 curve_key("r", "all"): [(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)]})


# sid -> (needs a stretch first, set a committed value, {control: change it})
_AUDIT = {
    "crop": (False, lambda w: (_crop_box(w, 1),
                               w.image_view._geometry_changed()),
             {"box": lambda w: _crop_box(w, 2)}),
    "background": (False, lambda w: None,
                   {"strength": lambda w: _pick(w._panel.option_box)}),
    "deconvolution": (False, lambda w: None,
                      {"strength": lambda w: _pick(w._panel.option_box)}),
    "noise_sharpen": (False, lambda w: None,
                      {"strength": lambda w: _pick(w._panel.option_box),
                       "engine": _other_engine}),
    "ai_denoise": (False, lambda w: None,
                   {"strength": lambda w: _pick(w._panel.option_box),
                    "engine": _other_engine}),
    "color": (False, lambda w: None,
              {"method": lambda w: _pick(w._panel.method_box),
               "tint": lambda w: w._panel.tint_slider.setValue(20),
               "temperature": lambda w: w._panel.temp_slider.setValue(20)}),
    "stretch": (False, lambda w: None,
                {"amount": lambda w: w._panel.stretch_slider.setValue(
                    w._panel.stretch_slider.value() + 5),
                 "linked": lambda w: w._apply_picked_stretch(
                     {"amount": w._panel.stretch_slider.value() / 100.0,
                      "linked": False})}),
    "remove_green": (True, lambda w: w._panel.rg_slider.setValue(40),
                     {"strength": lambda w: w._panel.rg_slider.setValue(60)}),
    "recover_core": (True, lambda w: w._panel.recover_slider.setValue(30),
                     {"strength": lambda w: w._panel.recover_slider.setValue(50)}),
    "levels": (True, lambda w: w._panel.black_slider.setValue(3),
               {"black": lambda w: w._panel.black_slider.setValue(6),
                "midtones": lambda w: w._panel.gamma_slider.setValue(120),
                "white": lambda w: w._panel.white_slider.setValue(90),
                "auto": lambda w: w._panel.auto_btn.click()}),
    "curves": (True, lambda w: w._panel.curve_editor.set_points(
                   [(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)]),
               {"rgb_curve": lambda w: w._panel.curve_editor.set_points(
                    [(0.0, 0.0), (0.3, 0.5), (1.0, 1.0)]),
                "channel_curves": _curve_matrix_change}),
    "saturation": (True, lambda w: w._panel.sat_slider.setValue(70),
                   {"saturation": lambda w: w._panel.sat_slider.setValue(80),
                    "nebula": lambda w: w._panel.neb_slider.setValue(30)}),
    "green_fringe": (True, lambda w: w._panel.fringe_slider.setValue(60),
                     {"amount": lambda w: w._panel.fringe_slider.setValue(80)}),
    "local_contrast": (True, lambda w: w._panel.lc_slider.setValue(30),
                       {"strength": lambda w: w._panel.lc_slider.setValue(50)}),
    "star_reduction": (True, lambda w: w._panel.sr_slider.setValue(30),
                       {"amount": lambda w: w._panel.sr_slider.setValue(50)}),
}


def test_the_audit_covers_every_stage_with_an_apply():
    from nocturne.ui.pipeline import path_stages
    import nocturne.ui.pipeline as pl
    ids = {s.id for s in path_stages(include=frozenset(pl._OPTIONAL))}
    assert ids - {"load", "enhancements", "export"} == set(_AUDIT)


@pytest.mark.parametrize("sid,control", [(sid, c) for sid, (_, _, cs) in _AUDIT.items()
                                         for c in cs])
def test_every_control_that_feeds_a_commit_leaves_an_applied_apply_live(
        qtbot, tmp_path, monkeypatch, sid, control):
    needs_stretch, set_value, controls = _AUDIT[sid]
    win = _open(qtbot, tmp_path)
    _no_tools(win, monkeypatch, engines=sid in _PROCESS, models=sid == "ai_denoise")
    if needs_stretch:
        _stretch_first(win, qtbot)
    win._go_to_id(sid, user_initiated=False); qtbot.wait(20)
    set_value(win); qtbot.wait(20)
    n = len(win.project.entries())
    win._panel.apply_btn.click(); qtbot.wait(50)
    assert len(win.project.entries()) == n + 1, f"fixture: {sid} did not commit"
    assert _off(win._panel.apply_btn), f"{sid}: the controls ARE the commit, Apply must be off"
    controls[control](win); qtbot.wait(30)
    btn = win._panel.apply_btn
    assert btn.isEnabled(), f"{sid}/{control}: a changed control left Apply off"
