import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.crop import CropParams, apply_crop_params


def test_bounds_crop():
    data = (np.arange(40 * 50 * 3, dtype=np.float32).reshape(40, 50, 3)) / 1e4
    out = apply_crop_params(AstroImage(data), CropParams(bounds=(5, 35, 8, 45)))
    assert out.data.shape == (30, 37, 3)


def test_rotate_then_shape():
    out = apply_crop_params(AstroImage(np.zeros((10, 20, 3), np.float32)),
                            CropParams(rotate=90))
    assert out.data.shape == (20, 10, 3)


def test_flip_horizontal():
    data = np.random.rand(4, 4, 3).astype(np.float32)
    out = apply_crop_params(AstroImage(data), CropParams(flip_h=True))
    assert np.allclose(out.data, data[:, ::-1])


def test_aspect_centers_crop():
    out = apply_crop_params(AstroImage(np.zeros((100, 200, 3), np.float32)),
                            CropParams(aspect="1:1"))
    assert out.data.shape == (100, 100, 3)


def test_default_identity():
    data = np.random.rand(8, 8, 3).astype(np.float32)
    out = apply_crop_params(AstroImage(data), CropParams())
    assert np.allclose(out.data, data)


def test_preserves_is_linear():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=False)
    out = apply_crop_params(img, CropParams(bounds=(1, 7, 1, 7)))
    assert out.is_linear is False
    assert out.data.dtype == np.float32
