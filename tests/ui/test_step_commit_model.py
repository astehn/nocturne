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
    # Shown, as a real window is: visibility checks are hollow otherwise —
    # Qt's isVisible() is false for every child of an unshown top-level
    # regardless of its own setVisible() call.
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
    never shown is exactly the bug this whole task exists to fix.

    Since 2026-09-25 (consistent panels) there is no separate "Not applied
    yet" label: the Apply button carries the state itself, decided once in
    MainWindow._step_state. Read it off the real button, and read the words
    the user actually sees ("● changes not applied"), not just the colour."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("levels")
    qtbot.wait(1)
    assert win._panel.apply_btn.state() != "pending"
    win._on_levels_change(0.1, 1.0, 0.9)
    win._sync_step_controls()
    assert win._panel.apply_btn.state() == "pending"
    assert "not applied" in win._panel.apply_btn.status_text()
    # Third leg, and the one with teeth: the two above are both satisfied by a
    # mark-only _sync_step_controls that never clears it again.
    # Saturation is deliberate — it commits through its own handler rather than
    # apply_current, which is where the clear was missing entirely.
    # user_initiated=False: this jump is test plumbing to reach Saturation, not
    # a simulated user abandoning the pending Levels change (Task 2 covers that
    # guard on its own) — without it this hangs on an unstubbed _ask_pending.
    win._go_to_id("saturation", user_initiated=False)
    qtbot.wait(1)                     # same rebuild lag as above
    # 0.70, not the panel's own default of 0.50: since 2026-09-13 a value equal
    # to what the controls read untouched is NOT pending, so driving the step to
    # its default would assert the opposite of what this line means. Nebula
    # stays 0 so no star split runs and this is instant.
    win._on_sat_change(0.70, 0.0)
    assert win._panel.apply_btn.state() == "pending"
    win._apply_saturation(0.70, 0.0)
    qtbot.wait(1)
    assert win._panel.apply_btn.state() == "applied"


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


def test_the_color_stage_covers_its_tint_preview(qtbot, tmp_path):
    """Color's tint preview had no coverage at all: its slot is keyed by step
    name ("tint"), which current_stage_id never returns. De-green Sky used to
    share this problem as Color's second preview, but now has its own stage
    and needs no mapping here — see
    test_the_remove_green_stage_covers_its_own_preview below."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    assert win._has_pending() is False
    win._on_tint_change(0.2, 0.0)
    assert win._has_pending() is True
    win._apply_tint_step(0.2, 0.0)
    assert win._has_pending() is False


def test_color_pending_is_not_disturbed_by_a_stale_remove_green_slot(qtbot, tmp_path):
    """De-green Sky moved off Color's panel entirely — _STAGE_PREVIEWS["color"]
    must be ("tint",) only. A value left in _rg_pending (from a previous
    visit to the remove_green stage, discarded rather than applied) must not
    make Color read as pending; if _STAGE_PREVIEWS["color"] regained
    "remove_green" this would spuriously light Color's pending state again."""
    win = _win(qtbot, tmp_path)
    win._rg_pending = 0.4     # simulate a stale slot from another stage
    win._go_to_id("color")
    assert win._has_pending() is False


