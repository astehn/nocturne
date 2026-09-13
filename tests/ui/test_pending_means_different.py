"""Pending means "differs from the commit", not "a slot is set".

The spec's definition is "describes something the committed image does not
reflect". The code's was "the slot is non-None", so nudging a slider away and
back left the step prompting about a preview that IS the commit. Recorded as a
deliberate deferral on the step-commit branch; this closes it.

The asymmetry matters and is encoded below: a needless prompt is a nuisance, a
missed one is lost work. So only a confident match clears pending, and every
shape this cannot compare stays pending.
"""
from __future__ import annotations

import pytest

from tests.ui.test_main_window import _window, _make_fits
from nocturne.ui.main_window import _same_option


def _stretched(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    return win


def test_nudging_a_slider_back_to_the_committed_value_clears_pending(qtbot, tmp_path):
    win = _stretched(qtbot, tmp_path)
    win.apply_current(0.5)
    assert not win._has_pending()

    win._on_stretch_change(0.8)
    assert win._has_pending(), "moving away must be pending"

    win._on_stretch_change(0.5)             # ...and back to what was committed
    assert not win._has_pending(), (
        "the preview now IS the commit; there is nothing to decide about")


def test_a_value_that_differs_is_still_pending(qtbot, tmp_path):
    """The other half. A guard that cleared pending too eagerly would lose
    work, so prove the ordinary case still holds."""
    win = _stretched(qtbot, tmp_path)
    win.apply_current(0.5)
    win._on_stretch_change(0.5001)
    assert win._has_pending()


def test_a_never_applied_step_back_at_its_starting_value_is_not_pending(qtbot, tmp_path):
    """CORRECTED 2026-09-13. This test previously asserted the opposite, on the
    reasoning that with no commit to compare against there is no match — "not a
    free pass". That is true of a value which might be work and false of one
    that is provably where the user found it, and Andreas hit the consequence
    on nine steps: nudge a slider, put it back, and Apply stays green while Next
    demands a choice between Cancel and Discard over nothing.

    The panel's `neutral_option` is what it reads untouched, so this is now
    answerable without a commit."""
    win = _stretched(qtbot, tmp_path)
    start = win._panel.neutral_option
    win._on_stretch_change(0.8)
    assert win._has_pending(), "moved away: pending"
    win._on_stretch_change(start)
    assert not win._has_pending(), "back where it started: nothing to apply"


@pytest.mark.parametrize("a,b,expect", [
    (0.5, 0.5, True),
    (0.5, 0.5000000001, True),          # float noise, far inside a slider tick
    (0.5, 0.51, False),                 # one tick apart
    ("auto", "auto", True),
    ("auto", 0.5, False),               # Levels records a STRING for derived values
    (0.5, "auto", False),
    ((0.05, 1.0, 1.0), (0.05, 1.0, 1.0), True),
    ((0.05, 1.0, 1.0), [0.05, 1.0, 1.0], True),
    ((0.05, 1.0, 1.0), (0.06, 1.0, 1.0), False),
    ((0.05, 1.0), (0.05, 1.0, 1.0), False),
    ({"engine": "rcastro"}, {"engine": "rcastro"}, True),
    (None, 0.5, False),
])
def test_option_comparison(a, b, expect):
    assert _same_option(a, b) is expect


def test_an_uncomparable_option_stays_pending():
    """Never raise, and never clear on something not understood."""
    class Awkward:
        def __eq__(self, other):
            raise RuntimeError("no")

    assert _same_option(Awkward(), Awkward()) is False
