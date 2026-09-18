"""A tool that can separate stars two different ways has to say which it used.

De-green Stars got this on 2026-09-12, after telling its two paths apart took
four rounds of measurement on a real master — they behave differently enough
that "which one ran" is part of reading the result, not a detail. The same
silent choice was left in the other tools that go through the split.

Scope correction, 2026-09-13: TODO listed FIVE tools. Two of them do not
belong — Narrowband and Colour Balance do not choose, they GATE on StarX and
say so in their own status line when it is missing (`narrowband_dialog`
showEvent, `color_balance_dialog`). The three that genuinely chose in silence
are Saturation's nebula boost, Star Reduction, and Starless Levels.
"""
from __future__ import annotations

import numpy as np
import pytest

from nocturne.core.image import AstroImage


def _split_free(win, base):
    from nocturne.core.starless import split_stars
    return split_stars(base)


def test_split_tagged_names_the_engine_it_actually_used(qtbot, tmp_path, monkeypatch):
    """The tag is produced WHERE the choice is made, not read back off the
    settings afterwards — the split runs on a worker thread and the settings
    can change while it is in flight."""
    from tests.ui.test_main_window import _window, _make_fits
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    base = win.project.current()

    monkeypatch.setattr("nocturne.ui.main_window.rcastro_valid", lambda s: False)
    assert win._split_tagged(base)[2] == "free"

    monkeypatch.setattr("nocturne.ui.main_window.rcastro_valid", lambda s: True)
    monkeypatch.setattr(
        win, "_split_tagged",
        lambda img: (*_split_free(win, img), "StarX"))     # stand in for StarX
    assert win._split_tagged(base)[2] == "StarX"


def test_the_note_names_BOTH_paths_not_just_the_free_one(qtbot, tmp_path):
    """The bug this fixes: the free branch showed a note and the StarX branch
    showed "", so silence read as "no note applies here" rather than "you got
    the good one". Asserted on both branches, because only checking the one
    that was already right proves nothing."""
    from tests.ui.test_main_window import _window, _make_fits
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    starx = win._split_note("StarX")
    free = win._split_note("free")
    assert starx and free, "both branches must say something"
    assert starx != free
    assert "StarX" in starx


@pytest.mark.parametrize("nebula,expect_path", [(0.0, False), (0.4, True)])
def test_saturation_names_the_path_only_when_it_actually_split(
        qtbot, tmp_path, nebula, expect_path):
    """The nebula boost is the only part that splits, and it is lazy. At
    neb 0.00 nothing separated, so naming an engine would report work the step
    did not do."""
    from tests.ui.test_main_window import _window, _make_fits
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("saturation")
    base = win._preview_base("saturation")
    from nocturne.core.starless import split_stars
    starless, stars = split_stars(base)
    win._sat_layers = (win._sr_sig(base), starless, stars, "free")

    text = win._sat_log_option(0.5, nebula)
    assert ("(free)" in text) is expect_path, text
    assert "0.50" in text


def test_star_reduction_log_line_carries_the_path(qtbot, tmp_path):
    from tests.ui.test_main_window import _window, _make_fits
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("star_reduction")
    base = win.project.current()
    win._sr_layers = (win._sr_sig(base),
                      AstroImage(base.data * 0.4, is_linear=base.is_linear),
                      AstroImage(base.data * 0.6, is_linear=base.is_linear),
                      "free")
    win._sr_ready = True
    win._apply_star_reduction(0.5)
    entries = win.log_panel.entries() if hasattr(win.log_panel, "entries") else None
    text = "\n".join(entries) if entries else win.log_panel.toPlainText()
    assert "Star Reduction" in text and "(free)" in text, text


def test_starless_levels_log_line_carries_the_path(qtbot, tmp_path):
    """Stashed on the window rather than passed into the dialog: the dialog
    does not split and has no business knowing about engines, but its log line
    is the only place the user can learn which separation they got."""
    from tests.ui.test_main_window import _window, _make_fits
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._starless_levels_path = "free"
    result = win.project.current()
    win._apply_starless_levels(result, (0.1, 0.9))
    entries = win.log_panel.entries() if hasattr(win.log_panel, "entries") else None
    text = "\n".join(entries) if entries else win.log_panel.toPlainText()
    assert "Starless Levels" in text and "(free)" in text, text


def test_narrowband_and_colour_balance_are_NOT_silent_choosers():
    """Guards the scope correction above, so the two that were wrongly on the
    list do not get 'fixed' into choosing silently later."""
    import inspect
    from nocturne.ui import color_balance_dialog, narrowband_dialog
    for mod in (narrowband_dialog, color_balance_dialog):
        src = inspect.getsource(mod)
        # They must GATE on having a splitter and say so. Pinned as behaviour,
        # not as the symbol `rcastro_valid`: on 2026-09-18 the gate became
        # "any configured splitter" so StarNet2 counts too, and the old spelling
        # would have failed a change that strengthened exactly what this guards.
        assert "preferred_splitter" in src, mod.__name__
        assert "is None" in src, f"{mod.__name__} must still gate on having one"
        assert "split_stars" not in src, (
            f"{mod.__name__} gained a free-split fallback; it used to GATE on "
            "StarX and say so, and if it now chooses silently it needs a path "
            "label like the other three")
