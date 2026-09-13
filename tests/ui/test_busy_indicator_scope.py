"""Where an operation reports depends on whether the user asked for it.

Andreas's rule, 2026-09-13, after noticing two indicators doing the same job:

    work about to change the image, user-triggered  ->  bar over the image
    step-entry preparation (splits, masks)          ->  right panel only
    a modal tool doing its own work                 ->  inside that modal

His words for the middle row: "In process steps when moving between steps and
the application is separating stars for example I dont think that we need to
show indicator 1." The third row was settled separately and needs no code — the
two modal dialogs already report inside themselves.

The busy CURSOR is deliberately in BOTH of the first two. It is not "over the
image": it is what tells you the click you just made is being ignored, and an
app that silently swallows input reads as broken rather than busy.
"""
from __future__ import annotations

import pytest

from tests.ui.test_main_window import _window, _make_fits


def _win(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    return win


def _show_now(win):
    """Skip BUSY_DELAY_MS — the visuals are timer-driven and this is about
    WHICH ones appear, not when."""
    win._show_busy_visuals()


def _shown(widget) -> bool:
    """`isHidden()`, not `isVisible()`. The suite never shows the top-level
    window, and a child of a hidden parent reports isVisible() False however it
    was set — which would make every assertion here pass for the wrong reason.
    isHidden() reflects the explicit show/hide call, which is what is under
    test."""
    return not widget.isHidden()


def test_the_visuals_honour_the_flag(qtbot, tmp_path):
    """The rule, at the moment it is applied. `_show_busy_visuals` is what
    actually decides, and it fires on a timer — so it is driven directly rather
    than through an operation that has already finished by then (under the
    tests' synchronous `_async_enabled = False`, it has)."""
    win = _win(qtbot, tmp_path)

    win._busy_over_image = True
    win._busy_label_text = "Working…"
    win._show_busy_visuals()
    assert _shown(win._busy_bar), "an image-changing op should show on the image"
    win._hide_busy_visuals()

    win._busy_over_image = False
    win._busy_label_text = "Separating stars…"
    win._show_busy_visuals()
    assert not _shown(win._busy_bar), "the bar should stay off the picture"
    # ...and the panel still carries the whole report.
    assert _shown(win._cancel_btn)
    assert _shown(win._elapsed_label)
    assert "Separating stars" in win._busy_label.text()
    assert win._cursor_active is True, (
        "the busy cursor belongs to BOTH forms — it is what says the click you "
        "just made is being ignored")
    win._hide_busy_visuals()


def test_run_busy_sets_the_flag_for_the_duration(qtbot, tmp_path):
    """Checked INSIDE the work, because `_hide_busy_visuals` resets it the
    moment the operation ends."""
    win = _win(qtbot, tmp_path)
    seen = {}
    win._run_busy(lambda: seen.setdefault("quiet", win._busy_over_image),
                  lambda _r: None, "Separating stars…", "failed",
                  over_image=False)
    assert seen["quiet"] is False

    win._run_busy(lambda: seen.setdefault("loud", win._busy_over_image),
                  lambda _r: None, "Working…", "failed")
    assert seen["loud"] is True


def test_the_setting_does_not_leak_into_the_next_operation(qtbot, tmp_path):
    """A quiet op must reset it, or the first step-entry split of a session
    silently turns the bar off for every Apply after it."""
    win = _win(qtbot, tmp_path)
    win._run_busy(lambda: None, lambda _r: None, "Separating stars…", "failed",
                  over_image=False)
    assert win._busy_over_image is True, "not reset when the operation ended"

    win._busy_label_text = "Working…"
    win._show_busy_visuals()
    assert _shown(win._busy_bar)
    win._hide_busy_visuals()


@pytest.mark.parametrize("stage_id", ["saturation", "star_reduction", "green_fringe"])
def test_the_three_step_entry_splits_ask_for_the_quiet_form(qtbot, tmp_path,
                                                            monkeypatch, stage_id):
    """Through the real navigation, so the wiring is what is tested and not a
    restatement of the flag."""
    win = _win(qtbot, tmp_path)
    seen = []
    real = win._run_busy

    def spy(work, on_result, label, err_prefix, *, over_image=True):
        seen.append((label, over_image))
        return real(work, on_result, label, err_prefix, over_image=over_image)

    monkeypatch.setattr(win, "_run_busy", spy)
    win._go_to_id(stage_id)
    if stage_id == "saturation":
        win._on_sat_change(0.5, 0.4)        # the nebula split is lazy

    assert seen, f"{stage_id} ran no background work to check"
    assert all(over is False for _label, over in seen), seen
