import numpy as np
import pytest

pytest.importorskip("PySide6")
from seestar_processor.settings import Settings  # noqa: E402
from seestar_processor.core.image import AstroImage  # noqa: E402
from seestar_processor.ui.palette_dialog import PaletteDialog  # noqa: E402


def _color(seed=0):
    rng = np.random.default_rng(seed)
    return AstroImage(rng.random((40, 50, 3)).astype(np.float32), is_linear=False)


def _make_dialog(qtbot):
    dlg = PaletteDialog(Settings(), _color())
    qtbot.addWidget(dlg)
    return dlg


def _fake_starx(img):
    # synthetic starless + a stars layer, same shape
    starless = AstroImage(img.data * 0.5, is_linear=img.is_linear)
    stars = AstroImage(img.data * 0.5, is_linear=img.is_linear)
    return starless, stars


def test_dialog_runs_starx_and_renders(qtbot):
    dlg = PaletteDialog(Settings(), _color())
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg._starx_enabled = True
    dlg._starx_runner = _fake_starx
    dlg.start()
    assert dlg._starless is not None and dlg._stars is not None
    assert not dlg.preview.pixmap().isNull()          # preview rendered


def test_slider_change_rerenders(qtbot):
    dlg = PaletteDialog(Settings(), _color())
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg._starx_enabled = True
    dlg._starx_runner = _fake_starx
    dlg.start()
    before = dlg.preview.pixmap().cacheKey()
    dlg.oiii_slider.setValue(90)
    assert dlg.preview.pixmap().cacheKey() != before


def test_apply_records_result(qtbot):
    got = {}
    dlg = PaletteDialog(Settings(), _color(), on_apply=lambda r: got.setdefault("r", r))
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg._starx_enabled = True
    dlg._starx_runner = _fake_starx
    dlg.start()
    dlg.sho_radio.setChecked(True)
    dlg.apply()
    assert "r" in got and got["r"].data.shape == (40, 50, 3)


def test_fallback_without_rcastro(qtbot):
    # Settings() has no RC-Astro path -> _starx_enabled False -> whole-image path
    dlg = PaletteDialog(Settings(), _color())
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg.start()
    assert dlg._starx_enabled is False
    assert dlg._stars is None                          # no star layer to screen back
    assert not dlg.preview.pixmap().isNull()           # still renders (whole-image)


def test_new_controls_present_and_no_old_curves(qtbot):
    from seestar_processor.ui.reset_slider import ResetSlider
    dlg = _make_dialog(qtbot)
    assert isinstance(dlg.ha_slider, ResetSlider) and dlg.ha_slider._default == 60
    assert isinstance(dlg.oiii_slider, ResetSlider) and dlg.oiii_slider._default == 70
    assert isinstance(dlg.hue_slider, ResetSlider) and dlg.hue_slider._default == 50
    assert isinstance(dlg.sat_slider, ResetSlider) and dlg.sat_slider._default == 65
    assert dlg.foraxx_radio.isChecked()                       # Foraxx default
    assert not hasattr(dlg, "black_slider") and not hasattr(dlg, "r_radio")


def test_params_reflect_sliders(qtbot):
    dlg = _make_dialog(qtbot)
    dlg.oiii_slider.setValue(80)
    dlg.hue_slider.setValue(50)
    p = dlg._params()
    assert p.palette == "Foraxx"
    assert p.oiii_stretch == 0.80 and p.hue_deg == 0.0


def test_reset_returns_sliders_to_defaults(qtbot):
    dlg = _make_dialog(qtbot)
    dlg.ha_slider.setValue(20)
    dlg.reset()
    assert dlg.ha_slider.value() == 60 and dlg.oiii_slider.value() == 70


def test_linear_hint_shown_for_stretched_input(qtbot):
    # _color() builds an is_linear=False image -> hint should be visible
    dlg = _make_dialog(qtbot)
    assert "linear" in dlg.hint.text().lower()
