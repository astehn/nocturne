"""Picking sets the slider and leaves the step PENDING — it never commits.

Both halves matter. Setting the slider without the pending state would lose the
choice silently on Next, which is exactly the class of bug the step-commit model
was built to remove.
"""
import numpy as np

from tests.ui.test_main_window import _make_fits, _window


def _at_stretch(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    return win


def test_the_panel_offers_the_picker(qtbot, tmp_path):
    win = _at_stretch(qtbot, tmp_path)
    assert hasattr(win._panel, "visual_btn")
    assert win._panel.visual_btn.isEnabled()


def test_picking_sets_the_slider_and_reads_as_pending(qtbot, tmp_path):
    from nocturne.ui.stretch_picker import STRETCH_PICKS
    win = _at_stretch(qtbot, tmp_path)
    before = [n for n, _ in win.project.entries()]

    win._apply_picked_stretch({"amount": STRETCH_PICKS[1][1]})

    assert win._panel.stretch_slider.value() == round(STRETCH_PICKS[1][1] * 100)
    assert win._has_pending(), "the choice must be visible as unapplied work"
    assert [n for n, _ in win.project.entries()] == before, "it must NOT commit"


def test_cancelling_changes_nothing(qtbot, tmp_path):
    """Asserted as UNCHANGED, not as 'no new entry' — a cancel that moved the
    slider to a different wrong value would pass the weaker form."""
    win = _at_stretch(qtbot, tmp_path)
    slider = win._panel.stretch_slider.value()
    entries = list(win.project.entries())
    pixels = win.project.current().data.copy()

    win._apply_picked_stretch(None)          # what a cancelled dialog returns

    assert win._panel.stretch_slider.value() == slider
    assert list(win.project.entries()) == entries
    assert np.array_equal(win.project.current().data, pixels)
    assert not win._has_pending()


def test_the_picker_is_offered_only_while_there_is_something_to_stretch(qtbot, tmp_path):
    """Once applied, the data is no longer linear and the step's own preview is
    skipped; offering a picker that would re-stretch it is a trap."""
    win = _at_stretch(qtbot, tmp_path)
    win.apply_current(0.30)
    win._go_to_id("stretch")
    assert not win._panel.visual_btn.isEnabled()
