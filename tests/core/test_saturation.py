import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.saturation import saturate


def test_saturation_increases_chroma():
    data = np.tile(np.array([0.6, 0.4, 0.2], np.float32), (8, 8, 1))
    out = saturate(AstroImage(data), 1.0)
    assert (out.data[0, 0].max() - out.data[0, 0].min()) > (0.6 - 0.2)


def test_half_amount_is_noop():
    data = np.random.rand(8, 8, 3).astype(np.float32)
    out = saturate(AstroImage(data), 0.5)
    assert np.allclose(out.data, data, atol=1e-6)


def test_zero_amount_is_greyscale():
    data = np.tile(np.array([0.6, 0.4, 0.2], np.float32), (8, 8, 1))
    out = saturate(AstroImage(data), 0.0).data[0, 0]
    assert out.max() - out.min() < 1e-6           # R=G=B -> grey


def test_partial_desaturation():
    data = np.tile(np.array([0.6, 0.4, 0.2], np.float32), (8, 8, 1))
    native = 0.6 - 0.2
    out = saturate(AstroImage(data), 0.25).data[0, 0]
    chroma = out.max() - out.min()
    assert 0.0 < chroma < native                  # muted but not grey


def test_monotonic_chroma_across_slider():
    data = np.tile(np.array([0.5, 0.35, 0.2], np.float32), (4, 4, 1))  # dark coloured pixel
    def chroma(a):
        px = saturate(AstroImage(data), a).data[0, 0]
        return float(px.max() - px.min())
    vals = [chroma(a) for a in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert vals == sorted(vals) and vals[0] < vals[-1]


def test_mono_noop():
    img = AstroImage(np.full((8, 8), 0.5, np.float32))
    assert np.allclose(saturate(img, 1.0).data, img.data)


def test_preserves_is_linear_and_range():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=False)
    out = saturate(img, 0.5)
    assert out.is_linear is False
    assert out.data.dtype == np.float32
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0


def test_background_protected_vs_midtones():
    # dark, noisy-background colour vs nebula-midtone colour: boosting must NOT
    # blow up the background's chroma the way it does the nebula's.
    bg = np.tile(np.array([0.12, 0.08, 0.06], np.float32), (4, 4, 1))   # lum ~0.087
    mid = np.tile(np.array([0.45, 0.35, 0.25], np.float32), (4, 4, 1))  # lum ~0.35
    sbg = saturate(AstroImage(bg), 1.0).data[0, 0]
    sm = saturate(AstroImage(mid), 1.0).data[0, 0]
    gain_bg = (sbg.max() - sbg.min()) - (0.12 - 0.06)
    gain_m = (sm.max() - sm.min()) - (0.45 - 0.25)
    assert gain_bg < gain_m          # background barely boosted; nebula boosted
    assert gain_bg < 0.02            # deep background essentially protected


def test_highlights_protected_vs_midtones():
    bright = np.tile(np.array([0.95, 0.85, 0.75], np.float32), (4, 4, 1))
    mid = np.tile(np.array([0.45, 0.35, 0.25], np.float32), (4, 4, 1))
    sb = saturate(AstroImage(bright), 1.0).data[0, 0]
    sm = saturate(AstroImage(mid), 1.0).data[0, 0]
    gain_b = (sb.max() - sb.min()) - (0.95 - 0.75)
    gain_m = (sm.max() - sm.min()) - (0.45 - 0.25)
    assert gain_b < gain_m  # bright pixels gain less chroma


def _screen(a, b):
    return 1.0 - (1.0 - a) * (1.0 - b)


def _sky_and_nebula():
    from nocturne.core.image import AstroImage
    a = np.full((100, 100, 3), 0.12, np.float32)      # sky
    a[30:70, 30:70] = (0.6, 0.3, 0.3)                  # reddish nebula block (lum 0.4)
    return AstroImage(a, is_linear=False, metadata={"k": 1})


def test_nebula_mask_sky_low_nebula_high():
    from nocturne.core.saturation import _nebula_mask
    lum = _sky_and_nebula().data.mean(axis=2)
    m = _nebula_mask(lum)
    assert m[50, 50] > 0.8        # nebula interior
    assert m[5, 5] < 0.2          # sky corner


def test_nebula_saturate_strength_zero_is_recombine():
    from nocturne.core.saturation import nebula_saturate
    from nocturne.core.image import AstroImage
    starless = _sky_and_nebula()
    stars = AstroImage(np.zeros((100, 100, 3), np.float32), is_linear=False)
    out = nebula_saturate(starless, stars, 0.0).data
    assert np.allclose(out, _screen(starless.data, stars.data))


def test_nebula_saturate_boosts_nebula_spares_sky():
    from nocturne.core.saturation import nebula_saturate
    from nocturne.core.image import AstroImage
    starless = _sky_and_nebula()
    stars = AstroImage(np.zeros((100, 100, 3), np.float32), is_linear=False)
    out = nebula_saturate(starless, stars, 1.0).data
    # nebula pixel: chroma (distance from its own luminance) grew
    def chroma(px):
        return float(np.abs(px - px.mean()).sum())
    assert chroma(out[50, 50]) > chroma(starless.data[50, 50])
    # sky pixel unchanged (mask ~0, stars 0 there)
    assert np.allclose(out[5, 5], starless.data[5, 5], atol=1e-3)


def test_nebula_saturate_screens_stars_untouched():
    from nocturne.core.saturation import nebula_saturate
    from nocturne.core.image import AstroImage
    starless = _sky_and_nebula()
    star_layer = np.zeros((100, 100, 3), np.float32)
    star_layer[5, 5] = (0.9, 0.9, 0.9)                 # a star over sky
    stars = AstroImage(star_layer, is_linear=False)
    out = nebula_saturate(starless, stars, 1.0).data
    plain = _screen(starless.data, star_layer)
    assert np.allclose(out[5, 5], plain[5, 5], atol=1e-3)   # star pixel unaffected by boost


def test_nebula_saturate_range_dtype_metadata():
    from nocturne.core.saturation import nebula_saturate
    from nocturne.core.image import AstroImage
    starless = _sky_and_nebula()
    stars = AstroImage(np.zeros((100, 100, 3), np.float32), is_linear=False)
    out = nebula_saturate(starless, stars, 0.7)
    assert out.data.dtype == np.float32
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0
    assert out.is_linear is False and out.metadata == {"k": 1}


def test_nebula_saturate_mono_no_chroma_change():
    from nocturne.core.saturation import nebula_saturate
    from nocturne.core.image import AstroImage
    starless = AstroImage(np.full((16, 16), 0.4, np.float32), is_linear=False)
    stars = AstroImage(np.zeros((16, 16), np.float32), is_linear=False)
    out = nebula_saturate(starless, stars, 1.0).data
    assert np.allclose(out, _screen(starless.data, stars.data))
