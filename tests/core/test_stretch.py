import numpy as np
import pytest
from seestar_processor.core.image import AstroImage
from seestar_processor.core.stretch import apply_stretch, STRETCH_PRESETS


def test_stretch_marks_nonlinear_and_brightens():
    data = np.linspace(0, 0.1, 64, dtype=np.float32).reshape(8, 8)
    img = AstroImage(data.copy())
    out = apply_stretch(img, "Medium")
    assert out.is_linear is False
    assert out is not img
    assert np.median(out.data) > np.median(data)
    assert out.data.max() <= 1.0


def test_larger_preset_brightens_more():
    data = np.full((8, 8), 0.05, dtype=np.float32)
    small = apply_stretch(AstroImage(data.copy()), "Small")
    large = apply_stretch(AstroImage(data.copy()), "Large")
    assert np.median(large.data) > np.median(small.data)


def test_unknown_preset_raises():
    with pytest.raises(ValueError):
        apply_stretch(AstroImage(np.zeros((4, 4), np.float32)), "Huge")
