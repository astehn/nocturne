import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.color import ColorSettings, apply_color


def test_neutralize_background_equalizes_channel_medians():
    # green background raised -> a color cast
    data = np.full((32, 32, 3), 0.1, dtype=np.float32)
    data[..., 1] = 0.2  # green higher
    img = AstroImage(data)
    out = apply_color(img, ColorSettings(neutralize_background=True, white_balance=False))
    meds = [float(np.median(out.data[..., c])) for c in range(3)]
    assert max(meds) - min(meds) < 1e-3


def test_white_balance_brings_channel_means_together():
    rng = np.random.default_rng(0)
    data = (rng.random((32, 32, 3)) * 0.6).astype(np.float32)  # headroom avoids clip noise
    data[..., 2] *= 0.4  # blue weak
    img = AstroImage(data)
    before = [float(data[..., c].mean()) for c in range(3)]
    out = apply_color(img, ColorSettings(neutralize_background=False, white_balance=True))
    after = [float(out.data[..., c].mean()) for c in range(3)]
    assert (max(after) - min(after)) < (max(before) - min(before))


def test_mono_is_noop():
    img = AstroImage(np.full((8, 8), 0.3, dtype=np.float32))
    out = apply_color(img, ColorSettings())
    assert out.data.ndim == 2
    assert np.allclose(out.data, img.data)


def test_preserves_is_linear_and_dtype():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=True)
    out = apply_color(img, ColorSettings())
    assert out.is_linear is True
    assert out.data.dtype == np.float32
    assert out.data.max() <= 1.0 and out.data.min() >= 0.0


def test_remove_green_clamps_green_excess():
    data = np.full((8, 8, 3), 0.3, dtype=np.float32)
    data[..., 1] = 0.8  # green excess
    out = apply_color(AstroImage(data),
                      ColorSettings(neutralize_background=False, white_balance=False,
                                    remove_green=True))
    assert out.data[..., 1].max() <= 0.3 + 1e-6  # clamped to (r+b)/2 = 0.3


def test_remove_green_function_clamps_green():
    from nocturne.core.color import remove_green
    data = np.full((8, 8, 3), 0.3, dtype=np.float32)
    data[..., 1] = 0.8  # green excess
    out = remove_green(AstroImage(data))
    assert out.data[..., 1].max() <= 0.3 + 1e-6           # clamped to (r+b)/2
    assert out.data[..., 0].max() <= 0.3 + 1e-6           # red untouched


def test_remove_green_leaves_non_green_pixel_untouched():
    from nocturne.core.color import remove_green
    data = np.zeros((2, 2, 3), dtype=np.float32)
    data[..., 0] = 0.5; data[..., 1] = 0.2; data[..., 2] = 0.5   # green already below avg
    out = remove_green(AstroImage(data))
    assert np.allclose(out.data[..., 1], 0.2)                     # unchanged


def test_remove_green_mono_is_noop():
    from nocturne.core.color import remove_green
    img = AstroImage(np.full((4, 4), 0.5, dtype=np.float32))
    out = remove_green(img)
    assert out.data.ndim == 2 and np.allclose(out.data, 0.5)


def test_remove_green_preserves_is_linear():
    from nocturne.core.color import remove_green
    img = AstroImage(np.full((4, 4, 3), 0.4, dtype=np.float32), is_linear=False)
    assert remove_green(img).is_linear is False
