import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.deconvolution import sharpen


def test_sharpen_changes_image_and_keeps_shape():
    data = np.random.rand(16, 16, 3).astype(np.float32)
    img = AstroImage(data)
    out = sharpen(img, 0.5)
    assert out.data.shape == (16, 16, 3)
    assert out.data.dtype == np.float32
    assert not np.allclose(out.data, data)
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0


def test_sharpen_increases_edge_contrast():
    data = np.zeros((16, 16), dtype=np.float32)
    data[:, 8:] = 0.5  # a step edge
    img = AstroImage(data)
    out = sharpen(img, 0.8)
    # sharpening overshoots at the edge -> larger local range than the input
    assert out.data.max() - out.data.min() >= 0.5


def test_sharpen_preserves_is_linear_and_mono():
    img = AstroImage(np.random.rand(16, 16).astype(np.float32), is_linear=True)
    out = sharpen(img, 0.3)
    assert out.is_linear is True
    assert out.data.ndim == 2
