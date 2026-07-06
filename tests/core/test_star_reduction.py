import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.star_reduction import reduce_stars


def _stars():
    s = np.zeros((32, 32, 3), np.float32)
    s[16, 16] = 1.0  # a star
    return AstroImage(s)


def test_reduces_star_brightness():
    starless = AstroImage(np.full((32, 32, 3), 0.1, np.float32))
    out = reduce_stars(starless, _stars(), 0.9)
    assert out.data.shape == (32, 32, 3)
    full = 1 - (1 - starless.data) * (1 - _stars().data)  # plain screen of full star
    assert out.data.max() <= full.max() + 1e-6
    assert out.data[16, 16].max() < full[16, 16].max()


def test_preserves_is_linear():
    starless = AstroImage(np.full((8, 8, 3), 0.1, np.float32), is_linear=False)
    stars = AstroImage(np.zeros((8, 8, 3), np.float32))
    assert reduce_stars(starless, stars, 0.5).is_linear is False
