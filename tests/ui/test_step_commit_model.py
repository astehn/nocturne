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


# --- Whole-branch review Critical #3: on Colour, the note sat above the
# wrong button. `_pending_apply_targets` deliberately refuses to target Apply
# Color (pressing it commits the method and discards the tint), so it must
# never be the button the note sits above.

def test_the_pending_note_sits_above_apply_tint_when_a_tint_is_pending(
        qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._on_tint_change(0.2, 0.0)
    win._sync_step_controls()

    lay = win._panel.layout()
    order = [lay.itemAt(i).widget() for i in range(lay.count())]
    assert order.index(win._panel.pending_label) == \
        order.index(win._panel.apply_tint_btn) - 1
    assert order.index(win._panel.pending_label) != order.index(win._panel.apply_btn) - 1, (
        "the note still sits above Apply Color, which would discard the "
        "pending tint rather than commit it")


def test_the_pending_note_sits_above_remove_green_when_it_is_pending(
        qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._on_removegreen_change(0.4)
    win._sync_step_controls()

    lay = win._panel.layout()
    order = [lay.itemAt(i).widget() for i in range(lay.count())]
    assert order.index(win._panel.pending_label) == \
        order.index(win._panel.remove_green_btn) - 1


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


# --- Whole-branch review Critical #2: the hero green goes out on the three
# compute steps (background, deconvolution, noise_sharpen). They render no
# live preview, so Apply is the only action ever available there, and
# arriving with nothing yet committed on this image IS the invitation.

def test_arriving_at_a_never_applied_compute_stage_is_green(qtbot, tmp_path):
    """Reproduces the review exactly: arrive at Deconvolution, nothing
    touched, and the button used to read grey with no other affordance on
    screen for what to do next."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("deconvolution")
    assert win._has_pending() is False, "fixture: nothing touched yet"
    assert win._panel.apply_btn.property("pending") == "true", (
        "a never-applied compute stage must invite its own Apply")


def test_a_compute_stage_stops_being_green_once_it_has_actually_run(
        qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._go_to_id("deconvolution")
    win._panel.option_box.setCurrentText("strong")
    win.apply_current("strong")
    qtbot.waitUntil(lambda: win._has_pending() is False, timeout=10000)
    win._sync_step_controls()

    assert win._panel.apply_btn.property("pending") == "false"


def test_a_live_preview_stage_is_not_green_just_for_arriving(qtbot, tmp_path):
    """The compute-stage exception must not leak onto stages that render a
    live preview — those already have `_has_pending` to say when pressing is
    warranted, and a permanently green button there would say nothing."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("saturation")
    assert win._panel.apply_btn.property("pending") == "false"


def test_background_off_does_not_stay_green_after_being_applied(qtbot, tmp_path):
    """Background's "off" records no history entry at all (see
    apply_current), so a naive `_committed_option is None` check alone would
    read this compute stage as still needing its first Apply forever — even
    right after the user explicitly committed that decision."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("background")
    win._panel.option_box.setCurrentText("off")
    win.apply_current("off")
    win._sync_step_controls()

    assert win._panel.apply_btn.property("pending") == "false"


def test_on_color_the_green_follows_the_button_that_commits_the_pending_thing(
        qtbot, tmp_path):
    """Color carries three commit buttons. Lighting Apply Color when a TINT is
    pending would point the user at the one button that does not commit it.

    Reads the RENDERED background, not just the Qt property (whole-branch
    review Critical #4): theme.py styles `QPushButton#primary[pending=...]`,
    and apply_tint_btn/remove_green_btn had no objectName "primary" at all —
    the property was set faithfully forever with zero visual effect. A test
    on the property alone cannot see that; this fails against exactly the
    no-op the review flagged.
    """
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QColor
    from nocturne.ui.theme import build_stylesheet, SUCCESS
    win = _win(qtbot, tmp_path)
    app = QApplication.instance()
    app.setStyleSheet(build_stylesheet())
    try:
        win._go_to_id("color")
        win._on_tint_change(0.2, 0.0)
        win._sync_step_controls()

        assert win._panel.apply_tint_btn.property("pending") == "true"
        assert win._panel.apply_btn.property("pending") == "false", (
            "Apply Color is lit for a pending tint it does not commit")
        assert win._panel.apply_tint_btn.objectName() == "primary", (
            "apply_tint_btn is not wired into the #primary[pending=...] selector")
        assert win._panel.remove_green_btn.objectName() == "primary", (
            "remove_green_btn is not wired into the #primary[pending=...] selector")

        btn = win._panel.apply_tint_btn
        pm = btn.grab()
        rendered = pm.toImage().pixelColor(pm.width() // 2, pm.height() // 2)
        expected = QColor(SUCCESS)
        assert (rendered.red(), rendered.green(), rendered.blue()) == \
            (expected.red(), expected.green(), expected.blue()), (
                f"Apply Tint does not actually render green while pending: {rendered.name()}")
    finally:
        app.setStyleSheet("")


# --- Whole-branch review Critical #5: Colour's method choice is not covered
# by pending at all. _has_pending checked _STAGE_PREVIEWS["color"] = ("tint",
# "remove_green") and fell back to option_box, but Colour's selector is
# method_box — so the originally reported bug was fully intact on this one
# choice, which materially changes the result.

def test_the_color_method_choice_is_covered_by_pending(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    assert win._has_pending() is False, "fixture: nothing touched yet"

    win._panel.method_box.setCurrentText("Photometric (SPCC)")

    assert win._has_pending() is True


def test_changing_the_color_method_shows_the_pending_note(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    qtbot.wait(1)
    assert not win._panel.pending_label.isVisible()

    win._panel.method_box.setCurrentText("Photometric (SPCC)")
    qtbot.wait(1)

    assert win._panel.pending_label.isVisible()


def test_changing_the_color_method_makes_next_prompt(qtbot, tmp_path, monkeypatch):
    asked = []
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_pending",
                        lambda self, step: asked.append(step) or "cancel")
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")

    win._panel.method_box.setCurrentText("Photometric (SPCC)")
    win.go_next()

    assert asked, "changing the colour-calibration method did not prompt Next"


def test_applying_color_clears_the_method_pending_state(qtbot, tmp_path):
    """Otherwise the method reads pending forever after committing exactly
    what it said, the same class of bug _clear_pending exists to prevent for
    every other dropdown."""
    from nocturne.core.color import ColorSettings
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._panel.method_box.setCurrentText("Photometric (SPCC)")
    assert win._has_pending() is True

    win.apply_current(ColorSettings(method="photometric"))

    assert win._has_pending() is False


def test_a_pending_tint_does_not_falsely_mark_the_method_pending_too(
        qtbot, tmp_path):
    """The two mechanisms (slot-based previews, dropdown baseline) must not
    cross-contaminate: nudging the tint must not make method_box itself read
    as having moved."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._on_tint_change(0.2, 0.0)
    assert win._has_pending() is True

    assert win._panel.method_box.currentText() == win._panel.method_baseline


def test_truncation_is_silent_when_only_this_step_would_go(
        qtbot, tmp_path, monkeypatch):
    """Replacing your own work at the frontier is the common case and must not
    prompt."""
    asked = []
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: asked.append(names) or False)
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
                        lambda self, names, label, verb, **kw: seen.append(list(names)) or True)
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
                        lambda self, names, label, verb, **kw: False)
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
                        lambda self, names, label, verb, **kw: seen.append(list(names)) or False)
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


