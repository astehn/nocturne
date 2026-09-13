"""Every live-preview panel knows what its controls read UNTOUCHED.

Andreas, 2026-09-13, on nine steps at once: "the user might want to move the
slider but then decides that they dont want what it does so they move the
slider back to its default position and then the apply button stays green" —
and Next then demanded a choice between Cancel and Discard over a change that
did not exist.

`neutral_option` is the value the panel would emit before anything is touched.
It sits beside the emit it must match, and this file is what stops the two
drifting: a panel whose emit changes but whose neutral does not is exactly the
bug coming back, and it would be invisible without a test that fires both.
"""
from __future__ import annotations

import pytest

from nocturne.ui.step_panels import build_panel
from nocturne.ui.pipeline import Stage

# stage kind -> (stage id, the on_*_change kwarg that panel emits through)
_LIVE_PREVIEW = [
    # Colour's panel KIND is "auto", not "color" — the stage id and the
    # panel kind are different vocabularies here.
    ("auto", "color", "on_tint_change"),
    ("stretch", "stretch", "on_stretch_change"),
    ("remove_green", "remove_green", "on_removegreen_change"),
    ("levels", "levels", "on_levels_change"),
    ("saturation", "saturation", "on_sat_change"),
    ("recover_core", "recover_core", "on_recover_change"),
    ("local_contrast", "local_contrast", "on_lc_change"),
    ("star_reduction", "star_reduction", "on_sr_change"),
]


def _stage(kind, sid):
    return Stage(sid, sid.replace("_", " ").title(), kind)


@pytest.mark.parametrize("kind,sid,hook", _LIVE_PREVIEW)
def test_every_live_preview_panel_declares_its_neutral(qtbot, kind, sid, hook):
    w = build_panel(_stage(kind, sid))
    qtbot.addWidget(w)
    assert hasattr(w, "neutral_option"), (
        f"{kind} has a live preview but no neutral_option, so putting its "
        "controls back where they started will not clear pending")


@pytest.mark.parametrize("kind,sid,hook", _LIVE_PREVIEW)
def test_neutral_option_matches_the_emit(qtbot, kind, sid, hook):
    """THE guard. Builds the panel, fires its change handler without touching
    anything, and requires the emitted value to equal the declared neutral.

    Two expressions describing one thing is how they drift — the same shape as
    the integration-time formatting that disagreed with itself, and the
    lightness_preserve drift narrowband_dialog carries a comment about."""
    from nocturne.ui.main_window import _same_option

    seen = []
    kwargs = {hook: lambda *a: seen.append(a[0] if len(a) == 1 else tuple(a))}
    w = build_panel(_stage(kind, sid), **kwargs)
    qtbot.addWidget(w)

    # Nudge a slider and put it straight back: the second emit carries exactly
    # the untouched reading, without depending on a build-time signal firing.
    sliders = _sliders(w, kind)
    assert sliders, f"{kind}: no slider found to drive"
    s = sliders[0]
    start = s.value()
    s.setValue(start + 1 if start < s.maximum() else start - 1)
    s.setValue(start)
    assert seen, f"{kind}: the panel emitted nothing"

    assert _same_option(w.neutral_option, seen[-1]), (
        f"{kind}: neutral_option is {w.neutral_option!r} but the untouched "
        f"controls emit {seen[-1]!r} — the two have drifted")


def _sliders(w, kind):
    from PySide6.QtWidgets import QSlider
    return [s for s in w.findChildren(QSlider)]


def test_the_guard_can_fail(qtbot):
    """Proves the comparison is real: a deliberately wrong neutral is caught."""
    from nocturne.ui.main_window import _same_option
    w = build_panel(_stage("stretch", "stretch"))
    qtbot.addWidget(w)
    assert not _same_option(w.neutral_option + 0.25, w.neutral_option)
