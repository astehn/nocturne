"""While a step is running, nothing may rewrite the history under it.

Found 2026-09-25 by a probe during the consistent-panels review: Undo, Redo and
the toolbar Reset were the only history-changing actions with no busy check.
Undoing a Crop while Colour calibrated left the history reading ['Color'] with
the crop still baked into the pixels — provenance and replay would then lie.
Every other tool (Trim, Colour Balance, Auto Enhance…) already refuses."""
import numpy as np
import pytest
from PySide6.QtWidgets import QMessageBox

from tests.ui.test_consistent_panels import _stretched


def _snapshot(win):
    return [n for n, _ in win.project.entries()], win.project.current().data.copy()


@pytest.mark.parametrize("action", ["undo", "redo", "reset"])
def test_history_actions_do_nothing_while_busy(qtbot, tmp_path, monkeypatch, action):
    win = _stretched(qtbot, tmp_path)
    if action == "redo":
        win._undo(); qtbot.wait(20)
        assert win.project.can_redo(), "precondition: something to redo"
    else:
        assert win.project.can_undo(), "precondition: something to undo"
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    names, data = _snapshot(win)
    win._set_busy(True, "probe")
    {"undo": win._undo, "redo": win._redo, "reset": win._reset_image}[action]()
    after_names, after_data = _snapshot(win)
    assert after_names == names
    assert np.array_equal(after_data, data)
    win._set_busy(False)


def test_history_actions_are_off_while_busy_and_back_after(qtbot, tmp_path):
    win = _stretched(qtbot, tmp_path)
    win._undo(); qtbot.wait(20)            # leaves both an undo and a redo
    win._go_to_id("stretch", user_initiated=False)
    win._panel.apply_btn.click(); qtbot.wait(50)
    win._undo(); qtbot.wait(20)
    assert win._undo_act.isEnabled() or win._redo_act.isEnabled()
    before = (win._undo_act.isEnabled(), win._redo_act.isEnabled(), win._reset_act.isEnabled())
    win._set_busy(True, "probe")
    win._refresh()                          # a refresh mid-run must not switch them back on
    assert not win._undo_act.isEnabled()
    assert not win._redo_act.isEnabled()
    assert not win._reset_act.isEnabled()
    win._set_busy(False)
    assert (win._undo_act.isEnabled(), win._redo_act.isEnabled(), win._reset_act.isEnabled()) == before


def test_leaving_colour_while_it_calibrates_lands_cleanly(qtbot, tmp_path, monkeypatch):
    """The stepper stays usable during a run, so the user can leave Colour while
    its calibration is on the worker. When it landed, the result handler
    re-baselined the dropdown of the panel it captured at the press — already
    deleted — and raised "QComboBox already deleted", skipping the refresh and
    the activity line. The commit itself must land, and quietly."""
    import threading
    from nocturne.steps.color import ColorStep
    from tests.ui.test_step_commit_async import _async_win, _idle, _names

    release = threading.Event()
    real = ColorStep.apply

    def held(self, img, option):
        release.wait(10)
        return real(self, img, option)

    monkeypatch.setattr(ColorStep, "apply", held)
    win = _async_win(qtbot, tmp_path)
    win._panel.apply_btn.click()
    qtbot.waitUntil(lambda: win._busy, timeout=2000)
    win._go_to_id("stretch", user_initiated=True)      # leave while it runs
    qtbot.wait(50)
    lines_before = len(win.activity.entries("step"))
    release.set()
    _idle(qtbot, win)
    assert _names(win) == ["Color"]
    assert len(win.activity.entries("step")) == lines_before + 1, "the Color line was skipped"
    assert win.current_stage_id() == "stretch"