# --- Task 4: Reset step ---

def test_every_committing_stage_offers_reset_step(qtbot, tmp_path):
    """Driven from the real stage list, not a hand-written one, so a stage
    added later is covered automatically."""
    win = _win(qtbot, tmp_path)
    for stage in win._stages:
        if stage.id in ("load", "export"):
            continue
        win._go_to_id(stage.id)
        assert getattr(win._panel, "reset_step_btn", None) is not None, (
            f"{stage.id} has no Reset step button")


def test_load_and_export_have_no_reset_step_button(qtbot, tmp_path):
    """Import has nothing to reset (the toolbar Reset owns that) and Export
    writes a file rather than committing one — neither should even show the
    button, not merely disable it."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("load")
    assert win._panel.reset_step_btn is None
    win._go_to_id("export")
    assert win._panel.reset_step_btn is None


def test_reset_step_is_disabled_with_nothing_to_reset(qtbot, tmp_path):
    """Never a no-op that looks like it did something."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    assert not win._panel.reset_step_btn.isEnabled()


def test_clicking_reset_step_drops_this_steps_commit(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from nocturne.ui import main_window as mw
    # Reset at the frontier now confirms (Critical #1 below) -- accept it.
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: True)
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)
    win.apply_current((0.1, 1.0, 0.9))

    qtbot.mouseClick(win._panel.reset_step_btn, Qt.MouseButton.LeftButton)

    assert win._committed_option("levels") is None


def test_reset_step_leaves_everything_before_it_untouched(qtbot, tmp_path, monkeypatch):
    """The 'must not' case: capture the earlier state and assert UNCHANGED."""
    from nocturne.ui import main_window as mw
    # Reset at the frontier now confirms (Critical #1 below) -- accept it.
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: True)
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    assert win._committed_option("stretch") is not None
    kept = np.array(win.project.state_at(1).data, copy=True)
    win._go_to_id("levels")
    win.apply_current((0.1, 1.0, 0.9))

    win._reset_step()

    assert np.array_equal(win.project.state_at(1).data, kept)


def test_reset_step_asks_before_discarding_later_work(
        qtbot, tmp_path, monkeypatch):
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: False)
    win = _win(qtbot, tmp_path)
    for sid, opt in (("stretch", 0.5), ("levels", (0.1, 1.0, 0.9)),
                     ("curves", [(0.0, 0.0), (1.0, 1.0)])):
        win._go_to_id(sid)
        win.apply_current(opt)
        assert win._committed_option(sid) is not None
    win._go_to_id("levels")
    before = list(win.project.entries())

    win._reset_step()

    assert list(win.project.entries()) == before


# --- Whole-branch review Critical #1: Reset at the frontier is silent AND
# unrecoverable. _confirm_truncation's own-work exemption is reasoned for
# Apply, where your commit is immediately replaced by your own new one --
# Reset replaces it with nothing, and jump_back has no redo (Undo walks past
# the removed entry rather than restoring it), so Reset must confirm even
# when the only casualty is its own commit.

def test_reset_step_at_the_frontier_now_confirms_and_names_its_own_commit(
        qtbot, tmp_path, monkeypatch):
    """Reproduces the review exactly: apply Stretch, apply Levels, Reset
    Levels — before the fix this fell through _confirm_truncation's own-work
    exemption silently, entries() dropped to [Stretch] with no way back."""
    from nocturne.ui import main_window as mw
    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: seen.append(list(names)) or True)
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("levels")
    win.apply_current((0.1, 1.0, 0.9))

    win._reset_step()

    assert seen == [["Levels"]], (
        f"a frontier Reset must confirm and name its own commit: {seen}")
    assert win._committed_option("levels") is None
    assert win._committed_option("stretch") is not None


def test_declining_a_frontier_reset_confirm_keeps_the_commit(
        qtbot, tmp_path, monkeypatch):
    """The other half: declining must leave the commit exactly as it was, not
    a half-truncated state."""
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: False)
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)
    win.apply_current((0.1, 1.0, 0.9))
    before = list(win.project.entries())

    win._reset_step()

    assert list(win.project.entries()) == before
    assert win._committed_option("levels") is not None


def test_reset_step_logs_and_clears_the_warning_like_every_other_commit_path(
        qtbot, tmp_path, monkeypatch):
    """_reset_step used to log with a bare f-string while every neighbouring
    commit path uses format_log_entry, and skipped _clear_warning() — both
    fixed alongside the confirm above."""
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: True)
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)
    win.apply_current((0.1, 1.0, 0.9))
    win._show_warning("stale warning from something else")

    win._reset_step()

    assert "stale warning" not in win._warning.text()
    log_text = win.log_panel.text()
    assert "Reset Levels" in log_text


def test_reset_step_on_a_repeated_own_name_is_named_once(qtbot, tmp_path, monkeypatch):
    """Enhancements can commit the same tap name twice in one run — the
    confirm must dedupe its own-work list exactly as it already does for
    later work."""
    from nocturne.ui import main_window as mw
    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: seen.append(list(names)) or True)
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("enhancements")
    win._enhance("Boost Red")
    win._enhance("Boost Red")
    assert [n for n, _ in win.project.entries()] == ["Stretch", "Boost Red", "Boost Red"]

    win._reset_step()

    assert seen == [["Boost Red"]], f"Boost Red named more than once: {seen}"


