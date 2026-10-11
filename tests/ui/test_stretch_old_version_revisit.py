"""An OLD project's Stretch (no "version" in its option, so stretch version 1)
revisited on a build whose new stretches are version 2. The live preview renders
the current version, so once it is rendered it is a different picture from the
commit even at the same amount — it must read as pending (review 2026-10-11,
I-1). Revisiting without touching must still show the committed image."""
import numpy as np
from astropy.io import fits

from nocturne.core.color import ColorSettings
from tests.ui.test_main_window import _window

_OLD = {"amount": 0.30, "linked": True}        # the shape every old project holds


def _fits(tmp_path):
    rng = np.random.default_rng(3)
    h, w = 300, 400
    d = np.empty((3, h, w), np.float32)
    sky, noise = [0.020, 0.019, 0.021], [4e-4, 2.5e-4, 6e-4]
    for c in range(3):
        d[c] = sky[c] + rng.normal(0, noise[c], (h, w))
    d[2, :, :160] += 0.002
    d[1, :, :160] += 0.0005
    p = tmp_path / "s.fits"
    fits.PrimaryHDU((d * 65535).astype(np.uint16)).writeto(str(p))
    return str(p)


def _old_project_at_stretch(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_fits(tmp_path))
    win._async_enabled = False
    win._go_to_id("color")
    win.apply_current(ColorSettings(method="sky"))
    win._go_to_id("stretch")
    win.apply_current(dict(_OLD))
    committed = win.project.current().data.copy()
    win._go_to_id("levels"); qtbot.wait(20)
    win._go_to_id("stretch"); qtbot.wait(20)
    return win, committed


def test_revisiting_without_touching_shows_the_commit_and_is_not_pending(qtbot, tmp_path):
    win, committed = _old_project_at_stretch(qtbot, tmp_path)
    assert np.array_equal(win._displayed.data, committed)
    assert win._has_pending() is False


def test_a_nudged_and_restored_slider_is_pending_and_apply_upgrades(qtbot, tmp_path):
    from nocturne.core import autostretch
    from nocturne.steps.stretch_step import parse_stretch_version
    win, committed = _old_project_at_stretch(qtbot, tmp_path)
    win._panel.stretch_slider.setValue(31); win._render_stretch_preview()
    win._panel.stretch_slider.setValue(30); win._render_stretch_preview()
    shown = win._displayed.data.copy()
    assert not np.array_equal(shown, committed), "fixture: v2 must differ from v1 here"
    assert win._has_pending() is True, "a v2 preview over a v1 commit read as nothing"
    win.apply_current(win._panel.commit_option())
    option = win._committed_option("stretch")
    assert parse_stretch_version(option) == autostretch.STRETCH_VERSION
    assert np.array_equal(win.project.current().data, shown)
    assert win._has_pending() is False


def test_a_current_version_commit_nudged_back_is_still_nothing(qtbot, tmp_path):
    """The existing rule must survive: same version, slider put back = no work."""
    win, _ = _old_project_at_stretch(qtbot, tmp_path)
    win._panel.stretch_slider.setValue(31); win._render_stretch_preview()
    win.apply_current(win._panel.commit_option())          # now a current commit
    win._panel.stretch_slider.setValue(40); win._render_stretch_preview()
    win._panel.stretch_slider.setValue(31); win._render_stretch_preview()
    assert win._has_pending() is False
