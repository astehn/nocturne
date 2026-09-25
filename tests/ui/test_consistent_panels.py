"""Consistent panels, Task 5: the pinned action, Apply's state decided in ONE
place (MainWindow._step_state), Colour's single Apply, Next kept in place on
Export, and the temporary look switch."""
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


def test_the_look_switch_changes_every_apply_and_is_remembered(qtbot, tmp_path):
    win = _open(qtbot, tmp_path)
    win._set_apply_look("B")
    win._go_to_id("levels", user_initiated=False); qtbot.wait(20)
    assert win._panel.apply_btn.look() == "B"
    assert win.settings.apply_look == "B"


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
    assert btn.isEnabled(), "an applied step can still be re-applied"


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


# --- the look switch -------------------------------------------------------------

@pytest.mark.parametrize("look", ["A", "B"])
def test_the_action_row_is_one_height_per_look_on_every_step(qtbot, tmp_path, look):
    win = _open(qtbot, tmp_path)
    win._set_apply_look(look)
    heights, ys = set(), set()
    for i, st in enumerate(list(win._stages)):
        if not st.enabled:
            continue
        win._go_to(i, user_initiated=False); qtbot.wait(20)
        heights.add(win._side.action_slot.height())
        ys.add(win._side.action_slot.mapTo(win, QPoint(0, 0)).y())
        pa = win._panel.primary_action
        if hasattr(pa, "look"):
            assert pa.look() == look, st.id
            assert pa.height() <= win._side.action_slot.height(), st.id
    assert len(heights) == 1 and len(ys) == 1, (heights, ys)


def test_the_look_switch_relooks_the_current_apply_immediately(qtbot, tmp_path):
    win = _open(qtbot, tmp_path)
    win._go_to_id("stretch", user_initiated=False); qtbot.wait(20)
    win._set_apply_look("B")
    assert win._panel.apply_btn.look() == "B"
    win._set_apply_look("A")
    assert win._panel.apply_btn.look() == "A"


def test_the_look_menu_is_an_exclusive_checkable_pair(qtbot, tmp_path):
    win = _open(qtbot, tmp_path)
    acts = win._apply_look_acts
    assert set(acts) == {"A", "B"}
    assert acts["A"].isChecked() and not acts["B"].isChecked()
    acts["B"].trigger()
    assert acts["B"].isChecked() and not acts["A"].isChecked()
    assert win.settings.apply_look == "B"


def test_apply_look_persists_through_settings(tmp_path):
    from nocturne.settings import Settings, load_settings, save_settings
    assert Settings().apply_look == "A"
    s = Settings(); s.apply_look = "B"
    p = str(tmp_path / "s.json")
    save_settings(s, p)
    assert load_settings(p).apply_look == "B"


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