def test_reset_step_button_enables_once_the_crop_stage_has_committed(qtbot, tmp_path):
    """`crop` has no STEP_NAME entry (it isn't a PROCESSING_ORDER step), so an
    enablement check that reused `_committed_option` would read permanently
    None here and leave the button dead even after a real Rotate."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("crop")
    assert not win._panel.reset_step_btn.isEnabled()

    win._rotate()

    assert win._panel.reset_step_btn.isEnabled()


def test_reset_step_on_crop_at_the_frontier_now_confirms_and_names_rotate(
        qtbot, tmp_path, monkeypatch):
    """Crop is first in the pipeline, so resetting it means discarding the
    whole history — here, just Rotate, the crop stage's OWN work and nothing
    else. That used to be silent AND unrecoverable (Critical #1: jump_back has
    no redo, and Undo walks past the removed entry rather than restoring it).
    It must now confirm, naming the thing that is actually going."""
    from nocturne.ui import main_window as mw
    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: seen.append(list(names)) or True)
    win = _win(qtbot, tmp_path)
    win._go_to_id("crop")
    win._rotate()
    assert win.project.entries() == [("Rotate", "")]

    win._reset_step()

    assert seen == [["Rotate"]], f"must name its own commit as what is going: {seen}"
    assert win.project.entries() == []
    assert not win._panel.reset_step_btn.isEnabled()


def test_reset_step_on_crop_names_later_real_work_and_can_be_declined(
        qtbot, tmp_path, monkeypatch):
    """Once something real happened after the crop, resetting the framing
    would take that with it — the confirm must name it, and declining must
    leave the history exactly as it was."""
    from nocturne.ui import main_window as mw
    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: seen.append(list(names)) or False)
    win = _win(qtbot, tmp_path)
    win._go_to_id("crop")
    win._rotate()
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("crop")
    before = list(win.project.entries())

    win._reset_step()

    assert seen and "Stretch" in seen[0]
    assert "Rotate" not in seen[0], "named the crop stage's own work as a casualty"
    assert list(win.project.entries()) == before


def test_reset_step_button_enables_once_an_enhancement_tap_lands(qtbot, tmp_path):
    """Same gap as crop: `enhancements` has no STEP_NAME entry either."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("enhancements")
    assert not win._panel.reset_step_btn.isEnabled()

    win._enhance("Boost Red")

    assert win._panel.reset_step_btn.isEnabled()


def test_reset_step_on_enhancements_drops_the_whole_trailing_run_not_one_tap(
        qtbot, tmp_path, monkeypatch):
    """Enhancements appends one entry per tap. Resetting the step must drop
    every tap it added in one action — not the most recent one, and not
    anything committed before the run started."""
    from nocturne.ui import main_window as mw
    # Reset at the frontier now confirms (Critical #1 below) -- accept it.
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: True)
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("enhancements")
    win._enhance("Boost Red")
    win._enhance("Vibrance")
    assert [n for n, _ in win.project.entries()] == ["Stretch", "Boost Red", "Vibrance"]

    win._reset_step()

    assert [n for n, _ in win.project.entries()] == ["Stretch"]


# --- Fix round 1: enablement must be scoped to THIS step's own work ---

def test_reset_step_disabled_on_untouched_levels_with_later_work(qtbot, tmp_path):
    """Reproduces the Critical: `_truncation_target(sid) < len(entries)`
    answers 'would truncating change anything', which is true here because
    CURVES holds real work — not because Levels does. Levels was never
    applied; the button must stay off, and pressing it would otherwise eat
    Curves silently."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("curves")
    win.apply_current([(0.0, 0.0), (1.0, 1.0)])
    win._go_to_id("levels")

    assert win._committed_option("levels") is None
    assert not win._panel.reset_step_btn.isEnabled()


def test_reset_step_disabled_on_untouched_crop_with_later_work(qtbot, tmp_path):
    """Same reproduction on crop: never cropped or rotated, but Stretch and
    Curves are real work after it. The old check would offer to wipe the
    whole history from a stage with nothing of its own in it."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("curves")
    win.apply_current([(0.0, 0.0), (1.0, 1.0)])
    win._go_to_id("crop")

    assert not win._panel.reset_step_btn.isEnabled()


# --- Fix round 1: Reset step must respect the busy guard ---

def test_reset_step_does_nothing_while_busy(qtbot, tmp_path):
    """A running worker (GraXpert, RC-Astro, ...) captured its base image
    before this call and commits onto whatever history is current when it
    lands. Truncating out from under it must not happen."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)
    win.apply_current((0.1, 1.0, 0.9))
    before = list(win.project.entries())
    win._busy = True

    win._reset_step()

    assert list(win.project.entries()) == before


def test_reset_step_button_is_disabled_while_busy(qtbot, tmp_path):
    """`_set_busy` disabled Back/Next/Apply already; the Reset step button
    must join them so it cannot be pressed in the first place, rather than
    relying on the handler's guard alone."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)
    win.apply_current((0.1, 1.0, 0.9))
    assert win._panel.reset_step_btn.isEnabled()

    win._set_busy(True)
    assert not win._panel.reset_step_btn.isEnabled()

    win._set_busy(False)
    assert win._panel.reset_step_btn.isEnabled(), (
        "real enablement was not restored once busy cleared")


# --- Fix round 1 (Minor 1): a trailing Trim must not kill the button ---

def test_reset_step_on_enhancements_survives_a_trailing_trim(qtbot, tmp_path):
    """Trim is BY DESIGN a late finishing crop appended after the tail (see
    GEOMETRY_NAMES / _trim), so taps-then-Trim is the ordinary path, not an
    edge case. The button must still walk back over the taps and reset them,
    naming Trim as an honest casualty rather than going permanently dead."""
    from nocturne.ui import main_window as mw
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("enhancements")
    win._enhance("Boost Red")
    win._enhance("Vibrance")
    win.project.run_step(mw._PrecomputedStep("Trim", win.project.current()), "")
    # The real Trim action refreshes on its own; injecting the entry directly
    # (bypassing that action) does not, so force the same recompute here
    # rather than reading the button's stale pre-Trim state.
    win._sync_step_controls()
    assert [n for n, _ in win.project.entries()] == \
        ["Stretch", "Boost Red", "Vibrance", "Trim"]
    assert win._panel.reset_step_btn.isEnabled(), (
        "a trailing Trim killed the Reset step button")

    seen = []
    from unittest.mock import patch
    with patch.object(mw.MainWindow, "_ask_truncation",
                       lambda self, names, label, verb, **kw: seen.append(list(names)) or True):
        win._reset_step()

    assert seen == [["Trim"]], f"expected Trim named as the only casualty, got {seen}"
    assert [n for n, _ in win.project.entries()] == ["Stretch"]