def test_the_remove_green_stage_covers_its_own_preview(qtbot, tmp_path):
    """Unlike tint, remove_green's stage id IS its step id, so it needs no
    entry in _STAGE_PREVIEWS at all — the generic (sid,) fallback covers it."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("remove_green")
    assert win._has_pending() is False
    win._on_removegreen_change(0.4)
    assert win._has_pending() is True


def test_the_label_appears_as_soon_as_a_compute_dropdown_moves(qtbot, tmp_path, monkeypatch):
    """The label reads the dropdown, so it must hear the dropdown.

    `_has_pending()` was already right here; only the label lagged, catching up
    on the next `_refresh` — i.e. when the user did something else entirely. A
    signal that is correct but displayed late is still a step that looks applied
    when it is not.

    The pending mark now lives on the Apply button (its state; consistent
    panels, 2026-09-25). On a compute step never applied the button is
    already green at arrival (`not_run`), so the colour alone cannot show the
    dropdown being heard there. Background is used instead, after committing
    "off" — bookkeeping only, no tool runs — which reads `applied`; moving
    the dropdown must then make it `pending` at once. GraXpert is
    reported present only so Apply is enabled for "light" (a disabled Apply is
    never marked); nothing here presses it.
    """
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw, "graxpert_valid", lambda settings: True)
    win = _win(qtbot, tmp_path)
    win._go_to_id("background")
    win._panel.option_box.setCurrentText("off")
    win.apply_current("off")
    qtbot.wait(1)
    assert win._panel.option_box.currentText() == "off", "precondition"
    assert win._panel.apply_btn.state() == "applied", "precondition"

    win._panel.option_box.setCurrentText("light")
    qtbot.wait(1)

    assert win._panel.apply_btn.state() == "pending", (
        "the dropdown moved and the button did not notice until the next refresh")


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


def test_remove_green_apply_and_continue_commits_it(
        qtbot, tmp_path, monkeypatch):
    """De-green Sky is a single-commit stage like any other now (its own
    stage, its own apply_btn) — 'Apply and continue' must not silently
    discard a pending strength."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("remove_green")
    win._panel.rg_slider.setValue(40)   # -> 0.40; fires _on_removegreen_change
    before = list(win.project.entries())
    _answer(monkeypatch, "apply")

    win.go_next()

    qtbot.waitUntil(lambda: len(win.project.entries()) == len(before) + 1,
                    timeout=5000)
    name, option = win.project.entries()[-1]
    assert name == "De-green Sky"
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
    Color's apply_tint_btn, so that stayed clickable during ANY unrelated
    busy op (a plate solve, Auto Enhance, Save Project — all _run_busy).
    Reproduced: tint nudged, an unrelated op running,
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

    Since 2026-09-25 the answer is IN the button (consistent panels): no line
    can sit past where the eye stops because there is no separate line — the
    pinned Apply itself carries the mark, and nothing else in the window
    claims to.
    """
    from PySide6.QtWidgets import QLabel
    win = _win(qtbot, tmp_path)
    win._go_to_id("saturation")
    win._on_sat_change(0.70, 0.0)
    win._sync_step_controls()
    assert win._side.action_slot.isAncestorOf(win._panel.apply_btn)
    assert win._panel.apply_btn.state() == "pending"
    assert not [lab for lab in win.findChildren(QLabel)
                if lab.objectName() == "pendingNote"], "a second pending line"


# --- Whole-branch review Critical #3: on Colour, the note sat above the
# wrong button. `_pending_apply_targets` deliberately refuses to target Apply
# Color (pressing it commits the method and discards the tint), so it must
# never be the button the note sits above.

def test_the_pending_note_sits_above_apply_tint_when_a_tint_is_pending(
        qtbot, tmp_path):
    # Colour has ONE visible Apply since 2026-09-25 (consistent panels), and
    # it commits the tint (via _apply_sequence) — so a pending tint marks that
    # one button, and pressing it commits the tint rather than only the method.
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._panel.tint_slider.setValue(20)
    win._sync_step_controls()

    assert win._panel.apply_btn.state() == "pending"
    assert win._apply_sequence() == [win._panel.apply_tint_btn], (
        "the pending tint is not what the one Apply would commit")
    n = len(win.project.entries())
    win._panel.apply_btn.click()
    assert [e for e, _ in win.project.entries()][n:] == ["Colour Tint"]


def test_the_pending_note_sits_above_remove_green_apply_when_it_is_pending(
        qtbot, tmp_path):
    """De-green Sky is a single-commit stage now, the same shape as every
    other one (see test_the_pending_note_sits_above_the_apply_button) — kept
    as its own regression since this exact stage used to be special-cased on
    Colour, with its own button name and its own coverage gap."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("remove_green")
    assert win._panel.apply_btn.state() == "no_change", "precondition"
    win._on_removegreen_change(0.4)
    win._sync_step_controls()

    assert win._panel.apply_btn.state() == "pending"


