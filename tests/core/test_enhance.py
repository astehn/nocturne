import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.enhance import boost_hue, darken_sky, lighten_sky, soft_glow, vibrance, star_colour_layers
from skimage.color import rgb2hsv


def _rgb(pixels):
    return AstroImage(np.array([pixels], dtype=np.float32), is_linear=False)


def test_boost_hue_is_selective():
    # a red pixel and a teal pixel side by side; Boost Red raises red saturation, not teal
    from skimage.color import rgb2hsv
    img = _rgb([(0.6, 0.2, 0.2), (0.2, 0.6, 0.6)])   # red-ish, teal-ish
    out = boost_hue(img, 0.0).data                    # hue 0 = red
    before = rgb2hsv(np.clip(img.data, 0, 1))
    after = rgb2hsv(np.clip(out, 0, 1))
    assert after[0, 0, 1] > before[0, 0, 1] + 0.01    # red pixel more saturated
    assert abs(after[0, 1, 1] - before[0, 1, 1]) < 0.01   # teal pixel ~unchanged


def test_boost_cyan_and_blue_target_their_hues():
    from skimage.color import rgb2hsv
    teal = _rgb([(0.2, 0.6, 0.6)])
    assert rgb2hsv(boost_hue(teal, 0.5).data)[0, 0, 1] > rgb2hsv(teal.data)[0, 0, 1] + 0.01
    blue = _rgb([(0.2, 0.2, 0.6)])
    assert rgb2hsv(boost_hue(blue, 0.667).data)[0, 0, 1] > rgb2hsv(blue.data)[0, 0, 1] + 0.01


def test_darken_sky_lowers_background_keeps_bright():
    img = _rgb([(0.10, 0.10, 0.10), (0.80, 0.80, 0.80)])   # dark bg, bright
    out = darken_sky(img).data
    assert out[0, 0].mean() < 0.10                          # background pulled down
    assert abs(out[0, 1].mean() - 0.80) < 0.005             # bright untouched
    assert out.min() >= 0.0


def test_lighten_sky_raises_background_keeps_bright():
    img = _rgb([(0.10, 0.10, 0.10), (0.80, 0.80, 0.80)])
    out = lighten_sky(img).data
    assert out[0, 0].mean() > 0.10                          # background lifted
    assert abs(out[0, 1].mean() - 0.80) < 0.01
    assert out.max() <= 1.0


def test_boost_hue_mono_passthrough():
    mono = AstroImage(np.full((4, 4), 0.3, np.float32), is_linear=False)
    assert boost_hue(mono, 0.0).data.ndim == 2


def test_sky_ops_handle_mono():
    mono = AstroImage(np.full((4, 4), 0.1, np.float32), is_linear=False)
    assert darken_sky(mono).data.ndim == 2 and darken_sky(mono).data.max() < 0.1
    assert lighten_sky(mono).data.ndim == 2 and lighten_sky(mono).data.max() > 0.1


def test_soft_glow_blooms_around_highlights():
    data = np.zeros((20, 20, 3), np.float32)
    data[8:12, 8:12] = 0.7                                   # bright central blob
    out = soft_glow(AstroImage(data, is_linear=False), amount=0.4, radius=3.0, threshold=0.2).data
    assert out[9, 9].mean() > data[9, 9].mean()             # blob brightens
    assert out[7, 9].mean() > 0.004                         # glow bleeds OUTSIDE the blob edge (was pure black)
    assert out[7, 9].mean() > out[5, 9].mean()              # ...and decays with distance (a real bloom)
    assert out[0, 0].mean() < 0.03                          # far corner still dark


def test_soft_glow_works_on_mono():
    data = np.zeros((16, 16), np.float32)
    data[6:10, 6:10] = 0.8
    out = soft_glow(AstroImage(data, is_linear=False), amount=0.5, radius=3.0, threshold=0.3).data
    assert out[7, 7] > 0.8                                   # mono glows too (not a passthrough)