def test_reset_step_on_enhancements_stays_disabled_with_only_a_trim(qtbot, tmp_path):
    """No taps were ever applied — only a trailing Trim. There is nothing of
    this step's own to reset, so the button must stay off (this is the
    Critical fix and Minor 1 combined, as the review specifically called
    out)."""
    from nocturne.ui import main_window as mw
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win.project.run_step(mw._PrecomputedStep("Trim", win.project.current()), "")
    win._go_to_id("enhancements")

    assert not win._panel.reset_step_btn.isEnabled()


def test_reset_step_is_alive_after_a_tint_only_commit_on_color(qtbot, tmp_path):
    """The Color stage commits under three names, and the stage id matches only
    one of them. Without the other two a tint-only edit is not recognised as
    this stage's own work and Reset reads disabled over a real commit."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._apply_tint_step(0.3, 0.1)
    assert [n for n, _ in win.project.entries()] == ["Colour Tint"]

    win._sync_step_controls()
    assert win._panel.reset_step_btn.isEnabled(), (
        "Reset is dead over a committed tint")


def test_reset_step_is_alive_after_a_remove_green_only_commit(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._remove_green(0.5)
    assert [n for n, _ in win.project.entries()] == ["Remove Green"]

    win._sync_step_controls()
    assert win._panel.reset_step_btn.isEnabled()


def test_resetting_color_confirms_and_names_its_own_tint(
        qtbot, tmp_path, monkeypatch):
    """Frontier reset now confirms even on the stage where "own work" spans
    three names — naming the tint actually being discarded, not staying
    silent the way _confirm_truncation's Apply-only exemption used to."""
    from nocturne.ui import main_window as mw
    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: seen.append(list(names)) or True)
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._apply_tint_step(0.3, 0.1)

    win._reset_step()

    assert seen == [["Colour Tint"]], f"must name the tint being discarded: {seen}"
    assert list(win.project.entries()) == []


# --- Task 5: wire the confirm into every Apply path ---
#
# apply_current is not the only path that truncates: five other buttons commit
# straight to jump_back with no prompt. All six are user-initiated Applies and
# must be guarded identically — wiring only apply_current would leave the
# other five live-preview steps silently discarding later work, which is the
# exact inconsistency this whole design exists to end.

def test_apply_on_a_revisited_step_asks_before_discarding_later_work(
        qtbot, tmp_path, monkeypatch):
    """The oldest bug this branch fixes: main_window.py's own comment says
    'Truncate history to this stage's applied predecessors', and it did so with
    no prompt at all. Go back to step 8 of 16, press Apply, lose 9-16."""
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: False)
    win = _win(qtbot, tmp_path)
    for sid, opt in (("stretch", 0.5), ("levels", (0.1, 1.0, 0.9)),
                     ("curves", [(0.0, 0.0), (1.0, 1.0)])):
        win._go_to_id(sid)
        win.apply_current(opt)
        assert win._committed_option(sid) is not None
    win._go_to_id("levels")
    before = list(win.project.entries())

    win.apply_current((0.1, 1.0, 0.9))

    assert list(win.project.entries()) == before, (
        "Apply truncated after the user declined")


def test_apply_at_the_frontier_still_never_prompts(qtbot, tmp_path, monkeypatch):
    """Most Applies are this. A confirm here would be worse than the bug."""
    asked = []
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: asked.append(names) or True)
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)

    win.apply_current((0.1, 1.0, 0.9))

    assert asked == []


def test_remove_green_frontier_apply_does_not_prompt(qtbot, tmp_path):
    """Replacing your own Remove Green at the frontier must stay silent — the
    autouse `_ask_truncation` stub raises if it is asked at all, so a clean
    run here is itself the proof."""
    win = _win(qtbot, tmp_path)
    win._remove_green(0.5)
    win._remove_green(0.6)
    assert win.project.entries()[-1][0] == "Remove Green"


def test_remove_green_revisited_asks_and_declining_keeps_later_work(
        qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    win._remove_green(0.5)
    win._go_to_id("stretch")
    win.apply_current(0.5)   # later work; frontier for Stretch, so silent
    before = list(win.project.entries())
    from nocturne.ui import main_window as mw
    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: seen.append(list(names)) or False)

    win._remove_green(0.7)

    assert seen and "Stretch" in seen[0]
    assert list(win.project.entries()) == before, (
        "Remove Green truncated after the user declined")


def test_tint_frontier_apply_does_not_prompt(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._apply_tint_step(0.2, 0.0)
    win._apply_tint_step(0.3, 0.0)
    assert win.project.entries()[-1][0] == "Colour Tint"


def test_tint_revisited_names_remove_green_and_declining_keeps_it(
        qtbot, tmp_path, monkeypatch):
    """Re-applying a tint over [Colour Tint, Remove Green] must name Remove
    Green as a casualty: it is genuinely later work, even though both are
    buttons on the same Color stage — different from Reset on the stage
    itself, where all three names count as the stage's own."""
    win = _win(qtbot, tmp_path)
    win._apply_tint_step(0.2, 0.0)
    win._remove_green(0.4)   # later work; frontier for Remove Green, so silent
    before = list(win.project.entries())
    from nocturne.ui import main_window as mw
    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: seen.append(list(names)) or False)

    win._apply_tint_step(0.5, 0.1)

    assert seen and "Remove Green" in seen[0]
    assert list(win.project.entries()) == before


