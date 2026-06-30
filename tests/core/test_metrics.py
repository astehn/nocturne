import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.metrics import rms_delta


def test_identical_is_zero():
    a = AstroImage(np.full((8, 8, 3), 0.5, np.float32))
    assert rms_delta(a, AstroImage(a.data.copy())) == 0.0


def test_change_is_positive():
    a = AstroImage(np.full((8, 8, 3), 0.5, np.float32))
    b = AstroImage(np.full((8, 8, 3), 0.6, np.float32))
    d = rms_delta(a, b)
    assert 9.0 < d < 11.0  # ~10%


def test_shape_mismatch_returns_none():
    a = AstroImage(np.zeros((8, 8, 3), np.float32))
    b = AstroImage(np.zeros((4, 4, 3), np.float32))
    assert rms_delta(a, b) is None
