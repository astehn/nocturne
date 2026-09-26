import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.local_contrast import enhance


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


def test_zero_amount_is_an_exact_identity():
    """0 is the slider's default and "no change". It used to rescale by
    lum / max(lum, 1e-6), which moved every pixel darker than 1e-6 and
    rounded the rest. Bit for bit, including near-black pixels."""
    import numpy as np
    from nocturne.core.image import AstroImage
    rng = np.random.default_rng(4)
    data = rng.random((48, 48, 3), dtype=np.float32)
    data[:4, :4] = 3e-7                         # below the 1e-6 guard
    img = AstroImage(data.copy(), is_linear=False)
    assert np.array_equal(enhance(img, 0.0).data, data)
    assert not np.array_equal(enhance(img, 0.3).data, data)
