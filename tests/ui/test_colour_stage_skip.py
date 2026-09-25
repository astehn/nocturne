"""Under an unlinked stretch the Colour step does nothing, so it is not offered.

Measured on IC 1396A, mean |pixel change| in the stretched output, 8-bit levels:

    background neutralise    linked 0.058      unlinked 0.000
    photometric gains        linked 0.3-1.5    unlinked 0.0004

Both of the step's jobs are per-channel and multiplicative, which is exactly
what a per-channel normalisation removes. Nothing else is in the step: the panel
builds ColorSettings(method=...) and remove_green defaults to False, because
de-green moved to its own post-stretch stage on 2026-09-13. So nothing is lost.

Andreas: "they still hit the crop step, the background step and the deconvolution
step but they are not even presented with the color step."
"""
import numpy as np
import pytest
from astropy.io import fits

pytest.importorskip("PySide6")
from nocturne.ui.main_window import MainWindow  # noqa: E402
from nocturne.ui.pipeline import path_stages  # noqa: E402


def _make_fits(tmp_path, name="stack.fits"):
    rng = np.random.default_rng(0)
    arr = rng.normal(1200, 60, (3, 24, 24))
    arr[0] = 1200 + (arr[0] - 1200) * 2.67
    p = tmp_path / name
    hdu = fits.PrimaryHDU(np.clip(arr, 0, 65535).astype(np.uint16))
    hdu.header["FILTER"] = "L"
    hdu.writeto(str(p))
    return str(p)


def _window(qtbot, tmp_path, name="stack.fits"):
    win = MainWindow(settings_path=str(tmp_path / "settings.json"), check_updates=False, telemetry=False)
    win._async_enabled = False
    qtbot.addWidget(win)
    win.open_fits(_make_fits(tmp_path, name))
    return win


def _ids(win):
    return [s.id for s in win._stages]


def test_unlinked_removes_colour_from_the_path(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert "color" in _ids(win)
    win._set_view_linked(False)
    assert not next(s for s in win._stages if s.id == "color").enabled


def test_the_other_linear_steps_all_survive(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._set_view_linked(False)
    for kept in ("load", "crop", "background", "deconvolution", "stretch"):
        assert kept in _ids(win), kept


def test_next_from_background_lands_on_deconvolution(qtbot, tmp_path):
    """The skip must be navigational, not merely cosmetic."""
    win = _window(qtbot, tmp_path)
    win._set_view_linked(False)
    win._go_to(_ids(win).index("background"))
    win.go_next()
    assert win.current_stage_id() == "deconvolution"


def test_the_current_step_is_preserved_across_the_rebuild(qtbot, tmp_path):
    """Indices shift when the list shrinks. Tracked by ID, not position, or
    flipping the switch would silently teleport the user to another step."""
    win = _window(qtbot, tmp_path)
    win._go_to(_ids(win).index("deconvolution"))
    assert win.current_stage_id() == "deconvolution"
    win._set_view_linked(False)
    assert win.current_stage_id() == "deconvolution"


def test_linked_keeps_colour(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert "color" in _ids(win)
    win._set_view_linked(False)
    win._set_view_linked(True)
    assert "color" in _ids(win)


def test_the_skip_does_not_leak_into_the_module_lists(qtbot, tmp_path):
    """path_stages() hands out the SAME frozen Stage objects every call. If the
    skip were done by mutation rather than dataclasses.replace, one project's
    choice would poison every later one in the session — and the module for the
    rest of the process."""
    # The WHOLE stage, not just its id: a leak that flips `enabled` in place
    # leaves the ids identical and would sail past an id-only comparison.
    before = list(path_stages())
    win = _window(qtbot, tmp_path)
    win._set_view_linked(False)
    assert list(path_stages()) == before
    assert all(s.enabled for s in path_stages())
    assert "color" in [s.id for s in before]

    second = _window(qtbot, tmp_path, name="second.fits")
    assert "color" in _ids(second)


def test_colour_stays_listed_but_disabled_when_unlinked(qtbot, tmp_path):
    """Inserting and removing Color moved every step below it (screenshot 07)."""
    from tests.ui.test_main_window import _make_fits, _window
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    ids_linked = [s.id for s in win._stages]
    win._set_view_linked(False)
    ids_unlinked = [s.id for s in win._stages]
    assert ids_unlinked == ids_linked                      # same rows, same order
    color = next(s for s in win._stages if s.id == "color")
    assert color.enabled is False
    assert "linked" in color.reason.lower()


def test_leaving_linked_while_on_colour_moves_you_to_an_enabled_step(qtbot, tmp_path):
    from tests.ui.test_main_window import _make_fits, _window
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("color", user_initiated=False)
    win._set_view_linked(False)
    assert win._stages[win._stage].enabled
