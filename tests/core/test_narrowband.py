import numpy as np
import pytest
from nocturne.core.image import AstroImage
from nocturne.core.narrowband import (
    NarrowbandParams, PALETTES, channel_level, extract_ha_oiii,
    normalize_to_reference, render, screen,
)


def _rgb(ha, oiii):
    """Build a colour AstroImage with R=Ha, G=B=OIII (the dual-band layout)."""
    data = np.stack([ha, oiii, oiii], axis=2).astype(np.float32)
    return AstroImage(np.clip(data, 0, 1), is_linear=False)


def test_channel_level_uses_median_black_point():
    c = np.array([0.1, 0.2, 0.2, 0.9], np.float32)   # min .1, median .2
    M, E0 = channel_level(c, blackpoint=1.0)
    assert abs(M - 0.2) < 1e-6                        # min + 1.0*(median-min) = median
    assert E0 > 0


def test_screen_is_symmetric_and_brightens():
    a = np.full((4, 4), 0.4, np.float32)
    b = np.full((4, 4), 0.5, np.float32)
    out = screen(a, b)
    assert np.allclose(out, screen(b, a))
    assert (out >= np.maximum(a, b) - 1e-6).all()


def test_extract_ha_oiii_splits_channels():
    ha = np.full((4, 4), 0.6, np.float32)
    oiii = np.full((4, 4), 0.2, np.float32)
    got_ha, got_oiii = extract_ha_oiii(_rgb(ha, oiii))
    assert np.allclose(got_ha, 0.6) and np.allclose(got_oiii, 0.2)


def test_extract_ha_oiii_rejects_mono():
    with pytest.raises(ValueError):
        extract_ha_oiii(AstroImage(np.zeros((4, 4), np.float32), is_linear=False))


def test_normalize_lifts_oiii_signal_toward_reference():
    # NBN anchors the background (median) and lifts the SIGNAL above it toward the
    # reference: a bright OIII patch is lifted MORE when Ha is stronger, while the sky
    # background (below the OIII median) stays put. The median is invariant by design.
    rng = np.random.default_rng(0)
    oiii = np.clip(0.08 + 0.02 * rng.standard_normal((80, 80)), 0, 1).astype(np.float32)
    oiii[30:50, 30:50] = 0.55                         # oxygen-rich patch

    def patch(ha_level):
        ha = np.clip(ha_level + 0.02 * rng.standard_normal((80, 80)), 0, 1).astype(np.float32)
        return normalize_to_reference(oiii, ha, blackpoint=1.0, boost=1.0)

    weak, strong = patch(0.30), patch(0.85)
    assert np.isfinite(strong).all()
    assert strong[40, 40] > weak[40, 40] + 0.1        # stronger Ha lifts the OIII signal
    assert abs(np.median(strong) - np.median(oiii)) < 0.02   # sky background anchored


def test_normalize_lift_scales_with_reference_strength():
    # The lift is driven by the reference's own robust level E0/(1-M_ref) — each
    # channel using its OWN black point. A stronger reference lifts the OIII mean
    # higher, proving the reference (not just the secondary) drives the result.
    rng = np.random.default_rng(1)
    oiii = np.clip(0.10 + 0.03 * rng.standard_normal((80, 80)), 0, 1).astype(np.float32)
    oiii[20:60, 20:60] = 0.5

    def mean_for(ha_level):
        ha = np.clip(ha_level + 0.02 * rng.standard_normal((80, 80)), 0, 1).astype(np.float32)
        return float(normalize_to_reference(oiii, ha, blackpoint=1.0, boost=1.0).mean())

    assert mean_for(0.85) > mean_for(0.30) + 0.02


def test_oiii_boost_lifts_the_signal():
    rng = np.random.default_rng(2)
    oiii = np.clip(0.10 + 0.03 * rng.standard_normal((64, 64)), 0, 1).astype(np.float32)
    oiii[16:48, 16:48] = 0.5
    ha = np.clip(0.45 + 0.03 * rng.standard_normal((64, 64)), 0, 1).astype(np.float32)
    base = normalize_to_reference(oiii, ha, boost=1.0)
    boosted = normalize_to_reference(oiii, ha, boost=1.6)
    assert boosted.mean() > base.mean() + 0.01        # boost pushes the signal higher
    assert boosted[32, 32] > base[32, 32]             # the patch specifically


