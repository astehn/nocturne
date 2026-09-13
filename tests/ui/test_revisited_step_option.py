"""A revisited process step must report the option the image actually carries.

Found 2026-09-11 by the step-commit-model review, which hit it as a false
"pending": the dropdown disagreed with the history for a step nobody had
touched. Deliberately not fixed there — seeding from the committed option
changes behaviour and deserved its own task rather than riding inside a
signalling change.

The bug: `_rebuild_panel` seeded every process stage's dropdown from
`default_option()`, never from what was committed. Apply Deconvolution at
"strong", navigate away, come back, and the box reads "medium" over an image
with "strong" baked in.
"""
from __future__ import annotations

import pytest

from tests.ui.test_main_window import _window, _make_fits


def _win(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    return win


@pytest.mark.parametrize("stage,applied", [
    ("deconvolution", "strong"),
    ("noise_sharpen", "light"),
])
def test_a_revisited_step_shows_what_was_committed(qtbot, tmp_path, stage, applied):
    win = _win(qtbot, tmp_path)
    win._go_to_id(stage)
    win._panel.option_box.setCurrentText(applied)
    win.apply_current(applied)

    win._go_to_id("levels")                      # away...
    win._go_to_id(stage)                         # ...and back
    assert win._panel.option_box.currentText() == applied, (
        "the dropdown reports a different option than the image carries")


def test_and_therefore_does_not_read_as_pending_on_arrival(qtbot, tmp_path):
    """The symptom that found the bug. A step nobody has touched since
    committing it has nothing to commit, so it must not prompt."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("deconvolution")
    win._panel.option_box.setCurrentText("strong")
    win.apply_current("strong")
    win._go_to_id("levels")
    win._go_to_id("deconvolution")
    assert win._has_pending() is False


def test_a_never_applied_step_still_offers_its_own_default(qtbot, tmp_path):
    """The fallback has to survive. Seeding from history alone would leave a
    fresh image with no suggested setting at all."""
    win = _win(qtbot, tmp_path)
    for stage, default in (("deconvolution", "medium"), ("noise_sharpen", "medium"),
                           ("background", "strong")):
        win._go_to_id(stage)
        assert win._panel.option_box.currentText() == default, stage


def test_background_off_is_the_documented_exception(qtbot, tmp_path):
    """Pins the residue rather than pretending it is fixed.

    "off" records no history entry (apply_current early-returns), so on a
    rebuild it is indistinguishable from never-applied and the box goes back to
    the step's default. Reading "no entry" as "off" would be right for this one
    user and wrong for every freshly-opened image, and would switch off the
    green that tells a novice the step wants pressing.
    """
    win = _win(qtbot, tmp_path)
    win._go_to_id("background")
    win._panel.option_box.setCurrentText("off")
    win.apply_current("off")
    assert win._panel.option_baseline == "off"       # while the panel lives
    win._go_to_id("levels")
    win._go_to_id("background")
    assert win._panel.option_box.currentText() == "strong", (
        "if this ever reads 'off', the exception was fixed — update the "
        "docstring on _process_option_default and delete this test")


def test_an_option_the_step_cannot_represent_is_ignored(qtbot, tmp_path):
    """A recorded value outside the dropdown's own list must not put the box
    into a state it has no entry for — fall back to the default instead."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("deconvolution")
    win.apply_current("strong")
    # Rewrite history with something no dropdown offers.
    entries = win.project.entries()
    assert entries[-1][0] == "Deconvolution"
    idx = win.project._position - 1
    name = win.project._records[idx][0]
    win.project._records[idx] = (name, "ludicrous")
    assert win._process_option_default("deconvolution") == "medium"
