import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.enhance import boost_hue, darken_sky, lighten_sky, soft_glow, vibrance, star_colour
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


def test_soft_glow_brightens_highlights_not_background():
    data = np.zeros((16, 16, 3), np.float32)
    data[6:10, 6:10] = 0.8                                   # a bright central blob
    out = soft_glow(AstroImage(data, is_linear=False), amount=0.5, radius=3.0, threshold=0.3).data
    assert out[7, 7].mean() > data[7, 7].mean()             # highlight brightened
    assert out[0, 0].mean() < 0.02                          # dark corner ~untouched


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


def test_star_colour_boosts_only_masked_region():
    data = np.zeros((4, 4, 3), np.float32)
    data[..., 0], data[..., 1], data[..., 2] = 0.6, 0.4, 0.4  # uniform slightly-red
    img = AstroImage(data, is_linear=False)
    mask = np.zeros((4, 4), np.float32); mask[1, 1] = 1.0
    out = star_colour(img, mask, amount=0.8).data
    s_in, s_out = rgb2hsv(data)[..., 1], rgb2hsv(np.clip(out, 0, 1))[..., 1]
    assert s_out[1, 1] > s_in[1, 1]                          # masked pixel: saturation up
    assert abs(s_out[0, 0] - s_in[0, 0]) < 1e-4             # unmasked pixel: unchanged


def test_star_colour_zero_amount_and_mono():
    data = np.zeros((4, 4, 3), np.float32); data[..., 0] = 0.6; data[..., 1] = 0.3; data[..., 2] = 0.3
    img = AstroImage(data, is_linear=False)
    mask = np.ones((4, 4), np.float32)
    assert np.allclose(star_colour(img, mask, amount=0.0).data, data, atol=1e-4)   # no-op
    mono = AstroImage(np.full((4, 4), 0.3, np.float32), is_linear=False)
    assert np.allclose(star_colour(mono, mask).data, mono.data)                    # mono unchanged