def test_the_apply_button_is_only_green_when_there_is_an_edit_to_commit(
        qtbot, tmp_path):
    """`SUCCESS` is documented in theme.py as "there is an edit to commit". A
    button wearing it on every step at all times cannot say anything when the
    step genuinely wants pressing.

    Since 2026-09-25 green means "pressing this will change your image" (spec
    §4), so a never-applied step whose default DOES something is green too
    (`not_run`). Local Contrast at 0 is a proven no-op (NOOP_AT_DEFAULT): it
    arrives plain, and turns green once the slider says something. (This used
    Saturation, whose 0.50 turned out not to be bit-exact — see
    NOOP_AT_DEFAULT.)"""
    win = _win(qtbot, tmp_path)
    win._go_to_id("local_contrast")
    assert win._panel.apply_btn.state() == "no_change"
    assert win._panel.apply_btn.property("pending") == "false"

    win._on_lc_change(0.4)
    win._sync_step_controls()
    assert win._panel.apply_btn.state() == "pending"
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
    assert win._panel.apply_btn.state() == "not_run", (
        "a never-applied compute stage must invite its own Apply")


def test_a_compute_stage_stops_being_green_once_it_has_actually_run(
        qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._go_to_id("deconvolution")
    win._panel.option_box.setCurrentText("strong")
    win.apply_current("strong")
    qtbot.waitUntil(lambda: win._has_pending() is False, timeout=10000)
    win._sync_step_controls()

    assert win._panel.apply_btn.state() == "applied"


def test_a_live_preview_stage_is_not_green_just_for_arriving(qtbot, tmp_path):
    """The compute-stage exception must not leak onto stages that render a
    live preview — those already have `_has_pending` to say when pressing is
    warranted, and a permanently green button there would say nothing.

    Sharpened by spec §4 (2026-09-25): "not green for arriving" holds exactly
    where the untouched panel is a no-op. Every NOOP_AT_DEFAULT stage must
    arrive `no_change`, plain and disabled."""
    from nocturne.ui.main_window import NOOP_AT_DEFAULT
    win = _win(qtbot, tmp_path)
    for sid in sorted(NOOP_AT_DEFAULT):
        win._go_to_id(sid, user_initiated=False)
        assert win._panel.apply_btn.state() == "no_change", sid
        assert win._panel.apply_btn.property("pending") == "false", sid
        assert not win._panel.apply_btn.isEnabled(), sid


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

    assert win._panel.apply_btn.state() == "applied"


def test_on_color_the_green_follows_the_button_that_commits_the_pending_thing(
        qtbot, tmp_path):
    """Color shows ONE Apply since 2026-09-25 (consistent panels) and it
    commits the tint, so a pending tint must light THAT button — there is no
    other one on screen to point at.

    Reads the RENDERED background, not just the Qt property (whole-branch
    review Critical #4): theme.py styles `QPushButton#primary[pending=...]`,
    and a button without objectName "primary" had the property set faithfully
    forever with zero visual effect. A test on the property alone cannot see
    that.
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

        assert win._panel.apply_btn.state() == "pending"
        assert win._panel.apply_btn.objectName() == "primary", (
            "apply_btn is not wired into the #primary[pending=...] selector")

        btn = win._panel.apply_btn
        pm = btn.grab()
        # Sample the fill beside the centred label, not the centre: the
        # centre lands on a glyph once the button gets its natural height.
        rendered = pm.toImage().pixelColor(pm.width() // 8, pm.height() // 2)
        expected = QColor(SUCCESS)
        assert (rendered.red(), rendered.green(), rendered.blue()) == \
            (expected.red(), expected.green(), expected.blue()), (
                f"Colour's Apply does not actually render green while a tint is "
                f"pending: {rendered.name()}")
    finally:
        app.setStyleSheet("")


def test_on_remove_green_its_own_apply_renders_green_while_pending(
        qtbot, tmp_path):
    """Same regression as above, for De-green Sky's own stage: its button is
    the generic `apply_btn`, not a special-cased `remove_green_btn`, and must
    be wired into the same #primary[pending=...] selector as every other
    single-commit stage."""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QColor
    from nocturne.ui.theme import build_stylesheet, SUCCESS
    win = _win(qtbot, tmp_path)
    app = QApplication.instance()
    app.setStyleSheet(build_stylesheet())
    try:
        win._go_to_id("remove_green")
        win._on_removegreen_change(0.4)
        win._sync_step_controls()

        assert win._panel.apply_btn.state() == "pending"
        assert win._panel.apply_btn.objectName() == "primary", (
            "apply_btn is not wired into the #primary[pending=...] selector")

        btn = win._panel.apply_btn
        pm = btn.grab()
        # Sample the fill beside the centred label, not the centre: the
        # centre lands on a glyph once the button gets its natural height.
        rendered = pm.toImage().pixelColor(pm.width() // 8, pm.height() // 2)
        expected = QColor(SUCCESS)
        assert (rendered.red(), rendered.green(), rendered.blue()) == \
            (expected.red(), expected.green(), expected.blue()), (
                f"Apply De-green Sky does not actually render green while pending: "
                f"{rendered.name()}")
    finally:
        app.setStyleSheet("")


# --- Whole-branch review Critical #5: Colour's method choice is not covered
# by pending at all. _has_pending checked _STAGE_PREVIEWS["color"] = ("tint",)
# and fell back to option_box, but Colour's selector is method_box — so the
# originally reported bug was fully intact on this one choice, which
# materially changes the result.

def test_the_color_method_choice_is_covered_by_pending(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    assert win._has_pending() is False, "fixture: nothing touched yet"

    win._panel.method_box.setCurrentText("Photometric (SPCC)")

    assert win._has_pending() is True


def test_changing_the_color_method_shows_the_pending_note(qtbot, tmp_path):
    # The note is the Apply button's state now (consistent panels). A
    # never-applied Colour is already green (`not_run`: pressing would
    # calibrate), so commit the method first to get a plain `applied` button,
    # then show that moving the dropdown makes it `pending`.
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._panel.apply_btn.click()
    qtbot.wait(1)
    assert win._panel.apply_btn.state() == "applied", "precondition"

    win._panel.method_box.setCurrentText("Photometric (SPCC)")
    qtbot.wait(1)

    assert win._panel.apply_btn.state() == "pending"


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
    """The Color stage commits under two names, and the stage id matches only
    one of them. Without the other a tint-only edit is not recognised as
    this stage's own work and Reset reads disabled over a real commit."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._apply_tint_step(0.3, 0.1)
    assert [n for n, _ in win.project.entries()] == ["Colour Tint"]

    win._sync_step_controls()
    assert win._panel.reset_step_btn.isEnabled(), (
        "Reset is dead over a committed tint")


def test_reset_step_is_alive_after_a_remove_green_only_commit(qtbot, tmp_path):
    """De-green Sky now has its own stage, whose id matches its own STEP_NAME
    entry directly — no _stage_own_names special case needed, unlike Color."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("remove_green")
    win._remove_green(0.5)
    assert [n for n, _ in win.project.entries()] == ["De-green Sky"]

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
    """Replacing your own De-green Sky at the frontier must stay silent — the
    autouse `_ask_truncation` stub raises if it is asked at all, so a clean
    run here is itself the proof."""
    win = _win(qtbot, tmp_path)
    win._remove_green(0.5)
    win._remove_green(0.6)
    assert win.project.entries()[-1][0] == "De-green Sky"


def test_remove_green_revisited_asks_and_declining_keeps_later_work(
        qtbot, tmp_path, monkeypatch):
    """Later work for De-green Sky means AFTER it in PROCESSING_ORDER now —
    Recover Core, not Stretch, which moved to sit BEFORE it."""
    win = _win(qtbot, tmp_path)
    win._remove_green(0.5)
    win._go_to_id("recover_core")
    win.apply_current(0.3)   # later work; frontier for Recover Core, so silent
    before = list(win.project.entries())
    from nocturne.ui import main_window as mw
    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: seen.append(list(names)) or False)

    win._remove_green(0.7)

    assert seen and "Recover Core" in seen[0]
    assert list(win.project.entries()) == before, (
        "De-green Sky truncated after the user declined")


def test_tint_frontier_apply_does_not_prompt(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._apply_tint_step(0.2, 0.0)
    win._apply_tint_step(0.3, 0.0)
    assert win.project.entries()[-1][0] == "Colour Tint"


def test_tint_revisited_names_remove_green_and_declining_keeps_it(
        qtbot, tmp_path, monkeypatch):
    """Re-applying a tint over [Colour Tint, De-green Sky] must name
    De-green Sky as a casualty: it is genuinely later work, now on its own
    stage entirely — different from Reset on the Color stage itself, where
    only "Color" and "Colour Tint" count as that stage's own."""
    win = _win(qtbot, tmp_path)
    win._apply_tint_step(0.2, 0.0)
    win._remove_green(0.4)   # later work; frontier for De-green Sky, so silent
    before = list(win.project.entries())
    from nocturne.ui import main_window as mw
    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: seen.append(list(names)) or False)

    win._apply_tint_step(0.5, 0.1)

    assert seen and "De-green Sky" in seen[0]
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
        AstroImage(base.data * 0.6, is_linear=base.is_linear), None)
    win._fringe_ready = True
    win._apply_green_fringe(0.5)   # later work; frontier for the fringe, so silent
    before = list(win.project.entries())
    from nocturne.ui import main_window as mw
    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: seen.append(list(names)) or False)

    win._apply_saturation(0.7, 0.0)

    assert seen and "De-green Stars" in seen[0]
    assert list(win.project.entries()) == before


