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


# --- F3: the slider's preview reuses the CLAHE; the picture must not move ---

def _today_enhance(img, amount):
    """enhance as it stood before the split (2026-10-06), frozen as the reference."""
    from skimage.exposure import equalize_adapthist
    amount = float(np.clip(amount, 0.0, 1.0))
    if amount == 0.0:
        return img.data.copy()
    data = np.clip(img.data, 0.0, 1.0).astype(np.float32)
    if data.ndim == 2:
        clahe = equalize_adapthist(data, clip_limit=0.01).astype(np.float32)
        return np.clip(data * (1 - amount) + clahe * amount, 0.0, 1.0).astype(np.float32)
    lum = data.mean(axis=2)
    clahe = equalize_adapthist(lum, clip_limit=0.01).astype(np.float32)
    new_lum = lum * (1 - amount) + clahe * amount
    ratio = new_lum / np.maximum(lum, 1e-6)
    return np.clip(data * ratio[..., None], 0.0, 1.0).astype(np.float32)


def _bases():
    rng = np.random.default_rng(9)
    col = (rng.random((70, 110, 3)) ** 2).astype(np.float32)
    col[10:40, 20:70] *= 0.3
    col[0, 0] = (-0.1, 1.3, 2e-7)
    return [AstroImage(col, is_linear=False, metadata={"k": 1}),
            AstroImage((col.mean(axis=2) * 1.1).astype(np.float32), is_linear=False)]


def test_prepared_path_equals_todays_function_bit_for_bit():
    from nocturne.core.local_contrast import apply_prepared, prepare
    for img in _bases():
        before = img.data.copy()
        prepared = prepare(img)
        for amount in (0.0, 0.2, 0.5, 1.0, 1.3):
            want = _today_enhance(img, amount)
            assert np.array_equal(apply_prepared(img, prepared, amount).data, want), amount
            assert np.array_equal(enhance(img, amount).data, want), amount
        assert np.array_equal(img.data, before), "the base is not written to"
