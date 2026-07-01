import numpy as np
import pytest
from seestar_processor.core.image import AstroImage
from seestar_processor.core.palette import (
    PALETTES, extract_channels, hoo, pseudo_sho, apply_palette, subtract_background,
)


def _img(pixels):
    # pixels: list of (r,g,b) -> a 1 x N x 3 colour image
    return AstroImage(np.array([pixels], dtype=np.float32), is_linear=False)


def test_extract_channels_ha_red_oiii_greenblue():
    img = _img([(0.8, 0.2, 0.4)])
    ha, oiii = extract_channels(img)
    assert np.allclose(ha, 0.8)
    assert np.allclose(oiii, 0.3)          # (0.2 + 0.4) / 2


def test_extract_channels_rejects_mono():
    mono = AstroImage(np.zeros((4, 4), np.float32))
    with pytest.raises(ValueError):
        extract_channels(mono)


def test_hoo_ha_pixel_red_and_oiii_pixel_teal():
    out = hoo(_img([(0.9, 0.1, 0.1), (0.1, 0.9, 0.9)])).data
    ha_px, oiii_px = out[0, 0], out[0, 1]
    assert ha_px[0] > ha_px[1] and ha_px[0] > ha_px[2]        # red-dominant
    assert np.isclose(oiii_px[1], oiii_px[2]) and oiii_px[1] > oiii_px[0]  # teal


def test_pseudo_sho_ha_gold_oiii_teal():
    out = pseudo_sho(_img([(0.9, 0.1, 0.1), (0.1, 0.9, 0.9)])).data
    ha_px, oiii_px = out[0, 0], out[0, 1]
    # Ha region -> gold: R and G both above B
    assert ha_px[0] > ha_px[2] and ha_px[1] > ha_px[2]
    # OIII region -> teal: B above R
    assert oiii_px[2] > oiii_px[0]


def test_subtract_background_drops_pedestal_keeps_signal():
    # A mostly-background field (0.3) with a small bright patch (0.8).
    data = np.full((1, 10, 3), 0.3, np.float32)
    data[0, 0] = 0.8                       # one bright pixel per channel
    out = subtract_background(AstroImage(data), percentile=50.0).data
    assert np.median(out) < 1e-6           # background pushed to ~0
    assert np.isclose(out[0, 0, 0], 0.5, atol=1e-6)   # signal preserved (0.8 - 0.3)


def test_subtract_background_passes_mono_through():
    mono = AstroImage(np.full((4, 4), 0.3, np.float32))
    assert subtract_background(mono).data.shape == (4, 4)


def test_apply_palette_dispatch_and_unknown():
    img = _img([(0.5, 0.5, 0.5)])
    assert apply_palette(img, "HOO").data.shape == img.data.shape
    assert set(PALETTES) == {"HOO", "pseudo_SHO"}
    with pytest.raises(ValueError):
        apply_palette(img, "SHO")


def test_neutralize_stars_makes_white():
    from seestar_processor.core.palette import neutralize_stars
    out = neutralize_stars(_img([(0.8, 0.2, 0.2)])).data[0, 0]
    assert np.allclose(out, out[0])              # R==G==B (grey/white)
    assert np.isclose(out[0], 0.4, atol=1e-6)    # = mean(0.8,0.2,0.2)


def test_screen_blend_math():
    from seestar_processor.core.palette import screen
    a = np.array([0.5, 0.0], np.float32)
    b = np.array([0.5, 0.3], np.float32)
    out = screen(a, b)
    assert np.isclose(out[0], 0.75)              # 1-(1-.5)(1-.5)
    assert np.isclose(out[1], 0.3)               # screen with 0 base = top


def test_render_nebula_saturation_zero_is_grey():
    from seestar_processor.core.palette import render_nebula, PaletteParams
    out = render_nebula(_img([(0.9, 0.1, 0.3)]), PaletteParams(saturation=0.0)).data[0, 0]
    assert np.allclose(out, out[0], atol=1e-6)   # greyscale


def test_render_nebula_balance_shifts_ha_oiii():
    from seestar_processor.core.palette import render_nebula, PaletteParams
    px = [(0.6, 0.6, 0.6)]                        # equal Ha and OIII
    ha_heavy = render_nebula(_img(px), PaletteParams(palette="HOO", balance=1.0)).data[0, 0]
    oiii_heavy = render_nebula(_img(px), PaletteParams(palette="HOO", balance=0.0)).data[0, 0]
    assert ha_heavy[0] > ha_heavy[2]             # balance=1 -> red (Ha) dominant
    assert oiii_heavy[2] > oiii_heavy[0]         # balance=0 -> blue (OIII) dominant


def test_render_nebula_scnr_reduces_green():
    from seestar_processor.core.palette import render_nebula, PaletteParams
    px = [(0.2, 0.9, 0.2)]
    with_scnr = render_nebula(_img(px), PaletteParams(scnr=True)).data[0, 0]
    without = render_nebula(_img(px), PaletteParams(scnr=False)).data[0, 0]
    assert with_scnr[1] <= without[1]


def test_compose_screens_stars_back():
    from seestar_processor.core.palette import compose, PaletteParams
    starless = _img([(0.3, 0.4, 0.4), (0.3, 0.4, 0.4)])
    stars = _img([(0.0, 0.0, 0.0), (0.9, 0.9, 0.9)])   # a star only in pixel 1
    out = compose(starless, stars, PaletteParams()).data
    assert out.shape == (1, 2, 3)
    assert out[0, 1].mean() > out[0, 0].mean()          # star pixel is brighter
