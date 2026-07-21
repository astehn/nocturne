import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.core.image import AstroImage           # noqa: E402
from nocturne.settings import Settings               # noqa: E402
from nocturne.ui.narrowband_dialog import NarrowbandDialog, PALETTES  # noqa: E402


def _img():
    ha = np.full((40, 40), 0.5, np.float32)
    oiii = np.full((40, 40), 0.2, np.float32)
    oiii[10:30, 10:30] = 0.6
    return AstroImage(np.stack([ha, oiii, oiii], axis=2), is_linear=False)


def _dialog(qtbot, **kw):
    d = NarrowbandDialog(Settings(), _img(), **kw)
    qtbot.addWidget(d)
    return d


def test_palettes_are_the_three_expected():
    assert list(PALETTES) == ["HOO", "Pseudo-SHO", "Pseudo-bicolor"]


def test_dialog_builds_with_seeded_layers(qtbot):
    d = _dialog(qtbot, starless=_img(), stars=None)
    d._on_starless((d._base, None))          # simulate showEvent seeding
    d._do_render()
    assert d.preview.has_image()


def _img_varied_ha():
    # Same shape/intent as _img(), but Ha has realistic per-pixel noise instead
    # of a perfectly flat 0.5. normalize_to_reference() intentionally treats a
    # zero-variance reference channel as degenerate (identity, see
    # tests/core/test_narrowband.py::test_normalize_degenerate_channel_is_identity_no_nan),
    # which would make oiii_boost inert end-to-end against a flat Ha.
    rng = np.random.default_rng(3)
    ha = np.clip(0.5 + 0.03 * rng.standard_normal((40, 40)), 0, 1).astype(np.float32)
    oiii = np.full((40, 40), 0.2, np.float32)
    oiii[10:30, 10:30] = 0.6
    return AstroImage(np.stack([ha, oiii, oiii], axis=2), is_linear=False)


def test_oiii_slider_changes_the_render(qtbot):
    img = _img_varied_ha()
    d = NarrowbandDialog(Settings(), img, starless=img, stars=None)
    qtbot.addWidget(d)
    d._on_starless((d._base, None))
    d.oiii_slider.setValue(50)
    d._do_render()
    low = d.preview_result().data.copy()
    d.oiii_slider.setValue(90)               # push OIII harder
    d._do_render()
    high = d.preview_result().data
    assert not np.allclose(low, high)


def test_apply_screens_stars_back_and_calls_on_apply(qtbot):
    got = []
    stars = AstroImage(np.zeros((40, 40, 3), np.float32), is_linear=False)
    stars.data[5, 5] = [0.95, 0.95, 0.95]
    d = _dialog(qtbot, starless=_img(), stars=stars, on_apply=lambda r, p: got.append((r, p)))
    d._on_starless((d._base, stars))
    d.apply()
    assert got and isinstance(got[0][0], AstroImage)
    assert got[0][0].data[5, 5].max() > 0.5          # star screened back
    assert got[0][1].palette == "HOO"                # params passed through
