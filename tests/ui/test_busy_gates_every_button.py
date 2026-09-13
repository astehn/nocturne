"""Every button on the step panel is disabled while an operation runs.

`_set_busy` used to name the buttons it knew about — apply_btn, later also
reset_step_btn — so each new control was a fresh chance to forget one. FOUR
separate findings on the step-commit branch were exactly that omission: the
background-stack button, Colour's tint and remove-green buttons, Reset step,
and Apply/Reset after a stepper navigation rebuilt the panel.

Enumerating exceptions is a list that goes stale. Sweeping the panel is a rule
that cannot, and that is what this pins — across EVERY stage, so a stage added
later is covered by a test nobody has to remember to update.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QPushButton

from tests.ui.test_main_window import _window, _make_fits
from nocturne.ui.pipeline import path_stages


def _win(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    return win


@pytest.mark.parametrize("stage_id", [s.id for s in path_stages()])
def test_no_panel_button_stays_live_while_busy(qtbot, tmp_path, stage_id):
    win = _win(qtbot, tmp_path)
    if not win._stages[[s.id for s in win._stages].index(stage_id)].enabled:
        pytest.skip(f"{stage_id} is not enabled in this build")
    win._go_to_id(stage_id)

    live_before = [b for b in win._panel.findChildren(QPushButton) if b.isEnabled()]
    win._set_busy(True, "Working…")
    still_live = [b.text() for b in win._panel.findChildren(QPushButton) if b.isEnabled()]
    assert not still_live, f"{stage_id}: {still_live} stayed clickable during an operation"

    win._set_busy(False)
    back = [b for b in win._panel.findChildren(QPushButton) if b.isEnabled()]
    assert set(map(id, back)) >= set(map(id, live_before)), (
        f"{stage_id}: buttons that were enabled before the operation did not "
        "come back")


def test_a_button_that_was_already_disabled_does_not_come_back_on(qtbot, tmp_path):
    """The reason only previously-enabled buttons are restored. Apply is off
    on Background without GraXpert; an unrelated operation finishing must not
    switch it on."""
    win = _win(qtbot, tmp_path)
    win._go_to_id("background")
    win._panel.apply_btn.setEnabled(False)

    win._set_busy(True, "Working…")
    win._set_busy(False)

    assert win._panel.apply_btn.isEnabled() is False


def test_a_panel_rebuilt_mid_operation_leaves_the_old_one_alone(qtbot, tmp_path):
    """Navigating during a busy op replaces the panel, and the buttons this
    captured belong to the panel that is now gone. Writing `setEnabled(True)`
    back onto them is at best pointless and at worst a use-after-free — the
    C++ objects may already be deleted.

    Asserted as UNCHANGED on the old panel, and separately that the NEW panel
    is left usable, because "nothing crashed" would pass either way.
    """
    win = _win(qtbot, tmp_path)
    win._go_to_id("stretch")
    old_panel = win._panel
    old_buttons = list(old_panel.findChildren(QPushButton))
    assert old_buttons, "fixture has no buttons; it proves nothing"

    win._set_busy(True, "Working…")
    assert not any(b.isEnabled() for b in old_buttons)

    win._rebuild_panel()                       # as a navigation would
    new_panel = win._panel
    assert new_panel is not old_panel
    win._set_busy(False)

    assert not any(b.isEnabled() for b in old_buttons), (
        "the finished operation reached back into the discarded panel")
    assert win._panel.apply_btn.isEnabled(), (
        "and the panel actually on screen was left unusable")


def test_the_stepper_is_gated_too(qtbot, tmp_path):
    """Back/Next are not panel children, so the sweep cannot reach them — they
    are still named explicitly and must stay that way."""
    win = _win(qtbot, tmp_path)
    win._set_busy(True, "Working…")
    assert not win._back_btn.isEnabled()
    assert not win._next_btn.isEnabled()
    win._set_busy(False)
