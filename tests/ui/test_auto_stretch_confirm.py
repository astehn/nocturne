"""Navigating to a post-stretch step on a linear image asks before it truncates.

The seventh unguarded truncation, and the only one reached by merely NAVIGATING
rather than pressing anything. `_go_to` commits a Stretch on the user's behalf
when a post-stretch step is opened on still-linear data, and that jump_back
keeps only the pre-stretch pipeline steps.

It is gated on `is_linear`, so no pipeline STEP can be lost — everything before
Stretch is in the keep set. A TOOLBAR commit made while linear is not: run
Narrowband on a linear image, click Levels, and the combine was gone with
nothing said.
"""
from __future__ import annotations

import numpy as np

from tests.ui.test_main_window import _window, _make_fits


def _linear_win_with_toolbar_work(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._enhance("Boost Blue")            # a toolbar commit, made while linear
    assert win.project.current().is_linear
    assert [n for n, _ in win.project.entries()] == ["Boost Blue"]
    return win


def test_it_asks_and_names_the_work_and_the_destination(qtbot, tmp_path):
    win = _linear_win_with_toolbar_work(qtbot, tmp_path)
    asked = []
    win._ask_auto_stretch = lambda names, dest: (asked.append((names, dest)), True)[1]
    win._go_to_id("levels")
    assert asked == [(["Boost Blue"], "Levels")], asked


def test_cancelling_keeps_the_work_AND_stays_on_the_step(qtbot, tmp_path):
    """Assert every part unchanged. A cancel that only skipped the stretch
    would still have navigated, leaving the user on a step whose data is
    linear — which is the state the auto-stretch exists to prevent."""
    win = _linear_win_with_toolbar_work(qtbot, tmp_path)
    stage_before = win.current_stage_id()
    entries_before = list(win.project.entries())
    pixels_before = win.project.current().data.copy()
    win._ask_auto_stretch = lambda names, dest: False

    win._go_to_id("levels")

    assert win.current_stage_id() == stage_before
    assert list(win.project.entries()) == entries_before
    assert np.array_equal(win.project.current().data, pixels_before)
    assert win.project.current().is_linear


def test_no_prompt_when_there_is_nothing_to_lose(qtbot, tmp_path):
    """The ordinary case — walking into Levels on a linear image with only
    pipeline steps behind you. Those are all in the keep set, so nothing is at
    risk and asking would be noise."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    asked = []
    win._ask_auto_stretch = lambda names, dest: (asked.append(names), True)[1]
    win._go_to_id("levels")
    assert not asked
    assert [n for n, _ in win.project.entries()] == ["Stretch"]
    assert not win.project.current().is_linear


def test_pre_stretch_pipeline_steps_are_never_named(qtbot, tmp_path):
    """Background/Colour/etc. are KEPT by `_leading_kept`, so they must not be
    listed as casualties — they are not lost."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("background")
    # Through the box, the way the Apply button does it — applying an option the
    # dropdown is not showing leaves the panel legitimately reading "pending".
    win._panel.option_box.setCurrentText("off")
    win.apply_current("off")          # a pre-stretch pipeline decision
    win._enhance("Boost Blue")
    asked = []
    win._ask_auto_stretch = lambda names, dest: (asked.append(names), True)[1]
    win._go_to_id("levels")
    assert asked, "the enhancement is at risk and should have been named"
    assert asked[0] == ["Boost Blue"], asked


def test_the_message_names_the_step_the_user_actually_clicked(qtbot, tmp_path):
    """The user did not ask to stretch — they clicked a step. The message has
    to lead with that, or it reads as the app doing something unprompted."""
    win = _linear_win_with_toolbar_work(qtbot, tmp_path)
    seen = {}
    win._confirm_destructive = lambda headline, detail, verb: (
        seen.update(headline=headline, detail=detail, verb=verb), True)[1]

    win._real_ask_auto_stretch(["Boost Blue"], "Levels")

    assert seen["headline"] == "Levels needs a stretched image."
    assert "Boost Blue" in seen["detail"]
    assert seen["verb"] == "Stretch"
