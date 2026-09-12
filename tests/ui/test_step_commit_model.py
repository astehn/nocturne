"""Whether a step's settings have been committed, and whether the app says so.

The confusion this answers was reported by a user with his own observatory: the
preview is pixel-identical to the commit (see _preview_base — that is
deliberate), so nothing on screen distinguishes "previewed" from "applied".
"""
import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.ui.pipeline import STEP_NAME


def _win(qtbot, tmp_path):
    """`_window` sets `_async_enabled = False`, so apply_current commits before
    it returns and no waiting is needed. That flag also makes this a different
    program from the shipped one — anything here that depends on threading is
    not being tested. See CLAUDE.md."""
    from tests.ui.test_main_window import _window
    win = _window(qtbot, tmp_path)
    base = AstroImage(np.full((32, 32, 3), 0.25, np.float32),
                      is_linear=False, metadata={})
    win.open_image(base, "test")
    # Visibility checks (test_the_pending_label_tracks_the_state) are hollow
    # unless the window is actually shown: Qt's isVisible() is false for every
    # child of an unshown top-level regardless of its own setVisible() call.
    win.show()
    qtbot.waitExposed(win)
    return win


def test_a_freshly_opened_step_is_not_pending(qtbot, tmp_path):
    """Arriving somewhere is 'not started', not 'pending'. Marking it pending
    would nag on every step the user merely walks past."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    assert win._has_pending() is False


def test_moving_a_slider_makes_the_step_pending(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)
    assert win._has_pending() is True


def test_applying_clears_pending(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)
    win.apply_current((0.1, 1.0, 0.9))
    qtbot.waitUntil(lambda: win._has_pending() is False, timeout=5000)


def test_the_pending_label_tracks_the_state(qtbot, tmp_path):
    """Read the widget, not the flag: the flag being right while the label is
    never shown is exactly the bug this whole task exists to fix."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    # A freshly built panel needs one event-loop tick before Qt's isVisible()
    # reflects its parent's already-shown state (it lags a beat right after
    # replaceWidget, confirmed by probing the widget tree directly).
    qtbot.wait(1)
    assert not win._panel.pending_label.isVisible()
    win._on_levels_change(0.1, 1.0, 0.9)
    win._sync_step_controls()
    assert win._panel.pending_label.isVisible()
    assert "not applied" in win._panel.pending_label.text().lower()
    # Third leg, and the one with teeth: the two above are both satisfied by a
    # show-only _sync_step_controls, because the label is CONSTRUCTED hidden.
    # Saturation is deliberate — it commits through its own handler rather than
    # apply_current, which is where the clear was missing entirely.
    # user_initiated=False: this jump is test plumbing to reach Saturation, not
    # a simulated user abandoning the pending Levels change (Task 2 covers that
    # guard on its own) — without it this hangs on an unstubbed _ask_pending.
    win._go_to_id("saturation", user_initiated=False)
    qtbot.wait(1)                     # same rebuild lag as above
    win._on_sat_change(0.5, 0.0)      # nebula 0: no star split, so this is instant
    assert win._panel.pending_label.isVisible()
    win._apply_saturation(0.5, 0.0)
    qtbot.wait(1)
    assert not win._panel.pending_label.isVisible()


def test_a_compute_step_is_pending_once_its_option_differs(qtbot, tmp_path):
    """No preview exists on a compute step, so nothing is at risk — but an
    intent has been expressed that the committed image does not reflect, and
    Next would drop it."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("deconvolution")
    assert win._has_pending() is False
    win._panel.option_box.setCurrentText("strong")
    assert win._has_pending() is True


def test_committed_option_reads_the_last_commit_for_that_stage(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    assert win._committed_option("levels") is None
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)
    win.apply_current((0.1, 1.0, 0.9))
    # Without this the test is passed by a _committed_option that always
    # returns None — which is what the "never applied" leg above asserts.
    qtbot.waitUntil(
        lambda: win._committed_option("levels") == (0.1, 1.0, 0.9), timeout=5000)


def test_a_process_step_is_not_pending_right_after_its_own_apply(qtbot, tmp_path):
    """Noise Reduction commits a dict ({"engine": ..., "level": ...}); the
    dropdown holds a bare string. Compared against the history it could never
    agree, so the step read pending from its own Apply onwards."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("noise_sharpen")
    win._panel.option_box.setCurrentText("strong")
    assert win._has_pending() is True
    win.apply_current({"engine": None, "level": "strong"})
    qtbot.waitUntil(lambda: win._has_pending() is False, timeout=10000)


