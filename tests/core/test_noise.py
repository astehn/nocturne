import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.noise import reduce_noise


def _noisy(h=32, w=32, ch=3, seed=0):
    rng = np.random.default_rng(seed)
    base = np.full((h, w, ch) if ch else (h, w), 0.5, dtype=np.float32)
    noise = rng.normal(0, 0.15, base.shape).astype(np.float32)
    return AstroImage(np.clip(base + noise, 0, 1).astype(np.float32))


def test_reduce_noise_lowers_std():
    img = _noisy()
    out = reduce_noise(img, 0.8)
    assert out.data.std() < img.data.std()
    assert out.data.shape == img.data.shape
    assert out.data.dtype == np.float32


def test_reduce_noise_mono():
    img = _noisy(ch=0)
    out = reduce_noise(img, 0.5)
    assert out.data.ndim == 2
    assert out.data.std() < img.data.std()


def test_preserves_is_linear_and_range():
    img = AstroImage(_noisy().data, is_linear=True)
    out = reduce_noise(img, 0.5)
    assert out.is_linear is True
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0
