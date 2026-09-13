"""Rotate and Flip discard ALL processing, so they ask first.

`_apply_geometry` was the one truncating path with no confirm. It jumps back to
the leading geometry steps, which throws away every processing step on the
image — more than any other path discards — and it did so on a single toolbar
click with no way back (jump_back deletes the paths; there is no redo).

Left out of the step-commit-model branch on purpose: it wants a differently
worded message than the "applied after it" one, because here there is no
"after" — re-framing invalidates the processing whenever it was applied. The
reviewer's caveat then was fair and is the reason this exists: users will have
learned the app asks, so one silent exception is worse than none.
"""
from __future__ import annotations

import pytest

from nocturne.core.crop import CropParams
from tests.ui.test_main_window import _window, _make_fits


def _win_with_processing(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    assert [n for n, _ in win.project.entries()] == ["Stretch"]
    return win


@pytest.mark.parametrize("action,label", [
    ("_rotate", "Rotate 90°"),
    ("_flip_h", "Flip horizontally"),
    ("_flip_v", "Flip vertically"),
])
def test_geometry_asks_before_discarding_processing(qtbot, tmp_path, action, label):
    win = _win_with_processing(qtbot, tmp_path)
    asked = []
    win._ask_geometry = lambda names, lbl: (asked.append((names, lbl)), True)[1]
    getattr(win, action)()
    assert asked, f"{action} discarded Stretch without asking"
    names, shown = asked[0]
    assert names == ["Stretch"], names
    assert shown == label, "the dialog should speak the user's words, not the history key"


@pytest.mark.parametrize("action", ["_rotate", "_flip_h", "_flip_v"])
def test_cancelling_changes_nothing_at_all(qtbot, tmp_path, action):
    """Assert UNCHANGED, not 'no new entry'. A cancel that still ran jump_back
    would leave the history right and the PIXELS wrong."""
    win = _win_with_processing(qtbot, tmp_path)
    before_entries = list(win.project.entries())
    before_pixels = win.project.current().data.copy()
    win._ask_geometry = lambda names, label: False

    getattr(win, action)()

    assert list(win.project.entries()) == before_entries
    import numpy as np
    assert np.array_equal(win.project.current().data, before_pixels)


def test_no_prompt_when_there_is_nothing_to_lose(qtbot, tmp_path):
    """The common case — rotate a freshly opened image. A confirm that fires
    when nothing is at risk trains people to dismiss it unread."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    asked = []
    win._ask_geometry = lambda names, label: (asked.append(names), True)[1]
    win._rotate()
    assert not asked
    assert [n for n, _ in win.project.entries()] == ["Rotate"]


def test_earlier_geometry_is_not_a_casualty(qtbot, tmp_path):
    """Crop/Rotate/Flip are KEPT by `_leading_kept`, so they must never be
    named as about to be discarded — they are not."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._apply_geometry("Crop", CropParams(bounds=(4, 20, 4, 20)))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    asked = []
    win._ask_geometry = lambda names, label: (asked.append(names), True)[1]
    win._rotate()
    assert asked and asked[0] == ["Stretch"], asked


def test_the_confirm_defaults_to_cancel(qtbot, tmp_path):
    """The shared destructive dialog, exercised for real rather than stubbed.

    `buttons()` returns LAYOUT order, not insertion order, so taking the
    default from `buttons()[-1]` once handed it to the DESTRUCTIVE button and
    Return irreversibly discarded work. That defect reached review because no
    test ever executed the dialog's body. This one does.
    """
    from PySide6.QtWidgets import QMessageBox
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))

    seen = {}

    def capture(self):
        seen["default"] = self.defaultButton().text()
        seen["texts"] = [b.text() for b in self.buttons()]
        return 0

    import unittest.mock as mock
    with mock.patch.object(QMessageBox, "exec", capture):
        win._confirm_destructive("Rotate 90°?", "This discards Stretch.", "Rotate 90°")

    assert seen["default"] == "Cancel", (
        f"the default must be the safe button; buttons were {seen['texts']}")


def test_the_message_explains_why_everything_goes(qtbot, tmp_path):
    """The substance of having a separate message at all.

    `_ask_truncation` says "applied after it", which is about work that came
    later than the step being re-applied. Here there is no "after": re-framing
    invalidates every processing step whenever it was applied. If this message
    ever collapses back into the truncation wording, the user is told something
    that is not true of this action.
    """
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    seen = {}
    win._confirm_destructive = lambda headline, detail, verb: (
        seen.update(headline=headline, detail=detail, verb=verb), True)[1]

    # `_real_ask_geometry` is the unstubbed one, stashed by the conftest guard
    # that otherwise refuses a live prompt — this test wants the real message.
    win._real_ask_geometry(["Stretch", "Levels"], "Rotate 90°")

    assert seen["headline"] == "Rotate 90°?"
    assert "Stretch and Levels" in seen["detail"], seen["detail"]
    assert "re-frames" in seen["detail"], (
        "the message must say WHY the processing goes, not just that it does")
    assert "applied after it" not in seen["detail"], (
        "that is the truncation wording and it is not true of a re-frame")
