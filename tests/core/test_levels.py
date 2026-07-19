import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.levels import apply_levels, auto_levels, clipping_masks


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


def _stretched():
    rng = np.random.default_rng(0)
    d = np.clip(rng.normal(0.25, 0.05, (64, 64, 3)).astype(np.float32), 0, 1)
    d[:2, :2] = 0.98  # a few bright pixels
    return d


def test_auto_levels_sane():
    d = _stretched()
    b, g, w = auto_levels(d)
    assert 0.0 <= b < w <= 1.0
    assert 0.4 <= g <= 2.5
    assert b < float(np.median(d)) < w


def test_clipping_masks_flags_extremes():
    d = np.zeros((4, 4, 3), np.float32)
    d[0, 0] = 0.01; d[3, 3] = 0.99
    sh, hi = clipping_masks(d, black=0.05, white=0.95)
    assert sh[0, 0] and hi[3, 3]
    assert not sh[3, 3] and not hi[0, 0]
