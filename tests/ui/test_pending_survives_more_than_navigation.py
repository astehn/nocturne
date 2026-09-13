"""A pending preview is guarded when the WORKSPACE goes, not only on navigation.

The last silent-loss hole left by the step-commit branch. Navigation asked
before abandoning an unapplied change; opening another image, opening a
project, closing one, or quitting took it without a word — because
`_confirm_save_if_dirty` gates on `_dirty`, which tracks COMMITS, and a preview
has not been committed.

It is deliberately the same dialog as navigation uses. It is the same question
from the user's side ("you have an unapplied change — what now?") and answering
it differently depending on which way you leave the step would be a distinction
only the code can see.
"""
from __future__ import annotations

import numpy as np
import pytest

from tests.ui.test_main_window import _window, _make_fits


def _win_with_pending(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win._on_stretch_change(0.8)          # a live preview, never applied
    assert win._has_pending()
    assert not win._dirty, "the point of this test is a pending change with NO commit"
    return win


def test_a_pending_preview_is_asked_about_even_when_nothing_is_dirty(qtbot, tmp_path):
    win = _win_with_pending(qtbot, tmp_path)
    asked = []
    win._ask_pending = lambda label: (asked.append(label), "discard")[1]
    assert win._confirm_save_if_dirty() is True
    assert asked == ["Stretch"], asked


def test_cancel_stops_the_action(qtbot, tmp_path):
    win = _win_with_pending(qtbot, tmp_path)
    win._ask_pending = lambda label: "cancel"
    assert win._confirm_save_if_dirty() is False


def test_apply_commits_it_before_the_workspace_goes(qtbot, tmp_path):
    win = _win_with_pending(qtbot, tmp_path)
    win._ask_pending = lambda label: "apply"
    assert win._confirm_save_if_dirty() is True
    assert [n for n, _ in win.project.entries()] == ["Stretch"]
    assert not win._has_pending()


def test_pending_is_asked_BEFORE_save(qtbot, tmp_path):
    """Order matters, and this is why: saving writes a bundle that does not
    contain the preview. Asking "save?" first invites someone to save and lose
    the change anyway."""
    win = _win_with_pending(qtbot, tmp_path)
    win._mark_dirty()                      # now BOTH prompts apply
    order = []
    win._ask_pending = lambda label: (order.append("pending"), "discard")[1]

    from PySide6.QtWidgets import QMessageBox
    import unittest.mock as mock
    with mock.patch.object(
            QMessageBox, "question",
            lambda *a, **k: (order.append("save"),
                             QMessageBox.StandardButton.Discard)[1]):
        assert win._confirm_save_if_dirty() is True
    assert order == ["pending", "save"], order


def test_no_prompt_when_there_is_no_pending_change(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._ask_pending = lambda label: pytest.fail("asked with nothing pending")
    assert win._confirm_save_if_dirty() is True


def test_open_fits_routes_through_the_guard(qtbot, tmp_path):
    """The guard is only worth anything if the workspace-replacing actions
    actually consult it. Proven through the real entry point rather than by
    calling the guard directly."""
    win = _win_with_pending(qtbot, tmp_path)
    before = win.project.current().data.copy()
    win._ask_pending = lambda label: "cancel"

    # A second file, written beside the first — _make_fits always uses the same
    # name, and reopening the SAME path would not prove the guard ran.
    second = tmp_path / "second"
    second.mkdir()
    win.open_fits(_make_fits(second))

    assert np.array_equal(win.project.current().data, before), (
        "the cancelled open replaced the workspace anyway")
    assert win._has_pending(), "and it took the pending change with it"