def test_green_fringe_frontier_apply_does_not_prompt(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    base = win.project.current()
    win._fringe_layers = (
        win._sr_sig(base), "split",
        AstroImage(base.data * 0.4, is_linear=base.is_linear),
        AstroImage(base.data * 0.6, is_linear=base.is_linear), None)
    win._fringe_ready = True
    win._apply_green_fringe(0.5)
    win._apply_green_fringe(0.6)
    assert win.project.entries()[-1][0] == "De-green Stars"


def test_green_fringe_revisited_asks_and_declining_keeps_later_work(
        qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    base = win.project.current()
    win._fringe_layers = (
        win._sr_sig(base), "split",
        AstroImage(base.data * 0.4, is_linear=base.is_linear),
        AstroImage(base.data * 0.6, is_linear=base.is_linear), None)
    win._fringe_ready = True
    win._apply_green_fringe(0.5)
    sr_base = win.project.current()
    win._sr_layers = (
        win._sr_sig(sr_base),
        AstroImage(sr_base.data * 0.4, is_linear=sr_base.is_linear),
        AstroImage(sr_base.data * 0.6, is_linear=sr_base.is_linear), "StarX")
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
        AstroImage(base.data * 0.6, is_linear=base.is_linear), "StarX")
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
        AstroImage(base.data * 0.6, is_linear=base.is_linear), "StarX")
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
    """Method and tint are independent commits on Color — its only two
    remaining sources now that De-green Sky has its own stage. Cancelling the
    first one's (the method's) truncation confirm must not still press the
    second (tint) — that would ask the same destructive question again
    seconds after the user just said no."""
    win = _win(qtbot, tmp_path)
    win._apply_tint_step(0.1, 0.0)   # pre-existing later work the method confirm will name
    tint_calls = []
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_apply_tint_step",
                        lambda self, tint, temperature: tint_calls.append((tint, temperature)))
    win._go_to_id("color")   # rebuilds the panel, wiring the patched handler
    win._panel.method_box.setCurrentText("Photometric (SPCC)")
    win._panel.tint_slider.setValue(20)      # -> _on_tint_change -> _tint_pending
    # Unlike the old tint/remove-green pair, method and tint are never BOTH
    # in _pending_apply_targets at once (that list refuses Apply Color while
    # a tint waits) — the sequence _apply_current_step actually presses is
    # _apply_sequence, which puts the method first.
    assert win._apply_sequence() == [
        win._panel.apply_method_btn, win._panel.apply_tint_btn]
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: False)
    _answer(monkeypatch, "apply")

    win.go_next()

    assert tint_calls == [], (
        "apply_tint_btn was clicked after the method confirm was declined")
    assert win._tint_pending == pytest.approx((0.2, 0.0)), (
        "the still-pending tint edit was disturbed")
    assert win.current_stage_id() == "color"


