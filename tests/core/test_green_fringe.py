import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.color import remove_green_fringe, _suppress_green_excess


def _screen(a, b):
    return 1.0 - (1.0 - a) * (1.0 - b)


def test_suppress_green_excess_reduces_green_keeps_rb():
    data = np.zeros((1, 1, 3), np.float32)
    data[0, 0] = (0.2, 0.8, 0.3)                 # avg_rb 0.25, excess 0.55
    out = _suppress_green_excess(data, 0.5)
    assert np.isclose(out[0, 0, 1], 0.8 - 0.5 * 0.55)
    assert np.isclose(out[0, 0, 0], 0.2) and np.isclose(out[0, 0, 2], 0.3)


def test_suppress_green_excess_noop_on_neutral_and_zero():
    grey = np.full((2, 2, 3), 0.5, np.float32)
    assert np.allclose(_suppress_green_excess(grey, 1.0), grey)          # excess 0
    g = np.zeros((1, 1, 3), np.float32); g[0, 0] = (0.2, 0.8, 0.3)
    assert np.allclose(_suppress_green_excess(g, 0.0), g)                # strength 0


def _layers():
    starless = AstroImage(np.full((4, 4, 3), 0.3, np.float32), is_linear=False,
                          metadata={"k": 1})
    stars = np.zeros((4, 4, 3), np.float32)
    stars[2, 2] = (0.2, 0.9, 0.3)                # a green-fringed star pixel
    return starless, AstroImage(stars, is_linear=False)


def test_strength_zero_is_plain_recombine():
    starless, stars = _layers()
    out = remove_green_fringe(starless, stars, 0.0).data
    assert np.allclose(out, _screen(starless.data, stars.data))


def test_degreens_star_pixel_only_background_untouched():
    starless, stars = _layers()
    out = remove_green_fringe(starless, stars, 1.0).data
    # star pixel green reduced vs the plain recombine
    plain = _screen(starless.data, stars.data)
    assert out[2, 2, 1] < plain[2, 2, 1]
    # a background pixel (stars==0 there) equals the untouched starless value
    assert np.allclose(out[0, 0], starless.data[0, 0])


def test_range_dtype_and_metadata_from_starless():
    starless, stars = _layers()
    out = remove_green_fringe(starless, stars, 0.7)
    assert out.data.dtype == np.float32
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0
    assert out.is_linear is False and out.metadata == {"k": 1}
