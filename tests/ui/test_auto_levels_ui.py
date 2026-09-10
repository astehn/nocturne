"""Auto Levels in a recipe — the UI half.

Lives under tests/ui/ because tests/ui/conftest.py auto-answers modal dialogs;
without it MainWindow construction can block forever on one.
"""
import numpy as np
import pytest

from astropy.io import fits

from tests.ui.test_main_window import _make_fits, _window


def _fits_with_a_noise_floor(tmp_path, name="floor.fits"):
    """An image whose `auto_levels` black point is genuinely non-zero.

    The shared `_make_fits` uses uniform random values, for which
    `median - 3.5*MAD` lands at or below zero — so Auto returns exactly the
    slider defaults (0.0, 1.0, 1.0), no `setValue` changes anything, and NO
    valueChanged signal fires. Five of the tests in this file were passing in
    that degenerate regime: re-introducing the ordering hazard left six of seven
    green. A Gaussian floor well above zero puts them back in the regime the
    feature actually runs in.
    """
    rng = np.random.default_rng(7)
    arr = np.clip(rng.normal(18000, 1200, (3, 48, 48)), 0, 65535).astype(np.uint16)
    p = tmp_path / name
    hdu = fits.PrimaryHDU(arr)
    hdu.header["FILTER"] = "L"
    hdu.writeto(str(p))
    return str(p)


def _levels_window(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_fits_with_a_noise_floor(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    win._go_to_id("levels")
    return win


def test_pressing_auto_marks_the_step_automatic(qtbot, tmp_path):
    """THE ORDERING HAZARD. `_on_levels_auto` SETS the three sliders, and each
    setValue fires `_on_levels_change` — which clears the flag. Set the flag
    before that and it is wiped by the app's own signals, so the recipe silently
    stores numbers while the button says Auto.
    """
    win = _levels_window(qtbot, tmp_path)
    # The sliders MUST move for the hazard to exist: on the synthetic fixture
    # `auto_levels` returns exactly (0.0, 1.0, 1.0) — the defaults — so pressing
    # Auto from a fresh panel changes nothing, fires no signal, and the test
    # would pass without ever exercising the path it exists to guard. Move them
    # away first, so Auto has to put them back.
    p = win._panel
    p.black_slider.setValue(p.black_slider.value() + 40)
    p.gamma_slider.setValue(p.gamma_slider.value() - 20)
    p.white_slider.setValue(p.white_slider.value() - 20)
    moved_from = (p.black_slider.value(), p.gamma_slider.value(), p.white_slider.value())

    win._on_levels_auto()

    assert (p.black_slider.value(), p.gamma_slider.value(),
            p.white_slider.value()) != moved_from, (
        "Auto did not move the sliders, so this test proves nothing")
    assert win._levels_auto is True, (
        "the flag was cleared by the slider signals Auto itself fired")


@pytest.mark.parametrize("slider", ["black_slider", "gamma_slider", "white_slider"])
def test_nudging_any_slider_makes_it_manual(qtbot, tmp_path, slider):
    """Tested per slider: the handler is shared, and a guard covering only
    `black` would miss a regression in `gamma` or `white`."""
    win = _levels_window(qtbot, tmp_path)
    win._on_levels_auto()
    assert win._levels_auto is True
    s = getattr(win._panel, slider)
    # Nudge INWARDS from wherever it sits: white lands at its maximum after Auto,
    # so a blind +3 is a no-op that fires no signal and the test would pass for
    # the wrong reason.
    s.setValue(s.value() - 3 if s.value() > s.minimum() + 3 else s.value() + 3)
    assert win._levels_auto is False, f"{slider} did not clear the automatic flag"


def test_applying_after_auto_records_the_decision(qtbot, tmp_path):
    win = _levels_window(qtbot, tmp_path)
    win._on_levels_auto()
    win.apply_current((0.031, 1.0, 1.0))       # what the panel sends
    name, option = win.project.entries()[-1]
    assert name == "Levels"
    assert option == "auto", f"recorded {option!r} instead of the decision"


def test_applying_after_a_nudge_records_the_numbers(qtbot, tmp_path):
    win = _levels_window(qtbot, tmp_path)
    win._on_levels_auto()
    win._panel.black_slider.setValue(win._panel.black_slider.value() + 3)
    win.apply_current((0.034, 1.0, 1.0))
    _, option = win.project.entries()[-1]
    assert option == (0.034, 1.0, 1.0), f"recorded {option!r} instead of the numbers"


def test_the_auto_button_shows_whether_the_values_are_still_derived(qtbot, tmp_path):
    """The nudge rule is otherwise invisible — a 0.001 nudge changes what the
    recipe stores. This is what makes it visible BEFORE the recipe is saved."""
    win = _levels_window(qtbot, tmp_path)
    assert win._panel.auto_btn.isChecked() is False
    win._on_levels_auto()
    assert win._panel.auto_btn.isChecked() is True
    win._panel.white_slider.setValue(win._panel.white_slider.value() - 2)
    assert win._panel.auto_btn.isChecked() is False


def test_navigating_away_and_back_forgets_that_auto_was_pressed(qtbot, tmp_path):
    """A rebuilt panel is a NEW widget: unchecked button, default sliders. The
    flag has to reset with them.

    Left set, the app disagreed with everything on screen — go to another step
    and back, press Apply without touching anything, and instead of the no-op the
    panel promises it applied a full median-3.5*MAD black point and recorded
    "auto". A silent change to the picture, with the canvas still showing the
    un-levelled image right up to the commit.
    """
    win = _levels_window(qtbot, tmp_path)
    win._on_levels_auto()
    assert win._levels_auto is True
    win._go_to_id("curves")
    win._go_to_id("levels")
    assert win._panel.auto_btn.isChecked() is False, "the rebuilt button is unchecked"
    assert win._levels_auto is False, (
        "the flag outlived the panel: Apply would now record 'auto' for values "
        "the user never derived")


def test_opening_another_image_forgets_that_auto_was_pressed(qtbot, tmp_path):
    """Press Auto on image A, open image B, press Apply on Levels — B would get
    an auto black point nobody asked for."""
    win = _levels_window(qtbot, tmp_path)
    win._on_levels_auto()
    assert win._levels_auto is True
    second = tmp_path / "second"
    second.mkdir()
    win.open_fits(_make_fits(second))
    win._go_to_id("levels")
    assert win._levels_auto is False


def test_auto_measures_the_same_image_the_commit_will(qtbot, tmp_path):
    """WYSIWYG. Auto measured `project.current()` while the preview and the
    commit both operate on the PRE-Levels image. Those agree only until a Levels
    step has been applied; after one they diverged by 0.227 mean on a synthetic
    frame — the preview showed one picture and Apply produced another.
    """
    from nocturne.core.levels import auto_levels

    win = _levels_window(qtbot, tmp_path)
    win.apply_current((0.05, 1.0, 1.0))      # a Levels step now exists
    win._go_to_id("levels")
    win._on_levels_auto()
    expected = auto_levels(win._preview_base("levels").data)
    shown = (win._panel.black_slider.value() / 1000.0,
             win._panel.gamma_slider.value() / 100.0,
             win._panel.white_slider.value() / 100.0)
    assert shown[0] == pytest.approx(expected[0], abs=2e-3), (
        f"Auto suggested {shown[0]:.4f} from the wrong image; the commit will "
        f"use {expected[0]:.4f}")
