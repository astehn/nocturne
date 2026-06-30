import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.color import ColorSettings, apply_color


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