def test_returning_to_an_applied_process_step_is_not_pending(qtbot, tmp_path):
    """The rebuilt panel starts at the step's default, not at the committed
    value — a string-vs-string mismatch that no type guard could have caught."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("deconvolution")
    win._panel.option_box.setCurrentText("strong")
    win.apply_current("strong")
    qtbot.waitUntil(lambda: win._has_pending() is False, timeout=10000)
    win._go_to_id("levels")
    win._go_to_id("deconvolution")
    assert win._has_pending() is False


def test_background_off_is_a_decision_not_a_pending_change(qtbot, tmp_path):
    """Choosing "off" records nothing at all (apply_current early-returns), so
    there is no commit for the history to report — but the user chose it."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("background")
    win._panel.option_box.setCurrentText("off")
    assert win._has_pending() is True
    win.apply_current("off")
    assert win._has_pending() is False


def test_the_color_stage_covers_both_of_its_previews(qtbot, tmp_path):
    """Color carries two live previews and had no coverage at all: its slots
    were keyed by step name ("tint", "remove_green"), which current_stage_id
    never returns."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    assert win._has_pending() is False
    win._on_tint_change(0.2, 0.0)
    assert win._has_pending() is True
    win._apply_tint_step(0.2, 0.0)
    assert win._has_pending() is False
    win._on_removegreen_change(0.4)
    assert win._has_pending() is True


def test_the_label_appears_as_soon_as_a_compute_dropdown_moves(qtbot, tmp_path):
    """The label reads the dropdown, so it must hear the dropdown.

    `_has_pending()` was already right here; only the label lagged, catching up
    on the next `_refresh` — i.e. when the user did something else entirely. A
    signal that is correct but displayed late is still a step that looks applied
    when it is not.
    """
    win = _win(qtbot, tmp_path)
    win._go_to_id("deconvolution")
    win.show()
    qtbot.waitExposed(win)
    assert not win._panel.pending_label.isVisible()

    win._panel.option_box.setCurrentText("strong")
    qtbot.wait(1)

    assert win._panel.pending_label.isVisible(), (
        "the dropdown moved and the label did not notice until the next refresh")


def _answer(monkeypatch, which):
    """Stub the pending prompt. `which` is 'apply', 'discard' or 'cancel'."""
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_pending", lambda self, step: which)


def test_continue_without_applying_leaves_history_untouched(
        qtbot, tmp_path, monkeypatch):
    """The 'must not' case: capture entries and assert UNCHANGED. Asserting the
    count merely differs from the applied count would pass against a version
    that committed something else."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)
    before = list(win.project.entries())
    _answer(monkeypatch, "discard")

    win.go_next()

    assert list(win.project.entries()) == before
    assert win.current_stage_id() != "levels"


def test_apply_and_continue_commits_exactly_one_step(
        qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)
    before = list(win.project.entries())
    _answer(monkeypatch, "apply")

    win.go_next()

    qtbot.waitUntil(lambda: len(win.project.entries()) == len(before) + 1,
                    timeout=5000)
    assert win.project.entries()[-1][0] == STEP_NAME["levels"]


def test_cancel_stays_on_the_step_and_keeps_the_preview(
        qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)
    _answer(monkeypatch, "cancel")

    win.go_next()

    assert win.current_stage_id() == "levels"
    assert win._has_pending() is True