def test_vibrance_lifts_unsaturated_more_than_saturated():
    data = np.array([[[0.6, 0.55, 0.5], [0.9, 0.2, 0.2]]], np.float32)   # low-sat, high-sat (both bright)
    out = vibrance(AstroImage(data, is_linear=False), amount=0.5).data
    s_in, s_out = rgb2hsv(data)[..., 1], rgb2hsv(np.clip(out, 0, 1))[..., 1]
    assert s_out[0, 0] - s_in[0, 0] > 0                      # low-sat pixel gained saturation
    assert (s_out[0, 0] - s_in[0, 0]) > (s_out[0, 1] - s_in[0, 1])   # more than the saturated one


def test_vibrance_protects_shadows_and_mono():
    dark = np.array([[[0.05, 0.03, 0.03]]], np.float32)      # below shadow-protect knee
    out = vibrance(AstroImage(dark, is_linear=False), amount=0.5).data
    assert np.allclose(out, dark, atol=1e-3)                 # background protected
    mono = AstroImage(np.full((4, 4), 0.3, np.float32), is_linear=False)
    assert np.allclose(vibrance(mono).data, mono.data)       # mono unchanged


def _plain_recombine(base_val, stars):
    return 1.0 - (1.0 - base_val) * (1.0 - stars)


def test_star_colour_layers_colours_only_stars():
    # starless nebula (uniform dim) + a stars layer that is black except one
    # faint-gold star. Boosting must colour the star and leave nebula untouched.
    starless = AstroImage(np.full((8, 8, 3), 0.2, np.float32), is_linear=False)
    stars = np.zeros((8, 8, 3), np.float32); stars[4, 4] = (0.30, 0.24, 0.18)  # low-sat gold
    out = star_colour_layers(starless, AstroImage(stars, is_linear=False), amount=0.6).data
    plain = _plain_recombine(0.2, stars)
    s_out = rgb2hsv(np.clip(out, 0, 1))[..., 1]
    s_plain = rgb2hsv(np.clip(plain, 0, 1))[..., 1]
    assert s_out[4, 4] > s_plain[4, 4] + 0.02              # star gains saturation vs plain recombine
    assert np.allclose(out[0, 0], plain[0, 0], atol=1e-4)  # off-star pixel: identical to plain recombine


def test_star_colour_layers_zero_amount_and_mono():
    starless = AstroImage(np.full((6, 6, 3), 0.15, np.float32), is_linear=False)
    stars = np.zeros((6, 6, 3), np.float32); stars[3, 3] = (0.4, 0.3, 0.2)
    out0 = star_colour_layers(starless, AstroImage(stars, is_linear=False), amount=0.0).data
    assert np.allclose(out0, _plain_recombine(0.15, stars), atol=1e-5)   # amount 0 = plain recombine
    mono_less = AstroImage(np.full((6, 6), 0.15, np.float32), is_linear=False)
    mono_st = np.zeros((6, 6), np.float32); mono_st[3, 3] = 0.5
    out_m = star_colour_layers(mono_less, AstroImage(mono_st, is_linear=False), amount=0.6).data
    assert np.allclose(out_m, _plain_recombine(0.15, mono_st), atol=1e-5)  # mono: no chroma, unchanged


def test_vibrance_does_not_tint_true_neutral():
    grey = np.full((1, 1, 3), 0.6, np.float32)      # bright r=g=b neutral
    out = vibrance(AstroImage(grey, is_linear=False), amount=0.5).data
    assert np.allclose(out, grey, atol=2e-3)         # stays neutral — no red cast


def test_soft_glow_threshold_one_is_finite():
    data = np.ones((4, 4, 3), np.float32)            # lum == 1 everywhere -> b-a == 0 in smoothstep
    out = soft_glow(AstroImage(data, is_linear=False), threshold=1.0).data
    assert np.isfinite(out).all()                    # no divide-by-zero NaN
