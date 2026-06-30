import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.local_contrast import enhance


def _img():
    rng = np.random.default_rng(0)
    return AstroImage(rng.random((48, 48, 3)).astype(np.float32), is_linear=False)


def test_enhance_changes_image_keeps_shape():
    img = _img()
    out = enhance(img, 0.6)
    assert out.data.shape == (48, 48, 3)
    assert out.data.dtype == np.float32
    assert not np.allclose(out.data, img.data)
    assert out.data.min() >= 0 and out.data.max() <= 1
    assert out.is_linear is False


def test_enhance_mono():
    img = AstroImage(np.random.default_rng(1).random((48, 48)).astype(np.float32))
    out = enhance(img, 0.5)
    assert out.data.ndim == 2
