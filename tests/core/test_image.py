import numpy as np
import pytest
from nocturne.core.image import AstroImage


def test_coerces_to_float32_and_detects_color():
    img = AstroImage(np.zeros((4, 4, 3), dtype=np.uint8))
    assert img.data.dtype == np.float32
    assert img.is_color is True
    assert img.is_linear is True


def test_mono_is_not_color():
    img = AstroImage(np.zeros((4, 4), dtype=np.float32))
    assert img.is_color is False


def test_copy_is_independent():
    img = AstroImage(np.ones((2, 2), dtype=np.float32))
    c = img.copy()
    c.data[0, 0] = 9.0
    assert img.data[0, 0] == 1.0


def test_rejects_bad_ndim():
    with pytest.raises(ValueError):
        AstroImage(np.zeros((2, 2, 3, 1), dtype=np.float32))
