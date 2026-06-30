import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.levels import apply_levels


def test_identity():
    d = np.linspace(0, 1, 64, dtype=np.float32).reshape(8, 8)
    out = apply_levels(AstroImage(d), 0.0, 1.0, 1.0)
    assert np.allclose(out.data, d, atol=1e-6)


def test_raise_black_point_darkens():
    d = np.full((8, 8), 0.3, np.float32)
    out = apply_levels(AstroImage(d), 0.2, 1.0, 1.0)
    assert np.median(out.data) < 0.3


def test_gamma_above_one_brightens():
    d = np.full((8, 8), 0.3, np.float32)
    out = apply_levels(AstroImage(d), 0.0, 2.0, 1.0)
    assert np.median(out.data) > 0.3


def test_preserves_linear_flag_and_range():
    out = apply_levels(
        AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=False),
        0.1, 1.5, 0.9,
    )
    assert out.is_linear is False
    assert out.data.min() >= 0 and out.data.max() <= 1