def test_color_a_successful_method_apply_still_lets_tint_proceed(
        qtbot, tmp_path, monkeypatch):
    """The loop breaks only on a DECLINED confirm, not on any click.

    Without this, "always stop after the first button" passes the whole suite:
    the declined-case test cannot tell a correct break from an over-eager one,
    because both stop. Colour is the one stage with two independent pending
    commits (method, tint), so it is the only place the difference is
    observable.
    """
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: True)
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._panel.method_box.setCurrentText("Photometric (SPCC)")
    win._on_tint_change(0.2, 0.0)
    win._sync_step_controls()
    assert len(win._apply_sequence()) == 2, "need both pending to test this"

    win._apply_current_step()

    committed = [n for n, _ in win.project.entries()]
    assert "Color" in committed, "the first button never committed"
    assert "Colour Tint" in committed, (
        "the loop stopped after a SUCCESSFUL first apply — break is too eager")
    assert not win._has_pending()


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
    assert targets == [win._panel.apply_method_btn], (
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
    assert win._panel.apply_method_btn not in targets, (
        "the method alone offered while a tint is waiting — it would discard it")
    assert win._panel.apply_btn not in targets, (
        "the visible Apply runs the sequence itself; as a target it would re-enter")
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

    assert win._apply_sequence()[0] is win._panel.apply_method_btn, (
        "fixture: the method must be the first press in this situation")
    # Since 2026-09-25 (consistent panels) there is ONE visible Apply and it
    # presses exactly _apply_sequence, so the green and the press can no
    # longer point at different buttons: the one Apply is green, and pressing
    # it commits in the safe order.
    assert win._panel.apply_btn.state() == "pending"
    n = len(win.project.entries())
    win._panel.apply_btn.click()
    assert [e for e, _ in win.project.entries()][n:] == ["Color", "Colour Tint"]


# --- Second whole-branch review -------------------------------------------
#
# All five findings sat at the SEAMS between the branch's mechanisms, not
# inside any one of them: one set of names serving two different questions,
# Reset truncating a step that had never committed, a sequence that ran once,
# and two dialogs whose wording nobody had ever rendered.


def test_apply_color_asks_before_discarding_a_committed_tint(
        qtbot, tmp_path, monkeypatch):
    """CRITICAL. "Colour Tint" is the COLOR STAGE's own work (so Reset can
    take it back), but it is not what Apply Color commits. Serving both
    questions from one set told the Apply confirm that a committed tint was
    this button's own work at the frontier, so Apply Color discarded it in
    silence — the exact bug this branch exists to end. "De-green Sky" is
    exercised here too even though it now has its own stage (and so is no
    longer part of Color's own-names at all) — it is still later work sitting
    in the history that Apply Color must not discard silently."""
    from nocturne.ui import main_window as mw
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._panel.apply_btn.click()
    win._apply_tint_step(0.20, 0.0)
    win._remove_green(0.40)
    before = list(win.project.entries())
    assert [n for n, _ in before] == ["Color", "Colour Tint", "De-green Sky"]

    seen = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw:
                        seen.append(list(names)) or False)

    win._panel.apply_btn.click()

    assert seen == [["Colour Tint", "De-green Sky"]], (
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


def _cropping(qtbot, tmp_path):
    """A window sitting on Crop with the box shown at the content edges."""
    from tests.ui.test_main_window import _bordered_window
    win = _bordered_window(qtbot, tmp_path)
    win._go_to_id("crop")
    win.image_view.show_crop_box()
    return win


def test_a_fresh_crop_box_is_not_pending(qtbot, tmp_path):
    """Matching `_on_crop_dismiss`: an untouched box has no work to lose, so
    showing one must not start prompting on every Next."""
    win = _cropping(qtbot, tmp_path)
    assert win.image_view.crop_box_visible()
    assert not win._has_pending()


def test_an_adjusted_crop_box_is_pending(qtbot, tmp_path):
    win = _cropping(qtbot, tmp_path)
    t, b, l, r = win.image_view.crop_bounds()
    win.image_view._set_bounds((t + 2, b - 2, l + 2, r - 2))
    win.image_view._geometry_changed()   # what a real drag ends in

    assert win._has_pending(), "an adjusted crop box is uncommitted work"
    win._sync_step_controls()
    assert win._panel.apply_btn.state() == "pending"


def test_next_does_not_discard_an_adjusted_crop_without_asking(
        qtbot, tmp_path, monkeypatch):
    """The reported bug: place a crop, press Next, and the app moved happily on
    to Background with the selection thrown away."""
    from nocturne.ui import main_window as mw
    asked = []
    monkeypatch.setattr(mw.MainWindow, "_ask_pending",
                        lambda self, step: asked.append(step) or "cancel")
    win = _cropping(qtbot, tmp_path)
    t, b, l, r = win.image_view.crop_bounds()
    win.image_view._set_bounds((t + 2, b - 2, l + 2, r - 2))
    win.image_view._geometry_changed()   # what a real drag ends in

    win.go_next()

    assert asked, "Next discarded the crop selection without asking"
    assert win.current_stage_id() == "crop", "cancel did not stay put"
    assert win.image_view.crop_box_visible(), "the box was dropped anyway"


def test_apply_and_continue_from_crop_commits_the_crop(
        qtbot, tmp_path, monkeypatch):
    from nocturne.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_ask_pending", lambda self, step: "apply")
    win = _cropping(qtbot, tmp_path)
    t, b, l, r = win.image_view.crop_bounds()
    win.image_view._set_bounds((t + 2, b - 2, l + 2, r - 2))
    win.image_view._geometry_changed()   # what a real drag ends in

    win.go_next()

    assert [n for n, _ in win.project.entries()] == ["Crop"]
    assert win.current_stage_id() != "crop"


def test_the_fringe_step_says_which_of_its_two_paths_ran(qtbot, tmp_path):
    """Same button, same slider, same step name — two implementations that
    behave differently enough that telling them apart took a measurement
    rather than a glance. StarX de-greens a stars layer; the free path
    de-greens the whole image inside a star mask and moves the sky more than
    the stars. Nothing anywhere said which one you got."""
    win = _win(qtbot, tmp_path)

    # A real split whose tool IS known — name it.
    win._fringe_layers = ("sig", "split", None, None, "StarX")
    assert win._fringe_path_label() == "StarX"
    assert "RC-Astro (StarX)" in win._fringe_status_text()

    win._fringe_layers = ("sig", "split", None, None, "StarNet2")
    assert "StarNet2" in win._fringe_status_text()

    # A real split whose tool is NOT known — say the operation, name no tool.
    # This asserted "StarX" until 2026-09-22, which was true only while StarX
    # was the one splitter this step could reach. After StarNet2 it made the
    # panel tell users with no RC-Astro that RC-Astro had run.
    win._fringe_layers = ("sig", "split", None, None, None)
    assert win._fringe_path_label() == "split"
    unknown = win._fringe_status_text()
    assert "StarX" not in unknown and "RC-Astro" not in unknown, unknown
    assert "stars layer" in unknown, "it must still say which operation ran"

    win._fringe_layers = ("sig", "mask", None, None, None)
    assert win._fringe_path_label() == "mask"
    text = win._fringe_status_text()
    assert "whole image" in text, (
        "the free path's note does not say it moves the background")


def test_the_automatic_stretch_records_the_amount_it_used(qtbot, tmp_path):
    """A history entry of `""` renders in the provenance report as a bare
    "Stretch" with no number — indistinguishable from a step whose amount
    nobody knows, next to manual ones that say "Stretch — 0.30".

    It is the step's own default either way (parse_stretch_option("") resolves
    to it), so this is about the RECORD, not the picture. Asserted against
    parse_stretch_option rather than a literal: writing 0.30 here would be the
    fourth copy of the number whose copies drifted apart on 2026-09-14.
    """
    from nocturne.steps.stretch_step import parse_stretch_option
    win = _linear_win(qtbot, tmp_path)
    assert win._ensure_stretched("Levels") is True
    stretches = [(n, o) for n, o in win.project.entries() if n == "Stretch"]
    assert stretches, "the automatic stretch did not record an entry at all"
    assert stretches[-1][1] == parse_stretch_option("")
    assert stretches[-1][1] != "", "an empty option is what made the report silent"
