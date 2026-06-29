import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.autostretch import autostretch


def test_autostretch_brightens_dark_image_without_mutating():
    data = np.full((8, 8), 0.02, dtype=np.float32)
    data[0, 0] = 0.9
    img = AstroImage(data.copy())
    out = autostretch(img)
    assert out.shape == data.shape
    assert out.dtype == np.float32
    assert out.min() >= 0.0 and out.max() <= 1.0
    # median should be lifted well above the original 0.02
    assert np.median(out) > 0.1
    # original image is untouched
    assert np.allclose(img.data, data)


def test_autostretch_color_per_channel_without_mutating():
    data = np.full((8, 8, 3), 0.02, dtype=np.float32)
    data[0, 0, :] = 0.9
    img = AstroImage(data.copy())
    out = autostretch(img)
    assert out.shape == (8, 8, 3)
    assert out.dtype == np.float32
    assert out.min() >= 0.0 and out.max() <= 1.0
    # each channel's median is lifted above the original 0.02
    for ch in range(3):
        assert np.median(out[..., ch]) > 0.1
    # original image is untouched
    assert np.allclose(img.data, data)