def test_normalize_degenerate_channel_is_identity_no_nan():
    flat = np.full((16, 16), 0.3, np.float32)
    out = normalize_to_reference(flat, flat, boost=1.0)
    assert np.isfinite(out).all()
    assert np.allclose(out, flat, atol=1e-3)


def test_render_hoo_makes_oiii_regions_bluer():
    # A frame with an OIII-strong patch should gain blue there after HOO render.
    ha = np.full((32, 32), 0.5, np.float32)
    oiii = np.full((32, 32), 0.1, np.float32)
    oiii[8:24, 8:24] = 0.6                           # oxygen-rich patch
    out = render(_rgb(ha, oiii), NarrowbandParams(palette="HOO", protect_background=0.0,
                                                  lightness_preserve=False))
    patch = out.data[16, 16]
    corner = out.data[0, 0]
    assert patch[2] > corner[2]                      # more blue in the OIII patch


def test_render_scnr_suppresses_green_in_hoo():
    rng = np.random.default_rng(3)
    ha = np.clip(0.5 + 0.03 * rng.standard_normal((48, 48)), 0, 1).astype(np.float32)
    oiii = np.clip(0.2 + 0.03 * rng.standard_normal((48, 48)), 0, 1).astype(np.float32)
    img = _rgb(ha, oiii)
    on = render(img, NarrowbandParams(palette="HOO", scnr=True, protect_background=0.0,
                                      lightness_preserve=False)).data
    off = render(img, NarrowbandParams(palette="HOO", scnr=False, protect_background=0.0,
                                       lightness_preserve=False)).data
    assert on[..., 1].mean() <= off[..., 1].mean() + 1e-6   # green not increased by SCNR


def test_render_all_palettes_run_and_are_colour():
    ha = np.full((16, 16), 0.5, np.float32)
    oiii = np.full((16, 16), 0.25, np.float32)
    for pal in PALETTES:
        out = render(_rgb(ha, oiii), NarrowbandParams(palette=pal))
        assert out.data.shape == (16, 16, 3)
        assert out.is_linear is False
        assert np.isfinite(out.data).all()


def test_brightness_effective_under_preserve_lightness():
    # Regression: Brightness must change the image even with lightness_preserve on
    # (it used to be overwritten by preserve_lightness and appeared dead). Applying
    # it after the lightness step keeps the slider live in both modes.
    ha = np.full((32, 32), 0.4, np.float32)
    oiii = np.full((32, 32), 0.2, np.float32)
    oiii[8:24, 8:24] = 0.5
    img = _rgb(ha, oiii)
    dim = render(img, NarrowbandParams(palette="HOO", lightness_preserve=True,
                                       brightness=1.0, protect_background=0.0)).data
    bright = render(img, NarrowbandParams(palette="HOO", lightness_preserve=True,
                                          brightness=1.8, protect_background=0.0)).data
    assert bright.mean() > dim.mean() + 0.02


def test_render_rejects_mono():
    with pytest.raises(ValueError):
        render(AstroImage(np.zeros((8, 8), np.float32), is_linear=False), NarrowbandParams())


def test_protect_background_leaves_dark_sky_closer_to_original():
    ha = np.full((32, 32), 0.05, np.float32)         # dark sky
    oiii = np.full((32, 32), 0.02, np.float32)
    ha[12:20, 12:20] = 0.7                            # bright nebula
    oiii[12:20, 12:20] = 0.5
    img = _rgb(ha, oiii)
    protected = render(img, NarrowbandParams(palette="HOO", protect_background=0.8,
                                             lightness_preserve=False)).data
    whole = render(img, NarrowbandParams(palette="HOO", protect_background=0.0,
                                         lightness_preserve=False)).data
    # dark corner stays closer to the original with protection on
    orig_corner = img.data[0, 0]
    assert np.abs(protected[0, 0] - orig_corner).sum() < np.abs(whole[0, 0] - orig_corner).sum()
