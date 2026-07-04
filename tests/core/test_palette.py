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
    assert set(PALETTES) == {"Foraxx", "HOO", "pseudo_SHO"}
    assert apply_palette(img, "Foraxx").data.shape == img.data.shape
    with pytest.raises(ValueError):
        apply_palette(img, "SHO")


def test_neutralize_stars_makes_white():
    from seestar_processor.core.palette import neutralize_stars
    out = neutralize_stars(_img([(0.8, 0.2, 0.2)])).data[0, 0]
    assert np.allclose(out, out[0])              # R==G==B (grey/white)


def test_screen_blend_math():
    from seestar_processor.core.palette import screen
    a = np.array([0.5, 0.0], np.float32)
    b = np.array([0.5, 0.3], np.float32)
    out = screen(a, b)
    assert np.isclose(out[0], 0.75)              # 1-(1-.5)(1-.5)
    assert np.isclose(out[1], 0.3)               # screen with 0 base = top


def test_subtract_bg_2d_drops_pedestal():
    from seestar_processor.core.palette import subtract_bg_2d
    ch = np.full((8, 8), 0.5, dtype=np.float32)
    ch[0, 0] = 0.9
    out = subtract_bg_2d(ch)                 # median 0.5 subtracted
    assert out.min() == 0.0
    assert out[0, 0] == pytest.approx(0.4, abs=1e-6)


def test_renorm_oiii_matches_median_and_mad():
    from seestar_processor.core.palette import renorm_oiii, _mad
    rng = np.random.default_rng(0)
    ha = rng.random((32, 32)).astype(np.float32)
    oiii = (rng.random((32, 32)) * 0.1 + 0.02).astype(np.float32)   # much fainter
    out = renorm_oiii(ha, oiii)
    assert np.median(out) == pytest.approx(np.median(ha), abs=0.05)
    assert _mad(out) == pytest.approx(_mad(ha), abs=0.05)


def test_stretch_channel_lifts_faint_channel():
    from seestar_processor.core.palette import stretch_channel
    faint = np.full((16, 16), 0.05, dtype=np.float32)
    faint[0, 0] = 0.2
    out = stretch_channel(faint, 0.7)
    assert float(np.median(out)) > 0.05        # background lifted well above input


def test_foraxx_hues_by_region():
    from seestar_processor.core.palette import foraxx
    ha = np.array([[0.9, 0.1, 0.9]], dtype=np.float32)   # Ha-only, OIII-only, gold
    oiii = np.array([[0.1, 0.9, 0.4]], dtype=np.float32)
    r, g, b = foraxx(ha, oiii)
    assert r[0, 0] > g[0, 0] and r[0, 0] > b[0, 0]       # Ha-only -> red
    assert b[0, 1] > r[0, 1]                             # OIII-only -> blue/teal
    assert r[0, 2] > g[0, 2] > b[0, 2]                   # gold: R>G>B


def test_rotate_hue_shifts_red_toward_green():
    from seestar_processor.core.palette import rotate_hue
    red = np.zeros((1, 1, 3), dtype=np.float32); red[0, 0, 0] = 1.0
    same = rotate_hue(red, 0.0)
    assert np.allclose(same, red, atol=1e-6)             # 0 deg = identity
    rotated = rotate_hue(red, 120.0)                     # +120 deg -> green
    assert rotated[0, 0, 1] > rotated[0, 0, 0] and rotated[0, 0, 1] > rotated[0, 0, 2]


def test_palette_params_defaults():
    from seestar_processor.core.palette import PaletteParams
    p = PaletteParams()
    assert p.palette == "Foraxx"
    assert p.ha_stretch == 0.6 and p.oiii_stretch == 0.7
    assert p.hue_deg == 0.0 and p.saturation == 0.65 and p.scnr is True


def _bicolour_starless():
    # left half Ha-strong (red), right half OIII-strong (green+blue)
    import numpy as np
    from seestar_processor.core.image import AstroImage
    d = np.zeros((20, 20, 3), dtype=np.float32)
    d[:, :10, 0] = 0.6                       # Ha (red) left
    d[:, 10:, 1] = 0.6; d[:, 10:, 2] = 0.6   # OIII (g+b) right
    d += 0.02                                # faint pedestal
    return AstroImage(d, is_linear=True)


def _faint_oiii_starless():
    import numpy as np
    from seestar_processor.core.image import AstroImage
    d = np.zeros((20, 20, 3), dtype=np.float32)
    d[:, :10, 0] = 0.6                       # left: strong Ha (red)
    d[:, 10:, 1] = 0.08; d[:, 10:, 2] = 0.08 # right: FAINT OIII (≪ Ha)
    d += 0.02
    return AstroImage(d, is_linear=True)