def test_saturation_frontier_apply_does_not_prompt(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._apply_saturation(0.5, 0.0)
    win._apply_saturation(0.6, 0.0)
    assert win.project.entries()[-1][0] == "Saturation"


def test_saturation_revisited_asks_and_declining_keeps_later_work(
        qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    win._apply_saturation(0.5, 0.0)
    base = win.project.current()
    win._fringe_layers = (
        win._sr_sig(base), "split",
        AstroImage(base.data * 0.4, is_linear=base.is_linear),
        AstroImage(base.data * 0.6, is_linear=base.is_linear))
    win._fringe_ready = True
    win._apply_green_fringe(0.5)   # later work; frontier for the fringe, so silent
    before = list(win.project.entries())
    from nocturne.ui import main_window as mw
    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: seen.append(list(names)) or False)

    win._apply_saturation(0.7, 0.0)

    assert seen and "Remove Green Fringe" in seen[0]
    assert list(win.project.entries()) == before


def test_green_fringe_frontier_apply_does_not_prompt(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    base = win.project.current()
    win._fringe_layers = (
        win._sr_sig(base), "split",
        AstroImage(base.data * 0.4, is_linear=base.is_linear),
        AstroImage(base.data * 0.6, is_linear=base.is_linear))
    win._fringe_ready = True
    win._apply_green_fringe(0.5)
    win._apply_green_fringe(0.6)
    assert win.project.entries()[-1][0] == "Remove Green Fringe"


def test_green_fringe_revisited_asks_and_declining_keeps_later_work(
        qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    base = win.project.current()
    win._fringe_layers = (
        win._sr_sig(base), "split",
        AstroImage(base.data * 0.4, is_linear=base.is_linear),
        AstroImage(base.data * 0.6, is_linear=base.is_linear))
    win._fringe_ready = True
    win._apply_green_fringe(0.5)
    sr_base = win.project.current()
    win._sr_layers = (
        win._sr_sig(sr_base),
        AstroImage(sr_base.data * 0.4, is_linear=sr_base.is_linear),
        AstroImage(sr_base.data * 0.6, is_linear=sr_base.is_linear))
    win._sr_ready = True
    win._apply_star_reduction(0.5)   # later work; frontier for SR, so silent
    before = list(win.project.entries())
    from nocturne.ui import main_window as mw
    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: seen.append(list(names)) or False)

    win._apply_green_fringe(0.7)

    assert seen and "Star Reduction" in seen[0]
    assert list(win.project.entries()) == before


def test_star_reduction_frontier_apply_does_not_prompt(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    base = win.project.current()
    win._sr_layers = (
        win._sr_sig(base),
        AstroImage(base.data * 0.4, is_linear=base.is_linear),
        AstroImage(base.data * 0.6, is_linear=base.is_linear))
    win._sr_ready = True
    win._apply_star_reduction(0.5)
    win._apply_star_reduction(0.6)
    assert win.project.entries()[-1][0] == "Star Reduction"


def test_star_reduction_revisited_asks_and_declining_keeps_later_work(
        qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    base = win.project.current()
    win._sr_layers = (
        win._sr_sig(base),
        AstroImage(base.data * 0.4, is_linear=base.is_linear),
        AstroImage(base.data * 0.6, is_linear=base.is_linear))
    win._sr_ready = True
    win._apply_star_reduction(0.5)
    win._enhance("Boost Red")   # later work; a plain append, no truncation at all
    before = list(win.project.entries())
    from nocturne.ui import main_window as mw
    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: seen.append(list(names)) or False)

    win._apply_star_reduction(0.7)

    assert seen and "Boost Red" in seen[0]
    assert list(win.project.entries()) == before


# --- Task 5, fix round 1: "Apply and continue" can now decline mid-flight ---
#
# _apply_current_step presses a button and returns nothing; _go_to used to
# infer success from `self._busy` alone. Before Task 5 an Apply could never
# fail to commit, so that inference was safe — a truncation confirm can now
# be declined, which leaves `_busy` False exactly like an ordinary
# synchronous commit does. Undetected, "Apply and continue" then navigated
# away with the declined edit silently discarded: a smaller instance of the
# exact class of bug this whole feature exists to end.

def test_cancelling_the_truncation_confirm_during_apply_and_continue_stays_put(
        qtbot, tmp_path, monkeypatch):
    """Capture and assert UNCHANGED, not merely 'moved somewhere else' — a fix
    that lands on some other stage would pass a weaker assertion here."""
    win = _win(qtbot, tmp_path)
    for sid, opt in (("stretch", 0.5), ("levels", (0.1, 1.0, 0.9)),
                     ("curves", [(0.0, 0.0), (1.0, 1.0)])):
        win._go_to_id(sid)
        win.apply_current(opt)
    win._go_to_id("levels")
    win._on_levels_change(0.2, 1.0, 0.9)
    stage_before = win.current_stage_id()
    entries_before = list(win.project.entries())
    _answer(monkeypatch, "apply")
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: False)

    win.go_next()

    assert win.current_stage_id() == stage_before, (
        "navigated away after the truncation confirm was declined")
    assert win._has_pending() is True, (
        "the pending Levels edit was silently dropped")
    assert list(win.project.entries()) == entries_before


def test_apply_and_continue_still_navigates_with_nothing_declined(
        qtbot, tmp_path, monkeypatch):
    """The other half of the fix. Over-correcting here turns 'Apply and
    continue' into 'apply and stay', a quiet regression nobody notices for
    weeks. Covers both shapes: no confirm needed (frontier), and a real
    confirm that is accepted."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    win._on_levels_change(0.1, 1.0, 0.9)
    stage_before = win.current_stage_id()
    _answer(monkeypatch, "apply")

    win.go_next()   # frontier: no later work, so no truncation confirm at all

    qtbot.waitUntil(lambda: win.current_stage_id() != stage_before, timeout=5000)
    assert win._has_pending() is False

    win._go_to_id("curves")
    win.apply_current([(0.0, 0.0), (1.0, 1.0)])
    win._go_to_id("levels")
    win._on_levels_change(0.3, 1.0, 0.9)
    stage_before = win.current_stage_id()
    _answer(monkeypatch, "apply")
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: True)

    win.go_next()   # a real confirm fires (Curves is later work) and is accepted

    qtbot.waitUntil(lambda: win.current_stage_id() != stage_before, timeout=5000)
    assert win._has_pending() is False


def test_color_cancelling_the_first_confirm_never_clicks_the_second_button(
        qtbot, tmp_path, monkeypatch):
    """Tint and remove-green are independent buttons on Color. Cancelling the
    first one's truncation confirm must not still press the second — that
    would ask the same destructive question again seconds after the user
    just said no."""
    win = _win(qtbot, tmp_path)
    win._remove_green(0.3)   # pre-existing later work tint's confirm will name
    rg_calls = []
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_remove_green",
                        lambda self, strength=1.0: rg_calls.append(strength))
    win._go_to_id("color")   # rebuilds the panel, wiring the patched handler
    win._panel.tint_slider.setValue(20)      # -> _on_tint_change -> _tint_pending
    win._panel.rg_slider.setValue(40)        # -> _on_removegreen_change -> _rg_pending
    assert win._pending_apply_targets() == [
        win._panel.apply_tint_btn, win._panel.remove_green_btn]
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: False)
    _answer(monkeypatch, "apply")

    win.go_next()

    assert rg_calls == [], (
        "remove_green_btn was clicked after the tint confirm was declined")
    assert win._rg_pending == pytest.approx(0.4), (
        "the still-pending remove-green edit was disturbed")
    assert win.current_stage_id() == "color"


def test_color_a_successful_tint_apply_still_lets_remove_green_proceed(
        qtbot, tmp_path, monkeypatch):
    """The loop breaks only on a DECLINED confirm, not on any click.

    Without this, "always stop after the first button" passes the whole suite:
    the declined-case test cannot tell a correct break from an over-eager one,
    because both stop. Colour is the one stage with two independent pending
    edits, so it is the only place the difference is observable.
    """
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: True)
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._on_tint_change(0.2, 0.0)
    win._on_removegreen_change(0.4)
    win._sync_step_controls()
    assert len(win._pending_apply_targets()) == 2, "need both pending to test this"

    win._apply_current_step()

    committed = [n for n, _ in win.project.entries()]
    assert "Colour Tint" in committed, "the first button never committed"
    assert "Remove Green" in committed, (
        "the loop stopped after a SUCCESSFUL first apply — break is too eager")
    assert not win._has_pending()


def test_every_committing_stage_names_the_before_after_affordance(qtbot, tmp_path):
    """Reset (Tasks 1-5) answers what he asked BY; this answers what he asked
    FOR — he wanted to "validate the before and after easily", and Space
    already does that, but he never found it. Driven by win._stages (not a
    hand-written list) so a stage added later is covered without editing
    this test."""
    win = _win(qtbot, tmp_path)
    for stage in win._stages:
        win._go_to_id(stage.id)
        hint = getattr(win._panel, "compare_hint", None)
        if stage.id in ("load", "export"):
            assert hint is None, f"{stage.id} should not offer a step-compare hint"
            continue
        assert hint is not None, f"{stage.id} has no before/after hint"
        # Space TOGGLES the peek (main_window._toggle_peek: `not self._peek_active`),
        # it does not require holding it down — the wording must match or a user
        # who tries the wrong gesture will conclude the feature is broken.
        assert "space" in hint.text().lower()
        assert "hold" not in hint.text().lower()


def test_the_truncation_dialog_defaults_to_cancel_and_names_the_step(
        qtbot, tmp_path, monkeypatch):
    """Drives the REAL _ask_truncation body, which nothing else does.

    Every other test stubs it and asserts only on the `names` argument, so the
    rendered dialog — its wording and, far worse, which button Return presses —
    was invisible to the whole suite. It shipped with the DESTRUCTIVE button as
    the default, because QMessageBox.buttons() returns layout order rather than
    insertion order, and `buttons()[-1]` therefore picked Apply rather than
    Cancel. That is the branch's headline safety dialog answering unsafely by
    reflex, and jump_back has no redo.
    """
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        mw.MainWindow._real_ask_truncation)
    seen = {}

    def fake_exec(self):
        seen["buttons"] = [b.text() for b in self.buttons()]
        seen["default"] = self.defaultButton().text()
        seen["text"] = self.text()
        seen["informative"] = self.informativeText()
        for b in self.buttons():
            if b.text() == "Cancel":
                b.click()
                return 0
        return 0

    monkeypatch.setattr(mw.QMessageBox, "exec", fake_exec)
    win = _win(qtbot, tmp_path)

    assert win._ask_truncation(["Curves", "Saturation"], "Levels", "Apply") is False

    assert seen["default"] == "Cancel", (
        f"the destructive button is the default: {seen}")
    assert "Levels" in seen["text"], (
        f"the dialog never says which step it is about: {seen['text']!r}")
    assert "Curves and Saturation" in seen["informative"]


def test_the_truncation_dialog_says_reset_when_resetting(
        qtbot, tmp_path, monkeypatch):
    """Apply and Reset were word-for-word identical before the headline."""
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        mw.MainWindow._real_ask_truncation)
    seen = {}

    def fake_exec(self):
        seen["text"] = self.text()
        seen["default"] = self.defaultButton().text()
        for b in self.buttons():
            if b.text() == "Cancel":
                b.click()
        return 0

    monkeypatch.setattr(mw.QMessageBox, "exec", fake_exec)
    win = _win(qtbot, tmp_path)

    win._ask_truncation(["Curves"], "Deconvolution", "Reset")

    assert "Reset Deconvolution" in seen["text"], seen["text"]
    assert "again" not in seen["text"], "Reset borrowed Apply's wording"
    assert seen["default"] == "Cancel"


def test_color_offers_apply_when_only_the_method_is_pending(qtbot, tmp_path):
    """A method-only change IS applicable, by pressing Apply Color.

    Refusing to target it left `_ask_pending` saying "this step can't be applied
    right now, so continuing will discard the change" about a step one button
    press would have applied. The refusal exists to protect a waiting tint; with
    no tint waiting there is nothing to protect.
    """
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    box = win._panel.method_box
    other = next(box.itemText(i) for i in range(box.count())
                 if box.itemText(i) != box.currentText())
    box.setCurrentText(other)

    assert win._has_pending()
    targets = win._pending_apply_targets()
    assert targets == [win._panel.apply_btn], (
        "the prompt would claim the step cannot be applied")


def test_color_still_refuses_apply_color_when_a_tint_is_waiting(qtbot, tmp_path):
    """The protection that refusal exists for, unchanged: Apply Color commits
    the method AND discards the tint."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    box = win._panel.method_box
    other = next(box.itemText(i) for i in range(box.count())
                 if box.itemText(i) != box.currentText())
    box.setCurrentText(other)
    win._on_tint_change(0.2, 0.0)

    targets = win._pending_apply_targets()
    assert win._panel.apply_btn not in targets, (
        "Apply Color offered while a tint is waiting — it would discard it")
    assert win._panel.apply_tint_btn in targets


def test_with_method_and_tint_pending_the_green_and_note_are_on_apply_color(
        qtbot, tmp_path):
    """MEDIUM. With the method AND a tint pending, `_apply_sequence` presses
    Apply Color first — it prepends it ahead of Apply Tint specifically to
    avoid the destructive order (Tint-then-Color commits the tint, then asks
    to discard it applying the method; Color-first discards nothing). But
    `_sync_step_controls` used to light and anchor on `_pending_apply_targets`
    instead, which orders Tint before Color (that ordering is right for
    REFUSING Apply Color while a tint waits — see the test above — but wrong
    for "which button gets pressed first"). So the green and the "Not applied
    yet" note both sat on Apply Tint while Next pressed Apply Color: following
    the app's own highlight walked the user into the order the fix exists to
    avoid. Both affordances must follow `_apply_sequence()[0]` instead."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    box = win._panel.method_box
    other = next(box.itemText(i) for i in range(box.count())
                 if box.itemText(i) != box.currentText())
    box.setCurrentText(other)
    win._on_tint_change(0.2, 0.0)
    win._sync_step_controls()

    assert win._apply_sequence()[0] is win._panel.apply_btn, (
        "fixture: Apply Color must be the first press in this situation")
    assert win._panel.apply_btn.property("pending") == "true", (
        "the green does not follow _apply_sequence's first press")

    lay = win._panel.layout()
    order = [lay.itemAt(i).widget() for i in range(lay.count())]
    assert order.index(win._panel.pending_label) == \
        order.index(win._panel.apply_btn) - 1, (
            "the note still anchors on Apply Tint, not the button Next presses first")


# --- Second whole-branch review -------------------------------------------
#
# All five findings sat at the SEAMS between the branch's mechanisms, not
# inside any one of them: one set of names serving two different questions,
# Reset truncating a step that had never committed, a sequence that ran once,
# and two dialogs whose wording nobody had ever rendered.


def test_apply_color_asks_before_discarding_a_committed_tint(
        qtbot, tmp_path, monkeypatch):
    """CRITICAL. "Colour Tint" and "Remove Green" are the COLOR STAGE's own
    work (so Reset can take them back), but they are not what Apply Color
    commits. Serving both questions from one set told the Apply confirm that a
    committed tint was this button's own work at the frontier, so Apply Color
    discarded it in silence — the exact bug this branch exists to end."""
    from nocturne.ui import main_window as mw
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._panel.apply_btn.click()
    win._apply_tint_step(0.20, 0.0)
    win._remove_green(0.40)
    before = list(win.project.entries())
    assert [n for n, _ in before] == ["Color", "Colour Tint", "Remove Green"]

    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw:
                        seen.append(list(names)) or False)

    win._panel.apply_btn.click()

    assert seen == [["Colour Tint", "Remove Green"]], (
        f"Apply Color must name the tint and the green it would discard: {seen}")
    assert list(win.project.entries()) == before, (
        "Apply Color destroyed the committed tint the user declined to lose")


def test_apply_color_at_its_own_frontier_is_still_silent(qtbot, tmp_path):
    """The other half: replacing Color's OWN commit must stay silent. The
    autouse `_ask_truncation` stub raises if asked, so a clean run is the
    proof — without it the fix above would just be "always ask"."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._panel.apply_btn.click()
    win._panel.apply_btn.click()

    assert [n for n, _ in win.project.entries()] == ["Color"]


def test_next_on_colour_never_destroys_a_committed_tint_in_silence(
        qtbot, tmp_path, monkeypatch):
    """CRITICAL, by the route a user actually reaches it: with only the method
    pending, Next offers "Apply and continue", which presses Apply Color. The
    branch's own prompt was routing a silent destruction of committed work."""
    from nocturne.ui import main_window as mw
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._panel.apply_btn.click()
    win._apply_tint_step(0.20, 0.0)
    before = list(win.project.entries())
    assert [n for n, _ in before] == ["Color", "Colour Tint"]

    box = win._panel.method_box
    box.setCurrentText(next(box.itemText(i) for i in range(box.count())
                            if box.itemText(i) != box.currentText()))
    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw:
                        seen.append(list(names)) or False)
    _answer(monkeypatch, "apply")
    stage = win.current_stage_id()

    win.go_next()

    assert seen == [["Colour Tint"]], f"navigated past the tint in silence: {seen}"
    assert list(win.project.entries()) == before
    assert win.current_stage_id() == stage, (
        "navigated on after the user declined the discard")


def test_reset_on_a_never_applied_step_leaves_later_work_alone(
        qtbot, tmp_path):
    """HIGH. The spec says the commit is removed IF this step has one. With
    none, Reset put the controls back AND truncated — eating Curves. The
    existing coverage tests the UNTOUCHED case, which one slider move walks
    straight past, so this one nudges a slider first.

    No `_ask_truncation` stub: the autouse fixture raises if a confirm is
    opened at all, which is itself the assertion that nothing was at risk."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("curves")
    win.apply_current([(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)])
    win._go_to_id("levels", user_initiated=False)
    before = list(win.project.entries())
    assert [n for n, _ in before] == ["Stretch", "Curves"]
    win._on_levels_change(0.1, 1.0, 0.9)
    assert win._has_pending()

    win._reset_step()

    assert list(win.project.entries()) == before, (
        "Reset on a step with no commit of its own discarded the later work")
    # Not `not win._has_pending()`: that is a model accessor, and a Reset that
    # cleared the pending slot without touching the sliders would pass it too
    # — _rebuild_panel gives us a fresh panel either way. Read the RENDERED
    # sliders back, against the defaults build_panel sets them to (ResetSlider
    # defaults: black=0, gamma=100 i.e. 1.00, white=100 i.e. 1.00).
    assert win._panel.black_slider.value() == 0, (
        "Reset left the black-point slider at the nudged value")
    assert win._panel.gamma_slider.value() == 100, (
        "Reset left the midtones slider at the nudged value")
    assert win._panel.white_slider.value() == 100, (
        "Reset left the white-point slider at the nudged value")


def test_reset_still_removes_this_steps_own_commit(qtbot, tmp_path, monkeypatch):
    """The teeth on the test above: "never truncate" would pass it. Reset on a
    step that HAS committed must still take that commit out."""
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: True)
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("levels")
    win.apply_current((0.1, 1.0, 0.9))
    assert [n for n, _ in win.project.entries()] == ["Stretch", "Levels"]

    win._reset_step()

    assert [n for n, _ in win.project.entries()] == ["Stretch"]


def test_the_frontier_reset_dialog_does_not_say_applied_after_it(
        qtbot, tmp_path, monkeypatch):
    """MEDIUM, and invisible for exactly the reason the destructive-default bug
    was: the two tests that drive the real body both use the later-work path,
    and the frontier one asserts on the stubbed `names` argument. Rendered, the
    seam of two earlier fixes read "Reset Levels? / This discards Levels,
    applied after it." — "it" being Levels. Assert on the TEXT."""
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        mw.MainWindow._real_ask_truncation)
    seen = {}

    def fake_exec(self):
        seen["text"] = self.text()
        seen["informative"] = self.informativeText()
        for b in self.buttons():
            if b.text() == "Cancel":
                b.click()
        return 0

    monkeypatch.setattr(mw.QMessageBox, "exec", fake_exec)
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("levels")
    win.apply_current((0.1, 1.0, 0.9))
    before = list(win.project.entries())

    win._reset_step()

    assert seen["text"] == "Reset Levels?", seen
    assert "applied after it" not in seen["informative"], (
        f"the frontier reset still reads as nonsense: {seen['informative']!r}")
    assert "Levels" in seen["informative"], seen["informative"]
    assert list(win.project.entries()) == before, (
        "the dialog was cancelled and the commit went anyway")


