import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.color import remove_green_fringe, remove_green


def _px(r, g, b, h=4, w=4):
    a = np.zeros((h, w, 3), np.float32)
    a[..., 0] = r
    a[..., 1] = g
    a[..., 2] = b
    return AstroImage(a, is_linear=False)


def test_strength_zero_is_noop():
    img = _px(0.2, 0.8, 0.3)
    assert np.allclose(remove_green_fringe(img, 0.0).data, img.data)


def test_green_excess_reduced_red_blue_untouched():
    img = _px(0.2, 0.8, 0.3)                 # avg_rb = 0.25, excess = 0.55
    out = remove_green_fringe(img, 0.5).data
    assert out[0, 0, 1] < 0.8                # green pulled down
    assert np.isclose(out[0, 0, 1], 0.8 - 0.5 * 0.55)   # G - strength*excess
    assert np.isclose(out[0, 0, 0], 0.2)     # red untouched
    assert np.isclose(out[0, 0, 2], 0.3)     # blue untouched


def test_neutral_and_red_dominant_untouched():
    grey = _px(0.5, 0.5, 0.5)                # excess 0
    red = _px(0.8, 0.3, 0.4)                 # G < avg_rb -> excess 0
    assert np.allclose(remove_green_fringe(grey, 1.0).data, grey.data)
    assert np.allclose(remove_green_fringe(red, 1.0).data, red.data)


def test_strength_one_equals_remove_green():
    rng = np.random.default_rng(0)
    img = AstroImage(rng.random((16, 16, 3)).astype(np.float32), is_linear=False)
    assert np.allclose(remove_green_fringe(img, 1.0).data, remove_green(img).data)


def test_range_dtype_and_metadata():
    img = AstroImage(np.full((8, 8, 3), 0.6, np.float32),
                     is_linear=False, metadata={"k": 1})
    img.data[..., 1] = 0.9                    # green excess
    out = remove_green_fringe(img, 0.7)
    assert out.data.dtype == np.float32
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0
    assert out.is_linear is False and out.metadata == {"k": 1}


def test_mono_is_noop():
    img = AstroImage(np.full((8, 8), 0.5, np.float32))
    assert np.allclose(remove_green_fringe(img, 1.0).data, img.data)
