import numpy as np
import pytest

pytest.importorskip("PySide6")
from seestar_processor.settings import Settings  # noqa: E402
from seestar_processor.core.image import AstroImage  # noqa: E402
from seestar_processor.ui.palette_dialog import PaletteDialog  # noqa: E402


def _color(seed=0):
    rng = np.random.default_rng(seed)
    return AstroImage(rng.random((40, 50, 3)).astype(np.float32), is_linear=False)


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


def test_channel_curve_change_rerenders(qtbot):
    dlg = PaletteDialog(Settings(), _color())
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg._starx_enabled = True
    dlg._starx_runner = _fake_starx
    dlg.start()
    before = dlg.preview.pixmap().cacheKey()
    dlg.white_slider.setValue(40)                     # move active channel's white point
    assert dlg.preview.pixmap().cacheKey() != before


def test_channel_tab_stores_and_repopulates(qtbot):
    dlg = PaletteDialog(Settings(), _color())
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg._starx_enabled = True
    dlg._starx_runner = _fake_starx
    dlg.start()
    dlg.r_radio.setChecked(True)                      # editing R
    dlg.white_slider.setValue(30)
    assert dlg._curves["R"].white == 0.30
    dlg.g_radio.setChecked(True)                      # switch to G
    assert dlg.white_slider.value() == 100            # G still neutral -> white 1.0
    dlg.r_radio.setChecked(True)                      # back to R
    assert dlg.white_slider.value() == 30             # R's stored value restored


def test_reset_returns_curves_to_neutral(qtbot):
    dlg = PaletteDialog(Settings(), _color())
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg._starx_enabled = True
    dlg._starx_runner = _fake_starx
    dlg.start()
    dlg.r_radio.setChecked(True)
    dlg.black_slider.setValue(40)
    dlg.reset()
    assert all(c.black == 0.0 and c.mid == 0.5 and c.white == 1.0
               for c in dlg._curves.values())
    assert dlg.black_slider.value() == 0


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