def test_the_reset_dialog_still_says_applied_after_it_for_later_work(
        qtbot, tmp_path, monkeypatch):
    """Teeth for the above: dropping the tail everywhere would pass it, and
    lose the one sentence that says the later work is what is at risk."""
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        mw.MainWindow._real_ask_truncation)
    seen = {}

    def fake_exec(self):
        seen["informative"] = self.informativeText()
        for b in self.buttons():
            if b.text() == "Cancel":
                b.click()
        return 0

    monkeypatch.setattr(mw.QMessageBox, "exec", fake_exec)
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("levels")
    win.apply_current((0.1, 1.0, 0.9))
    win._go_to_id("curves")
    win.apply_current([(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)])
    win._go_to_id("levels", user_initiated=False)

    win._reset_step()

    assert seen["informative"] == "This discards Curves, applied after it.", seen


def test_the_reset_dialog_uses_the_stage_label_on_crop(qtbot, tmp_path, monkeypatch):
    """LOW. `crop` and `enhancements` are stepper stages with a Reset button
    but no STEP_NAME entry, so `STEP_NAME.get(step_id, step_id)` fell back to
    the raw id: "Reset crop?", lowercase, against the stage label "Crop" that
    the log line for the same action already used (`self._stages[self._stage]
    .label`). Assert on the RENDERED text, not the stubbed `names` list every
    other Reset test checks — that stub cannot see which label reached the
    dialog."""
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        mw.MainWindow._real_ask_truncation)
    seen = {}

    def fake_exec(self):
        seen["text"] = self.text()
        for b in self.buttons():
            if b.text() == "Cancel":
                b.click()
        return 0

    monkeypatch.setattr(mw.QMessageBox, "exec", fake_exec)
    win = _win(qtbot, tmp_path)
    win._go_to_id("crop")
    win._rotate()
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("crop", user_initiated=False)

    win._reset_step()

    assert seen["text"] == "Reset Crop?", (
        f"the dialog fell back to the raw stage id: {seen}")


