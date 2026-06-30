import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.crop import CropSettings, apply_crop


def _img(h, w, ch=3):
    shape = (h, w, ch) if ch else (h, w)
    return AstroImage(np.random.rand(*shape).astype(np.float32))


def test_default_settings_is_noop():
    img = _img(10, 20)
    out = apply_crop(img, CropSettings())
    assert out.data.shape == (10, 20, 3)
    assert np.allclose(out.data, img.data)


def test_trim_edges_10_percent():
    img = _img(100, 100)
    out = apply_crop(img, CropSettings(trim="10%"))
    assert out.data.shape == (80, 80, 3)


def test_aspect_1_1_center_crops_wide_image():
    img = _img(100, 200)  # wide
    out = apply_crop(img, CropSettings(aspect="1:1"))
    assert out.data.shape == (100, 100, 3)


def test_aspect_16_9_on_square():
    img = _img(180, 180)
    out = apply_crop(img, CropSettings(aspect="16:9"))
    h, w, _ = out.data.shape
    assert w == 180
    assert h == 101  # round(180 * 9/16)


def test_rotate_90_swaps_dimensions():
    img = _img(10, 20)
    out = apply_crop(img, CropSettings(rotate=90))
    assert out.data.shape == (20, 10, 3)


def test_flip_horizontal_reverses_columns():
    img = _img(4, 4)
    out = apply_crop(img, CropSettings(flip_h=True))
    assert np.allclose(out.data, img.data[:, ::-1])


def test_flip_vertical_reverses_rows():
    img = _img(4, 4)
    out = apply_crop(img, CropSettings(flip_v=True))
    assert np.allclose(out.data, img.data[::-1, :])


def test_preserves_is_linear_and_mono():
    img = AstroImage(np.random.rand(10, 20).astype(np.float32), is_linear=False)
    out = apply_crop(img, CropSettings(aspect="1:1"))
    assert out.is_linear is False
    assert out.data.ndim == 2
    assert out.data.shape == (10, 10)


def test_output_is_float32_contiguous():
    img = _img(10, 20)
    out = apply_crop(img, CropSettings(rotate=90, flip_h=True))
    assert out.data.dtype == np.float32
    assert out.data.flags["C_CONTIGUOUS"]
