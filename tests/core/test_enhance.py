import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.enhance import boost_hue, darken_sky, lighten_sky


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