def test_the_reset_dialog_uses_the_stage_label_on_enhancements(
        qtbot, tmp_path, monkeypatch):
    """Same gap, the other stepper stage that carries a Reset button."""
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        mw.MainWindow._real_ask_truncation)
    seen = {}

    def fake_exec(self):
        seen["text"] = self.text()
        for b in self.buttons():
            if b.text() == "Cancel":
                b.click()
        return 0

    monkeypatch.setattr(mw.QMessageBox, "exec", fake_exec)
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("enhancements")
    win._enhance("Boost Red")

    win._reset_step()

    assert seen["text"] == "Reset Enhancements?", (
        f"the dialog fell back to the raw stage id: {seen}")


def test_a_first_ever_apply_does_not_say_again(qtbot, tmp_path, monkeypatch):
    """LOW. "Apply Levels again?" on a step this image has never had applied."""
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        mw.MainWindow._real_ask_truncation)
    seen = {}

    def fake_exec(self):
        seen["text"] = self.text()
        for b in self.buttons():
            if b.text() == "Cancel":
                b.click()
        return 0

    monkeypatch.setattr(mw.QMessageBox, "exec", fake_exec)
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("curves")
    win.apply_current([(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)])
    win._go_to_id("levels", user_initiated=False)

    win.apply_current((0.1, 1.0, 0.9))

    assert seen["text"] == "Apply Levels?", seen


