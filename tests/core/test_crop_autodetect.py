import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.crop import detect_content_bounds, auto_crop


def _bordered():
    data = np.zeros((40, 50, 3), dtype=np.float32)
    data[5:35, 8:45] = 0.4  # content rectangle inside a black border
    return AstroImage(data)


def test_detect_bounds_finds_content_rect():
    assert detect_content_bounds(_bordered()) == (5, 35, 8, 45)


def test_auto_crop_removes_border():
    out = auto_crop(_bordered())
    assert out.data.shape == (30, 37, 3)
    assert out.data.min() > 0.0


def test_auto_crop_extra_margin():
    out = auto_crop(_bordered(), margin=0.10)
    assert out.data.shape[0] < 30 and out.data.shape[1] < 37


def test_auto_crop_preserves_is_linear():
    img = AstroImage(_bordered().data, is_linear=True)
    assert auto_crop(img).is_linear is True


def test_detect_bounds_all_black_returns_full():
    img = AstroImage(np.zeros((10, 12), dtype=np.float32))
    assert detect_content_bounds(img) == (0, 10, 0, 12)
