import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.star_reduction import reduce_stars


def _star_with_wings():
    """A star: bright core (1.0) surrounded by softer wings (0.5)."""
    s = np.zeros((32, 32, 3), np.float32)
    s[16, 16] = 1.0
    s[15, 16] = s[17, 16] = s[16, 15] = s[16, 17] = 0.5
    return AstroImage(s)


def _screen(starless, stars):
    return 1.0 - (1.0 - starless) * (1.0 - stars)


def test_shrinks_wings_but_keeps_sharp_core():
    stars = _star_with_wings()
    starless = AstroImage(np.full((32, 32, 3), 0.1, np.float32))
    out = reduce_stars(starless, stars, 0.9).data
    full = _screen(starless.data, stars.data)
    # wings crushed -> apparent size reduced
    assert out[15, 16].max() < full[15, 16].max() - 0.1
    # bright core preserved -> stays a sharp point (no blur, not eroded away)
    assert out[16, 16].max() >= full[16, 16].max() - 1e-3


def test_amount_zero_is_noop():
    s = np.zeros((8, 8, 3), np.float32)
    s[4, 4] = 0.6
    stars, starless = AstroImage(s), AstroImage(np.full((8, 8, 3), 0.1, np.float32))
    out = reduce_stars(starless, stars, 0.0).data
    assert np.allclose(out, _screen(starless.data, s), atol=1e-6)


def test_stronger_amount_dims_faint_stars_more():
    s = np.zeros((8, 8, 3), np.float32)
    s[4, 4] = 0.5  # a faint star (no saturated core)
    stars, starless = AstroImage(s), AstroImage(np.zeros((8, 8, 3), np.float32))
    light = reduce_stars(starless, stars, 0.3).data[4, 4].max()
    strong = reduce_stars(starless, stars, 0.9).data[4, 4].max()
    assert strong < light < 0.5      # faint star dimmed, more so at higher amount


def test_preserves_is_linear():
    starless = AstroImage(np.full((8, 8, 3), 0.1, np.float32), is_linear=False)
    stars = AstroImage(np.zeros((8, 8, 3), np.float32))
    assert reduce_stars(starless, stars, 0.5).is_linear is False
