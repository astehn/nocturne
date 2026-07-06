import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.metrics import rms_delta


def test_identical_is_zero():
    a = AstroImage(np.full((8, 8, 3), 0.5, np.float32), is_linear=False)
    assert rms_delta(a, AstroImage(a.data.copy(), is_linear=False)) == 0.0


def test_nonlinear_change_is_positive():
    # Post-stretch (non-linear) images are compared as displayed (clipped).
    a = AstroImage(np.full((8, 8, 3), 0.5, np.float32), is_linear=False)
    b = AstroImage(np.full((8, 8, 3), 0.6, np.float32), is_linear=False)
    d = rms_delta(a, b)
    assert 9.0 < d < 11.0  # ~10%


def test_shape_mismatch_returns_none():
    a = AstroImage(np.zeros((8, 8, 3), np.float32), is_linear=False)
    b = AstroImage(np.zeros((4, 4, 3), np.float32), is_linear=False)
    assert rms_delta(a, b) is None


def test_linear_delta_reflects_visible_change():
    # Linear data has tiny values (~0.003); removing a light-pollution gradient
    # is nearly invisible in raw terms but clearly visible once autostretched for
    # display. The metric must report the visible change, not the raw magnitude
    # (the old behaviour rounded such steps to ~0.0% in the log).
    rng = np.random.default_rng(0)
    grad = np.linspace(0.001, 0.005, 64)[:, None, None]
    before = AstroImage(np.clip(0.003 + grad + rng.normal(0, 3e-4, (64, 64, 3)), 0, 1))
    after = AstroImage(np.clip(0.003 + rng.normal(0, 3e-4, (64, 64, 3)), 0, 1))
    raw = float(np.sqrt(np.mean((after.data - before.data) ** 2)) * 100.0)
    assert raw < 1.0                       # raw metric would look like "nothing happened"
    assert rms_delta(before, after) > 3.0  # display-based metric reports the real change