def test_render_nebula_lifts_faint_oiii_into_colour():
    # Without renorm_oiii + independent stretch_channel, the faint OIII (~0.08)
    # stays near-black and the right half is red-monochrome; the pipeline must
    # lift it into visible teal.
    from seestar_processor.core.palette import render_nebula, PaletteParams
    out = render_nebula(_faint_oiii_starless(),
                        PaletteParams(palette="HOO", scnr=False, hue_deg=0.0,
                                      saturation=0.5)).data
    right = out[:, 10:]
    assert right[..., 2].mean() > 0.3                    # faint OIII lifted off the floor
    assert right[..., 2].mean() > right[..., 0].mean()   # teal, not red


def test_render_nebula_output_is_stretched():
    from seestar_processor.core.palette import render_nebula, PaletteParams
    out = render_nebula(_bicolour_starless(), PaletteParams())
    assert out.is_linear is False


def test_render_nebula_hoo_greenblue_equal():
    import numpy as np
    from seestar_processor.core.palette import render_nebula, PaletteParams
    out = render_nebula(_bicolour_starless(),
                        PaletteParams(palette="HOO", scnr=False, hue_deg=0.0,
                                      saturation=0.5)).data
    assert np.allclose(out[..., 1], out[..., 2], atol=1e-5)   # HOO: G == B


def test_render_nebula_scnr_reduces_green():
    from seestar_processor.core.palette import render_nebula, PaletteParams
    common = dict(palette="HOO", hue_deg=0.0, saturation=0.5)
    on = render_nebula(_bicolour_starless(), PaletteParams(scnr=True, **common)).data
    off = render_nebula(_bicolour_starless(), PaletteParams(scnr=False, **common)).data
    assert on[..., 1].sum() <= off[..., 1].sum() + 1e-6      # green not increased


def test_compose_screens_stars_back():
    import numpy as np
    from seestar_processor.core.image import AstroImage
    from seestar_processor.core.palette import compose, render_nebula, PaletteParams
    starless = _bicolour_starless()
    stars = AstroImage(np.zeros((20, 20, 3), np.float32), is_linear=True)
    stars.data[5, 5] = 0.9                                   # one bright star
    params = PaletteParams()
    result = compose(starless, stars, params)
    out = result.data
    nebula = render_nebula(starless, params).data
    assert out[5, 5].mean() >= nebula[5, 5].mean()          # star brightened the pixel
    assert result.is_linear is False                        # compose output is always stretched


def _faint_broad_linear():
    # A realistic linear master: faint sky background, a broad faint signal, and
    # a bright star (peak-normalized). Reproduces the "everything blows out to
    # white" bug when the background is subtracted at the median (p50).
    rng = np.random.default_rng(1)
    d = np.full((40, 40, 3), 0.02, dtype=np.float32)
    d[10:30, 10:30, 0] += 0.05                      # broad Ha patch
    d += rng.normal(0, 0.003, d.shape).astype(np.float32)
    d[5, 5, :] = 1.0                                # a bright star
    d = np.clip(d, 0.0, None)
    d /= d.max()
    return AstroImage(d.astype(np.float32), is_linear=True)


def test_render_nebula_does_not_blow_out_to_white():
    from seestar_processor.core.palette import render_nebula, PaletteParams
    img = _faint_broad_linear()
    out = render_nebula(img, PaletteParams(ha_stretch=0.0, oiii_stretch=0.0)).data
    white_fraction = float((out.mean(axis=2) >= 0.99).mean())
    assert white_fraction < 0.05        # p50 median-subtract blew ~15-45% to white


def test_render_nebula_sliders_have_effect():
    from seestar_processor.core.palette import render_nebula, PaletteParams
    img = _faint_broad_linear()
    lo = render_nebula(img, PaletteParams(ha_stretch=0.0, oiii_stretch=0.0)).data
    hi = render_nebula(img, PaletteParams(ha_stretch=1.0, oiii_stretch=1.0)).data
    assert float(np.median(hi)) - float(np.median(lo)) > 0.1   # stretch sliders do something


def _single_star_layer():
    # StarX 'stars_only' output is sparse (mostly black). A single gaussian star,
    # peak-normalized linear. An adaptive autostretch degenerates on this sparse
    # input and bloats the star's faint wings to white (footprint 9px -> ~149px);
    # a controlled stretch keeps the star tight.
    H, W = 80, 80
    yy, xx = np.mgrid[0:H, 0:W]
    star = np.exp(-(((xx - 40) ** 2 + (yy - 40) ** 2) / (2 * 1.4 ** 2))).astype(np.float32)
    return AstroImage(np.stack([star, star, star], axis=2), is_linear=True)


def test_neutralize_stars_does_not_bloat():
    from seestar_processor.core.palette import neutralize_stars
    out = neutralize_stars(_single_star_layer()).data
    footprint = int((out.mean(axis=2) > 0.5).sum())
    assert footprint < 40        # star stays tight (autostretch bloated it to ~149px)
    assert out.max() > 0.5       # but the star is still clearly visible