def test_an_untouched_step_is_never_prompted(qtbot, tmp_path, monkeypatch):
    """A prompt on every Next would be worse than the bug it fixes."""
    asked = []
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_pending",
                        lambda self, step: asked.append(step) or "cancel")
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")

    win.go_next()

    assert asked == [], "prompted with nothing pending"
    assert win.current_stage_id() != "levels"


def test_programmatic_navigation_never_prompts(qtbot, tmp_path, monkeypatch):
    """Opening an image and undoing both move the stepper. Neither is a moment
    to ask the user about work they did not just abandon."""
    asked = []
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_pending",
                        lambda self, step: asked.append(step) or "cancel")
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)

    win.open_image(AstroImage(np.full((32, 32, 3), 0.25, np.float32),
                              is_linear=False, metadata={}), "again")

    assert asked == []


def test_open_image_passes_user_initiated_false_through_to_the_guard(
        qtbot, tmp_path, monkeypatch):
    """The teeth the test above is missing.

    open_image calls `_show_chrome(True)` -> `_rebuild_panel()` BEFORE its own
    `_go_to_id("load", ...)` runs, and that rebuild clears whichever pending
    slot belongs to the CURRENT stage (`_levels_pending` for Levels) as a side
    effect — independent of `user_initiated`. So a Levels-pending fixture
    reaches the guard already clean and can't tell a correct
    `user_initiated=False` from a broken `user_initiated=True`: flipping the
    default in open_image left the test above green (verified by hand).
    `_tint_pending` (Color) is the one slot `_rebuild_panel` does not clear on
    its own stage, so it is still there when the guard actually checks."""
    asked = []
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_pending",
                        lambda self, step: asked.append(step) or "cancel")
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._on_tint_change(0.2, 0.0)

    win.open_image(AstroImage(np.full((32, 32, 3), 0.25, np.float32),
                              is_linear=False, metadata={}), "again")

    assert asked == []


def test_the_guard_is_wired_into_the_real_next_button(qtbot, tmp_path, monkeypatch):
    """Through the button, not through _go_to.

    A test that calls the guarded function with its own argument passes while
    the line that arms it is deleted — that exact gap reopened a race on the
    background-stacking branch with 1505 tests green.
    """
    from PySide6.QtCore import Qt
    asked = []
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_pending",
                        lambda self, step: asked.append(step) or "cancel")
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)

    qtbot.mouseClick(win._next_btn, Qt.MouseButton.LeftButton)

    assert asked, "the Next button reached _go_to without the pending guard"


def test_color_apply_and_continue_commits_the_tint_not_apply_color(
        qtbot, tmp_path, monkeypatch):
    """Color's own `apply_btn` ("Apply Color") commits the calibration method,
    not what's pending. 'Apply and continue' must press apply_tint_btn — the
    button that actually commits what the user changed — or it would commit a
    method nobody asked for and still drop the tint, which is worse than the
    silent discard this task exists to fix.

    Moves the actual slider, not just `_on_tint_change`: `apply_tint_btn`
    reads `tint_slider.value()` at click time (step_panels.py), not the
    pending slot. Calling `_on_tint_change` alone left the slider at 0, so the
    app committed `(0.0, 0.0)` while this test — asserting only the step
    NAME — passed regardless.
    """
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._panel.tint_slider.setValue(20)     # -> 0.20; fires _on_tint_change
    before = list(win.project.entries())
    _answer(monkeypatch, "apply")

    win.go_next()

    qtbot.waitUntil(lambda: len(win.project.entries()) == len(before) + 1,
                    timeout=5000)
    name, option = win.project.entries()[-1]
    assert name == "Colour Tint"
    assert option == (pytest.approx(0.2), pytest.approx(0.0)), (
        f"committed {option!r}, not the slider's value")
    assert win._tint_pending is None