def test_re_applying_a_committed_step_still_says_again(
        qtbot, tmp_path, monkeypatch):
    """Teeth for the above: deleting "again" outright would pass it."""
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        mw.MainWindow._real_ask_truncation)
    seen = {}

    def fake_exec(self):
        seen["text"] = self.text()
        for b in self.buttons():
            if b.text() == "Cancel":
                b.click()
        return 0

    monkeypatch.setattr(mw.QMessageBox, "exec", fake_exec)
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("levels")
    win.apply_current((0.1, 1.0, 0.9))
    win._go_to_id("curves")
    win.apply_current([(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)])
    win._go_to_id("levels", user_initiated=False)

    win.apply_current((0.2, 1.0, 0.9))

    assert seen["text"] == "Apply Levels again?", seen


def test_colour_next_applies_the_method_and_the_tint_in_one_prompt(
        qtbot, tmp_path, monkeypatch):
    """MEDIUM. Colour is the one stage with two independent pending sources, so
    this is its ordinary case. One pass over the targets committed the tint and
    left the method pending, and `_go_to` then returned with the stage
    unchanged and nothing said — press Next, watch nothing happen.

    The method must go FIRST: "Color" precedes "Colour Tint" in
    PROCESSING_ORDER, so committing the tint and then the method discards the
    tint the app just committed on the user's behalf."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    box = win._panel.method_box
    box.setCurrentText(next(box.itemText(i) for i in range(box.count())
                            if box.itemText(i) != box.currentText()))
    win._on_tint_change(0.2, 0.0)
    stage = win.current_stage_id()
    _answer(monkeypatch, "apply")

    win.go_next()

    # No _ask_truncation stub: the autouse fixture raises if a truncation
    # confirm is opened, so this also proves the sequence never asked to
    # discard work it had just committed itself.
    assert [n for n, _ in win.project.entries()] == ["Color", "Colour Tint"], (
        "one 'Apply and continue' must commit both, method first")
    assert not win._has_pending()
    assert win.current_stage_id() != stage, "the navigation never landed"
