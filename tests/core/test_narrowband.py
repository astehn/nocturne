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


def _noisy_nebula(n=200):
    rng = np.random.default_rng(3)
    lum = np.clip(0.25 + 0.05 * rng.standard_normal((n, n)), 0, 1).astype(np.float32)
    lum[n // 3:2 * n // 3, n // 3:2 * n // 3] += 0.35      # a nebula with noisy edges
    return np.repeat(np.clip(lum, 0, 1)[:, :, None], 3, axis=2).astype(np.float32)


def test_the_protect_background_mask_is_feathered():
    """It followed pixel-level noise straight into the picture. Measured on a
    real IC 1396A render: the steepest step was a full 0->1 in ONE pixel, and
    116,556 pixels (4.00% of the frame) jumped more than 0.25 — which is the
    hard edge Andreas could see around the nebula.
    """
    from nocturne.core.narrowband import nebula_mask
    m = nebula_mask(_noisy_nebula(), 0.4)
    gy, gx = np.gradient(m)
    grad = np.hypot(gx, gy)
    assert grad.max() < 0.25, f"mask still steps hard: max gradient {grad.max():.3f}"
    assert (grad > 0.25).sum() == 0
    assert m.min() < 0.2 and m.max() > 0.8, "and it must still separate nebula from sky"


def test_the_mask_feather_matches_the_one_saturation_already_uses():
    """Same constant, not a second opinion. Feathering as a FRACTION of the short
    edge is also what keeps the 640 px preview honest against the full-resolution
    Apply — both get proportionally the same softness."""
    from nocturne.core import narrowband
    from nocturne.core.saturation import _MASK_SIGMA_FRAC
    assert narrowband._MASK_SIGMA_FRAC == _MASK_SIGMA_FRAC


def test_a_starless_layer_lets_saturation_reach_the_nebula_core():
    """The core is the brightest thing in a starless narrowband frame, and
    saturate()'s star-protection taper was suppressing the boost exactly there:
    1.05x gain at the brightest part against 1.50x in the outskirts."""
    from skimage.color import rgb2lab
    from nocturne.core.narrowband import NarrowbandParams, render
    ha = np.full((60, 60), 0.55, np.float32)
    oiii = np.full((60, 60), 0.30, np.float32)
    ha[20:40, 20:40] = 0.95                      # a bright core
    oiii[20:40, 20:40] = 0.90
    img = AstroImage(np.stack([ha, oiii, oiii], axis=2), is_linear=False)
    core = np.zeros((60, 60), bool)
    core[24:36, 24:36] = True

    def chroma(out):
        lab = rgb2lab(np.clip(out, 0, 1))
        return float(np.hypot(lab[..., 1][core], lab[..., 2][core]).mean())

    p = NarrowbandParams(saturation=1.0, protect_background=0.0)
    with_stars = chroma(render(img, p, has_stars=True).data)
    starless = chroma(render(img, p, has_stars=False).data)
    assert starless > with_stars * 1.2, (
        f"starless must reach the core: {starless:.2f} vs {with_stars:.2f}")


def test_which_palettes_use_the_green_blend_is_measured_not_asserted():
    """The constant must match what the engine actually does, or greying the
    slider out becomes its own lie. Measured: HOO changes by 0.081 between
    blend 0.00 and 1.00; the other two by exactly 0.000000, because only HOO
    builds a synthetic green — Pseudo-SHO takes green straight from Ha and
    Pseudo-bicolor takes it straight from OIII.
    """
    from nocturne.core.narrowband import PALETTES_USING_BLEND
    rng = np.random.default_rng(2)
    img = AstroImage(np.clip(rng.random((60, 60, 3)).astype(np.float32) * 0.6 + 0.2, 0, 1),
                     is_linear=False)
    for palette in PALETTES:
        a = render(img, NarrowbandParams(palette=palette, blend_amount=0.0)).data
        b = render(img, NarrowbandParams(palette=palette, blend_amount=1.0)).data
        moved = float(np.abs(a - b).max()) > 1e-6
        assert moved == (palette in PALETTES_USING_BLEND), (
            f"{palette}: blend {'moves' if moved else 'does not move'} the picture, "
            f"but PALETTES_USING_BLEND says {palette in PALETTES_USING_BLEND}")
