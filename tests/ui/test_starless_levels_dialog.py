import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.ui.starless_levels_dialog import StarlessLevelsDialog


@pytest.fixture
def split():
    starless = np.zeros((32, 32, 3), np.float32)
    starless[8:16, 8:16] = 0.60
    stars = np.zeros((32, 32, 3), np.float32)
    stars[0, 0] = 0.95
    return (AstroImage(starless, is_linear=False, metadata={}),
            AstroImage(stars, is_linear=False, metadata={}))


def test_opens_at_identity_endpoints(qtbot, split):
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    assert dlg.values() == (0.0, 1.0)


def test_sliders_can_represent_their_own_defaults(qtbot, split):
    """A slider whose divisor cannot express its default silently shifts the
    image the moment the dialog opens."""
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    black, white = dlg.values()
    assert black == 0.0 and white == 1.0


def test_compose_matches_the_core_function_exactly(qtbot, split):
    """WYSIWYG: the dialog must not have its own arithmetic."""
    from nocturne.core.enhance import starless_levels_layers
    starless, stars = split
    dlg = StarlessLevelsDialog(starless, stars)
    qtbot.addWidget(dlg)
    dlg.white_slider.setValue(600)
    out = dlg.compose()
    expected = starless_levels_layers(starless, stars, 0.0, 0.6)
    assert np.allclose(out.data, expected.data, atol=1e-6)


def test_white_slider_drives_the_white_point(qtbot, split):
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    dlg.white_slider.setValue(600)
    assert dlg.values()[1] == pytest.approx(0.6, abs=1e-6)


def test_clipping_toggle_is_off_by_default(qtbot, split):
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    assert dlg.clip_check.isChecked() is False


def test_apply_delivers_the_composed_image_and_the_values(qtbot, split):
    seen = {}
    dlg = StarlessLevelsDialog(*split,
                               on_apply=lambda img, vals: seen.update(img=img, vals=vals))
    qtbot.addWidget(dlg)
    dlg.white_slider.setValue(600)
    dlg._apply()
    assert seen["vals"] == (0.0, 0.6)
    assert seen["img"].data.shape == (32, 32, 3)


def test_stars_are_untouched_by_the_dialog(qtbot, split):
    """Assert the stars array is EQUAL to what it was, not merely different
    from some known-bad value."""
    starless, stars = split
    before = stars.data.copy()
    dlg = StarlessLevelsDialog(starless, stars)
    qtbot.addWidget(dlg)
    dlg.white_slider.setValue(400)
    dlg.compose()
    assert np.array_equal(stars.data, before)
