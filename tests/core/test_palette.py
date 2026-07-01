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


def test_apply_channel_curve_neutral_is_noop():
    from seestar_processor.core.palette import apply_channel_curve, ChannelCurve
    ch = np.array([[0.0, 0.25, 0.5, 0.75, 1.0]], np.float32)
    out = apply_channel_curve(ch, ChannelCurve())        # black 0, mid .5, white 1
    assert np.allclose(out, ch, atol=1e-6)


def test_apply_channel_curve_white_point_brightens():
    from seestar_processor.core.palette import apply_channel_curve, ChannelCurve
    ch = np.array([[0.5]], np.float32)
    out = apply_channel_curve(ch, ChannelCurve(white=0.5))  # pull white down -> brighter
    assert out[0, 0] > 0.5


def test_apply_channel_curve_black_point_darkens():
    from seestar_processor.core.palette import apply_channel_curve, ChannelCurve
    ch = np.array([[0.3]], np.float32)
    out = apply_channel_curve(ch, ChannelCurve(black=0.2))  # lift black -> darker lows
    assert out[0, 0] < 0.3


def test_apply_channel_curve_mid_gamma():
    from seestar_processor.core.palette import apply_channel_curve, ChannelCurve
    ch = np.array([[0.5]], np.float32)
    assert np.isclose(apply_channel_curve(ch, ChannelCurve(mid=0.5))[0, 0], 0.5, atol=1e-6)
    assert apply_channel_curve(ch, ChannelCurve(mid=0.8))[0, 0] > 0.5   # brighter mids
    assert apply_channel_curve(ch, ChannelCurve(mid=0.2))[0, 0] < 0.5   # darker mids


def test_render_nebula_neutral_curves_equals_plain_palette():
    from seestar_processor.core.palette import render_nebula, PaletteParams, hoo
    img = _img([(0.9, 0.2, 0.4), (0.3, 0.7, 0.6)])
    # neutral curves + scnr off == plain HOO combination
    out = render_nebula(img, PaletteParams(palette="HOO", scnr=False)).data
    plain = hoo(img).data
    assert np.allclose(out, plain, atol=1e-6)


def test_render_nebula_per_channel_independent():
    from seestar_processor.core.palette import render_nebula, PaletteParams, ChannelCurve
    img = _img([(0.8, 0.5, 0.5), (0.6, 0.5, 0.5)])
    base = render_nebula(img, PaletteParams(scnr=False)).data
    # pull RED white down -> red mean rises; green/blue unchanged
    tweaked = render_nebula(
        img, PaletteParams(r=ChannelCurve(white=0.5), scnr=False)).data
    assert tweaked[..., 0].mean() > base[..., 0].mean()
    assert np.allclose(tweaked[..., 1], base[..., 1], atol=1e-6)
    assert np.allclose(tweaked[..., 2], base[..., 2], atol=1e-6)


def test_render_nebula_scnr_reduces_green():
    from seestar_processor.core.palette import render_nebula, PaletteParams
    img = _img([(0.2, 0.9, 0.2)])
    with_scnr = render_nebula(img, PaletteParams(scnr=True)).data[0, 0]
    without = render_nebula(img, PaletteParams(scnr=False)).data[0, 0]
    assert with_scnr[1] <= without[1]


def test_compose_screens_stars_back():
    from seestar_processor.core.palette import compose, PaletteParams
    starless = _img([(0.3, 0.4, 0.4), (0.3, 0.4, 0.4)])
    stars = _img([(0.0, 0.0, 0.0), (0.9, 0.9, 0.9)])   # a star only in pixel 1
    out = compose(starless, stars, PaletteParams()).data
    assert out.shape == (1, 2, 3)
    assert out[0, 1].mean() > out[0, 0].mean()          # star pixel is brighter
