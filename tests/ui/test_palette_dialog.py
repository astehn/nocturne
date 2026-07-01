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


def test_slider_change_rerenders(qtbot):
    dlg = PaletteDialog(Settings(), _color())
    qtbot.addWidget(dlg)
    dlg._async = False
    dlg._starx_enabled = True
    dlg._starx_runner = _fake_starx
    dlg.start()
    before = dlg.preview.pixmap().cacheKey()
    dlg.sat_slider.setValue(95)                        # should trigger a re-render
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
