import numpy as np
from nocturne.core.image import AstroImage
from nocturne.steps.local_contrast import LocalContrastStep


def test_local_contrast_step_float_amount():
    img = AstroImage(np.random.default_rng(0).random((32, 32, 3)).astype(np.float32))
    out = LocalContrastStep().apply(img, 0.6)
    assert out.data.shape == (32, 32, 3)
    assert not np.allclose(out.data, img.data)


def test_local_contrast_step_legacy_string():
    img = AstroImage(np.random.default_rng(0).random((32, 32, 3)).astype(np.float32))
    out = LocalContrastStep().apply(img, "medium")
    assert out.data.shape == (32, 32, 3)
    assert not np.allclose(out.data, img.data)


def test_local_contrast_step_options_empty():
    assert LocalContrastStep().options() == []
    assert LocalContrastStep().default_option() == ""


def test_local_contrast_step_zero_is_noop():
    img = AstroImage(np.random.default_rng(0).random((16, 16, 3)).astype(np.float32))
    out = LocalContrastStep().apply(img, 0.0)
    assert np.allclose(out.data, np.clip(img.data, 0.0, 1.0))
