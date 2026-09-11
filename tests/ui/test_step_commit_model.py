"""Whether a step's settings have been committed, and whether the app says so.

The confusion this answers was reported by a user with his own observatory: the
preview is pixel-identical to the commit (see _preview_base — that is
deliberate), so nothing on screen distinguishes "previewed" from "applied".
"""
import numpy as np

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
    silent discard this task exists to fix."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("color")
    win._on_tint_change(0.2, 0.0)
    before = list(win.project.entries())
    _answer(monkeypatch, "apply")

    win.go_next()

    qtbot.waitUntil(lambda: len(win.project.entries()) == len(before) + 1,
                    timeout=5000)
    assert win.project.entries()[-1][0] == "Colour Tint"
    assert win._tint_pending is None
