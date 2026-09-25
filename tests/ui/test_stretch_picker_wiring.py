"""Picking sets the slider and leaves the step PENDING — it never commits.

Both halves matter. Setting the slider without the pending state would lose the
choice silently on Next, which is exactly the class of bug the step-commit model
was built to remove.
"""
import numpy as np

from tests.ui.test_main_window import _make_fits, _window


def _log_text(win):
    entries = win.log_panel.entries() if hasattr(win.log_panel, "entries") else None
    return "\n".join(entries) if entries else win.log_panel.toPlainText()


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


# --- the colour pick, end to end -----------------------------------------

def test_the_picker_asks_colour_first(qtbot, tmp_path):
    """Import sets the DEFAULT. A view that disagreed with the commitment would
    make the first picture Nocturne shows one it cannot produce."""
    win = _at_stretch(qtbot, tmp_path)
    assert [p.key for p in win._stretch_picks()] == ["linked", "amount"]


def test_picking_sets_both_the_slider_and_the_mechanism(qtbot, tmp_path):
    win = _at_stretch(qtbot, tmp_path)
    win._apply_picked_stretch({"amount": 0.24, "linked": False})
    assert win._panel.stretch_slider.value() == 24
    assert win._panel.stretch_linked is False


def test_picking_linked_brings_the_colour_step_back(qtbot, tmp_path):
    """Option A, decided 2026-09-14. Import sets a default, not a lock: someone
    who skipped Colour and then chose Linked must not silently commit a linked
    stretch having never been offered the calibration it is the only one to
    preserve."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._set_view_linked(False)
    assert not next(s for s in win._stages if s.id == "color").enabled
    win._go_to_id("stretch")

    win._apply_picked_stretch({"amount": 0.24, "linked": True})

    assert next(s for s in win._stages if s.id == "color").enabled
    assert "colour" in _log_text(win).lower() or "color" in _log_text(win).lower()
    assert win.current_stage_id() == "stretch"      # and we did NOT get moved


def test_picking_unlinked_again_leaves_the_path_UNCHANGED(qtbot, tmp_path):
    """Captured and asserted unchanged: re-enabling on the wrong branch would
    put back a step that still does nothing."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._set_view_linked(False)
    before = list(win._stages)
    win._go_to_id("stretch")
    win._apply_picked_stretch({"amount": 0.24, "linked": False})
    assert list(win._stages) == before