def test_color_apply_and_continue_commits_remove_green_too(
        qtbot, tmp_path, monkeypatch):
    """The remove-green branch of `_pending_apply_targets` had no coverage:
    deleting it left the whole file green. Untested, that is precisely the
    bug this task exists to fix, just for Color's other slider — 'Apply and
    continue' on a pending Remove Green silently discarding it."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._panel.rg_slider.setValue(40)   # -> 0.40; fires _on_removegreen_change
    before = list(win.project.entries())
    _answer(monkeypatch, "apply")

    win.go_next()

    qtbot.waitUntil(lambda: len(win.project.entries()) == len(before) + 1,
                    timeout=5000)
    name, option = win.project.entries()[-1]
    assert name == "Remove Green"
    assert option == pytest.approx(0.4), f"committed {option!r}, not 0.40"
    assert win._rg_pending is None


def test_returning_to_an_untouched_color_after_a_discarded_tint_does_not_prompt(
        qtbot, tmp_path, monkeypatch):
    """CRITICAL 1. `_rebuild_panel` cleared `_rg_pending` on Color but not
    `_tint_pending`, so a discarded tint stayed in the slot forever — the next
    visit to Color, untouched, slider at 0, read as pending. Worse than a
    false prompt: the dialog's default button is "Apply and continue", so
    Return alone committed a no-op (0.0, 0.0) tint, and `_apply_tint_step`'s
    jump_back deleted every step applied since.

    Reproduces exactly that: nudge the tint, discard, apply Stretch and
    Levels, come back to Color untouched.
    """
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._panel.tint_slider.setValue(20)
    _answer(monkeypatch, "discard")
    win.go_next()                                       # off Color, tint discarded

    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("levels")
    win.apply_current((0.1, 1.0, 0.9))
    committed = list(win.project.entries())

    asked = []
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_pending",
                        lambda self, step: asked.append(step) or "apply")
    win._go_to_id("color")                               # untouched: slider reads 0
    assert win._has_pending() is False, (
        "a stale _tint_pending survived the discard and the two applies")

    win.go_next()

    assert asked == [], "an untouched Color step prompted"
    assert win.project.entries() == committed, (
        "Stretch/Levels were deleted by a no-op tint commit")


def _linear_win(qtbot, tmp_path):
    """A pre-stretch window — real FITS data loads linear — so a
    POST_STRETCH_IDS target (Levels) actually exercises _ensure_stretched."""
    from tests.ui.test_main_window import _window, _make_fits
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.show()
    qtbot.waitExposed(win)
    return win


def _deferred_run_busy(monkeypatch, win):
    """Replace _run_busy with one that sets busy=True immediately (matching
    the real async path: _set_busy(True) runs synchronously before the
    worker is dispatched) but STORES work/on_result instead of running them,
    so the test controls exactly when the apply "lands" relative to
    navigation. `_async_enabled=False` (what `_win`/`_window` set for every
    other test here) makes `_run_busy` run everything synchronously and hides
    this entire class of ordering bug — see CLAUDE.md 'measuring the GUI'."""
    from nocturne.ui import main_window as mw
    captured = {}

    def fake(self, work, on_result, label, err_prefix):
        self._set_busy(True, label)
        captured["work"] = work
        captured["on_result"] = on_result

    monkeypatch.setattr(mw.MainWindow, "_run_busy", fake)
    return captured


def _land(win, captured):
    """Simulate the worker completing: run the captured work, feed it to
    on_result, then clear busy — the same sequence _run_busy's real async
    path runs on a background thread before calling back onto the UI one."""
    result = captured["work"]()
    captured["on_result"](result)
    win._set_busy(False)


def test_apply_and_continue_defers_navigation_until_the_worker_lands(
        qtbot, tmp_path, monkeypatch):
    """CRITICAL 2. apply_current is asynchronous in the shipped app —
    _run_busy dispatches off the UI thread and returns immediately, so firing
    the navigation right after pressing Apply ran _ensure_stretched and
    _rebuild_panel against a project the worker had not finished mutating.

    Reproduced on a linear image: move Deconvolution to "strong", answer
    "apply" navigating to Levels (a POST_STRETCH_ID). Before the fix,
    _ensure_stretched fired immediately against the still-linear,
    pre-Deconvolution project — a phantom Stretch landed BEFORE Deconvolution
    committed, and Deconvolution's result (computed from the true pre-stretch
    base) then landed on top of it, silently resetting is_linear back to True
    even though the entries list claimed Stretch was done.
    """
    win = _linear_win(qtbot, tmp_path)
    win._go_to_id("deconvolution")
    win._panel.option_box.setCurrentText("strong")
    assert win._has_pending() is True
    captured = _deferred_run_busy(monkeypatch, win)
    _answer(monkeypatch, "apply")

    win._go_to_id("levels")

    assert win.project.entries() == [], (
        "navigation committed something before the async apply landed")
    assert win.current_stage_id() == "deconvolution", (
        "the stage moved before the apply that was supposed to precede it "
        "actually committed")

    _land(win, captured)

    assert [n for n, _ in win.project.entries()] == ["Deconvolution", "Stretch"], (
        "Deconvolution must land, in order, before the auto-stretch Levels needs")
    assert win.current_stage_id() == "levels"
    assert win.project.current().is_linear is False, (
        "Deconvolution landed on top of the auto-stretch and undid it")


def test_apply_and_continue_is_not_offered_when_apply_is_disabled(
        qtbot, tmp_path, monkeypatch):
    """IMPORTANT 3. Background's apply_btn is disabled from the moment the
    dropdown reads anything but "off" (GraXpert unconfigured in test
    settings — apply_enabled is False). Before the fix, `_apply_current_step`
    silently skipped the disabled button and `_go_to` navigated anyway:
    "Apply and continue" committed nothing and nobody was told — the original
    bug wearing a reassuring button. The prompt must not offer an action that
    cannot happen.
    """
    from PySide6.QtWidgets import QMessageBox
    win = _win(qtbot, tmp_path)
    win._go_to_id("background")
    win._panel.option_box.setCurrentText("light")   # baseline is "strong" (default)
    assert win._has_pending() is True
    assert win._panel.apply_btn.isEnabled() is False, (
        "fixture assumption: GraXpert must be unconfigured in test settings")
    assert win._pending_apply_targets() == []

    # Restore the real _ask_pending (stashed by the autouse fixture as
    # _real_ask_pending) rather than monkeypatch.undo(): this test and
    # _no_real_file_dialogs share one function-scoped monkeypatch, and a
    # blanket undo() would also lift THAT guard for the rest of the test.
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_pending", mw.MainWindow._real_ask_pending)
    seen = []

    def fake_exec(self):
        seen.extend(b.text() for b in self.buttons())
        for b in self.buttons():
            if b.text() == "Continue without applying":
                b.click()
                return 0
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    answer = win._ask_pending("Background")

    assert "Apply and continue" not in seen, (
        "the prompt offered an apply that could not actually happen")
    assert answer == "discard"


def test_async_apply_writes_the_baseline_on_the_panel_it_was_pressed_from(
        qtbot, tmp_path, monkeypatch):
    """IMPORTANT 4. on_result wrote `self._panel.option_baseline` — whichever
    panel is CURRENT when the worker returns, not the one Apply was pressed
    on. The stepper isn't busy-gated the way Next is, so navigating away and
    back while an apply is in flight is reachable in the real app.

    Reproduced: apply Noise Reduction "strong" (deferred), navigate away and
    back to a FRESH Noise Reduction panel before the worker lands, then land
    it — the fresh, untouched panel must not inherit "strong" as its
    baseline against its own "medium" default.
    """
    win = _win(qtbot, tmp_path)
    win._go_to_id("noise_sharpen")
    win._panel.option_box.setCurrentText("strong")
    captured = _deferred_run_busy(monkeypatch, win)
    win.apply_current({"engine": None, "level": "strong"})
    assert win._busy is True

    win._go_to_id("levels", user_initiated=False)
    win._go_to_id("noise_sharpen", user_initiated=False)
    fresh_panel = win._panel
    fresh_baseline = fresh_panel.option_baseline

    _land(win, captured)

    assert win._panel is fresh_panel
    assert win._panel.option_baseline == fresh_baseline, (
        "the async apply overwrote the panel current when it returned, not "
        "the panel it was pressed from")
    assert win._has_pending() is False, (
        "an untouched Noise Reduction panel now reads pending because its "
        "baseline was clobbered by an unrelated apply landing late")


def test_deferred_nav_does_not_fire_after_the_user_moved_on(
        qtbot, tmp_path, monkeypatch):
    """IMPORTANT 1. The stepper isn't busy-gated the way Next/Back are, so
    the user can click a different row while a deferred "Apply and
    continue" is still in flight. Reproduced: on Noise Reduction with a
    pending dropdown, Next -> apply (deferred, target Local Contrast);
    while the worker is still running, click Curves -> a second prompt
    (Cancel default, IMPORTANT 2 keeps Apply off it since noise_sharpen's
    own apply_btn is busy-disabled) -> discard -> lands on Curves. When the
    worker completes, the FIRST deferral must not yank the user back to
    Local Contrast — they deliberately moved to Curves since.
    """
    from nocturne.ui import main_window as mw
    win = _win(qtbot, tmp_path)
    win._go_to_id("noise_sharpen")
    win._panel.option_box.setCurrentText("strong")
    assert win._has_pending() is True
    captured = _deferred_run_busy(monkeypatch, win)
    answers = iter(["apply", "discard"])
    monkeypatch.setattr(mw.MainWindow, "_ask_pending", lambda self, step: next(answers))

    win.go_next()                               # -> deferred, target local_contrast
    assert win._deferred_nav is not None
    assert win.current_stage_id() == "noise_sharpen"

    win._go_to_id("curves")                      # second prompt: discard -> real nav
    assert win.current_stage_id() == "curves"

    _land(win, captured)

    assert win.current_stage_id() == "curves", (
        "a stale deferred nav yanked the user off a step they moved to")


def test_deferred_nav_does_not_fire_after_a_round_trip_back_to_the_origin(
        qtbot, tmp_path, monkeypatch):
    """The origin-stage bail (test above) is defeated by a round trip: leave
    the origin stage and come back to it while the apply is still in
    flight, and a bare stage-index comparison matches again by coincidence
    even though real navigation happened in between. GraXpert applies are
    documented elsewhere in this file as taking minutes — ample time to
    check another step and come back. `_nav_seq` (a monotonic counter,
    bumped on every completed navigation) catches this where the index
    couldn't: it cannot recur the way an index can.

    Reproduced: Noise Reduction pending -> apply (deferred, target Local
    Contrast) -> Curves -> discard -> back to Noise Reduction (no prompt:
    the rebuilt panel isn't pending) -> worker lands -> must stay on Noise
    Reduction, not get yanked to Local Contrast.
    """
    from nocturne.ui import main_window as mw
    win = _win(qtbot, tmp_path)
    win._go_to_id("noise_sharpen")
    win._panel.option_box.setCurrentText("strong")
    assert win._has_pending() is True
    captured = _deferred_run_busy(monkeypatch, win)
    answers = iter(["apply", "discard"])
    monkeypatch.setattr(mw.MainWindow, "_ask_pending", lambda self, step: next(answers))

    win.go_next()                                 # -> deferred, target local_contrast
    assert win._deferred_nav is not None

    win._go_to_id("curves")                       # second prompt: discard -> real nav
    assert win.current_stage_id() == "curves"

    win._go_to_id("noise_sharpen")                # round trip: fresh panel, not pending
    assert win._has_pending() is False
    assert win.current_stage_id() == "noise_sharpen"

    _land(win, captured)

    assert win.current_stage_id() == "noise_sharpen", (
        "a stale deferred nav landed after a round trip back to its own origin")


def test_color_apply_and_continue_is_not_offered_during_an_unrelated_busy_op(
        qtbot, tmp_path, monkeypatch):
    """IMPORTANT 2. _set_busy disables only self._panel.apply_btn, not
    Color's apply_tint_btn / remove_green_btn, so those stayed clickable
    during ANY unrelated busy op (a plate solve, Auto Enhance, Save Project
    — all _run_busy). Reproduced: tint nudged, an unrelated op running,
    _ask_pending's real body still offered "Apply and continue" as its
    DEFAULT button. Pressing it would click apply_tint_btn, whose own
    handler (_apply_tint_step) early-returns on self._busy — nothing
    commits, no navigation happens, no warning is shown: the default button
    does nothing at all, the same class of bug as IMPORTANT 3 reached
    through a different door.
    """
    from PySide6.QtWidgets import QMessageBox
    from nocturne.ui import main_window as mw
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._panel.tint_slider.setValue(20)
    win._set_busy(True, "Solving…")                 # an UNRELATED busy op
    try:
        monkeypatch.setattr(mw.MainWindow, "_ask_pending", mw.MainWindow._real_ask_pending)
        seen = []

        def fake_exec(self):
            seen.extend(b.text() for b in self.buttons())
            for b in self.buttons():
                if b.text() == "Continue without applying":
                    b.click()
                    return 0
            return 0

        monkeypatch.setattr(QMessageBox, "exec", fake_exec)

        answer = win._ask_pending("Color")

        assert "Apply and continue" not in seen, (
            "the prompt offered an apply that would silently do nothing "
            "while an unrelated busy op is running")
        assert answer == "discard"
    finally:
        win._set_busy(False)


def test_land_deferred_nav_bails_if_the_apply_never_actually_committed(
        qtbot, tmp_path):
    """MINOR 3(a). The _has_pending() bail in _land_deferred_nav is the
    safety half of the async fix: a refused or failed apply (Levels on a
    still-linear image, a cancelled tool, an exception) leaves its pending
    slot set, and landing the deferred nav anyway would sweep the user
    forward as if the apply had worked.
    """
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)                # pending: nothing committed
    win._deferred_nav = (win._stage, win._stage + 1)    # simulate a queued deferral

    win._land_deferred_nav()

    assert win._deferred_nav is None, "a landed (or bailed) deferral must be consumed"
    assert win.current_stage_id() == "levels", (
        "landed the deferred nav even though the apply never actually committed")


def test_swap_workspace_drops_a_stale_deferred_nav(qtbot, tmp_path):
    """MINOR 3(b). A deferred nav from a superseded workspace (new image
    opened, project closed) points at a stage index and an apply that will
    never call back into it meaningfully — _swap_workspace must drop it."""
    win = _win(qtbot, tmp_path)
    win._deferred_nav = (0, 1)

    win._swap_workspace()

    assert win._deferred_nav is None


def test_the_pending_note_sits_above_the_apply_button(qtbot, tmp_path):
    """Below the primary action is past where the eye stops.

    Reported from a screenshot: the line answering "did that apply?" was muted
    grey help-text styling, underneath the big green button, and effectively
    invisible. Position carries more here than colour does.
    """
    win = _win(qtbot, tmp_path)
    win._go_to_id("saturation")
    lay = win._panel.layout()
    order = [lay.itemAt(i).widget() for i in range(lay.count())]
    assert win._panel.pending_label in order
    assert order.index(win._panel.pending_label) < order.index(win._panel.apply_btn)
    assert win._panel.pending_label.objectName() == "pendingNote"


def test_the_apply_button_is_only_green_when_there_is_an_edit_to_commit(
        qtbot, tmp_path):
    """`SUCCESS` is documented in theme.py as "there is an edit to commit". A
    button wearing it on every step at all times cannot say anything when the
    step genuinely wants pressing."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("saturation")
    assert win._panel.apply_btn.property("pending") == "false"

    win._on_sat_change(0.7, 0.0)
    win._sync_step_controls()
    assert win._panel.apply_btn.property("pending") == "true"


def test_on_color_the_green_follows_the_button_that_commits_the_pending_thing(
        qtbot, tmp_path):
    """Color carries three commit buttons. Lighting Apply Color when a TINT is
    pending would point the user at the one button that does not commit it."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._on_tint_change(0.2, 0.0)
    win._sync_step_controls()

    assert win._panel.apply_tint_btn.property("pending") == "true"
    assert win._panel.apply_btn.property("pending") == "false", (
        "Apply Color is lit for a pending tint it does not commit")


def test_truncation_is_silent_when_only_this_step_would_go(
        qtbot, tmp_path, monkeypatch):
    """Replacing your own work at the frontier is the common case and must not
    prompt."""
    asked = []
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, verb: asked.append(names) or False)
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)
    win.apply_current((0.1, 1.0, 0.9))

    target = win._truncation_target("levels")
    assert win._confirm_truncation("levels", target, "Apply") is True
    assert asked == [], "prompted when only this step's own entry was at risk"


def test_truncation_confirms_and_names_the_later_steps(
        qtbot, tmp_path, monkeypatch):
    seen = []
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, verb: seen.append(list(names)) or True)
    win = _win(qtbot, tmp_path)
    for sid, opt in (("stretch", 0.5), ("levels", (0.1, 1.0, 0.9)),
                     ("curves", [(0.0, 0.0), (1.0, 1.0)])):
        win._go_to_id(sid)
        win.apply_current(opt)
        assert win._committed_option(sid) is not None
    win._go_to_id("levels")

    target = win._truncation_target("levels")
    assert win._confirm_truncation("levels", target, "Apply") is True
    # NOTE: the brief's original assertion checked STEP_NAME["saturation"],
    # which was never applied in this test's sequence (stretch/levels/curves)
    # — a copy-paste slip. Curves is the step actually applied after Levels
    # here, so it is the one truncation must name.
    assert seen and STEP_NAME["curves"] in seen[0]
    assert STEP_NAME["levels"] not in seen[0], (
        "named this step as a casualty of redoing this step")


def test_declining_the_confirm_returns_false_and_truncates_nothing(
        qtbot, tmp_path, monkeypatch):
    """The confirm must be asked BEFORE jump_back. An implementation that
    truncates then asks would pass a test that only checked the return value."""
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, verb: False)
    win = _win(qtbot, tmp_path)
    for sid, opt in (("stretch", 0.5), ("levels", (0.1, 1.0, 0.9)),
                     ("curves", [(0.0, 0.0), (1.0, 1.0)])):
        win._go_to_id(sid)
        win.apply_current(opt)
        assert win._committed_option(sid) is not None
    before = list(win.project.entries())

    target = win._truncation_target("levels")
    assert win._confirm_truncation("levels", target, "Apply") is False
    assert list(win.project.entries()) == before


def test_a_repeated_step_is_named_once_in_the_confirm(qtbot, tmp_path, monkeypatch):
    """Trim appends rather than reaching back (see _trim), so it can appear
    twice in one history. Naming it twice reads as a bug in the dialog."""
    from nocturne.ui import main_window as mw
    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, verb: seen.append(list(names)) or False)
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("levels")
    win.apply_current((0.1, 1.0, 0.9))
    # Two Trims around a Curves, the shape _trim's append-only design produces.
    for name in ("Trim", "Curves", "Trim"):
        win.project.run_step(mw._PrecomputedStep(name, win.project.current()), "")

    win._confirm_truncation("levels", win._truncation_target("levels"), "Apply")

    assert seen, "no confirm was raised"
    assert seen[0].count("Trim") == 1, f"Trim named twice: {seen[0]}"
    assert "Curves" in seen[0]
