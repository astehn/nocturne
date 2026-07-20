import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.deconvolution import sharpen


def test_sharpen_changes_image_and_keeps_shape():
    rng = np.random.default_rng(1)
    data = rng.random((16, 16, 3)).astype(np.float32)
    img = AstroImage(data)
    out = sharpen(img, 0.5)
    assert out.data.shape == (16, 16, 3)
    assert out.data.dtype == np.float32
    assert np.mean(np.abs(out.data - data)) > 1e-3  # meaningfully sharpened
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


def test_sharpen_output_is_finite_after_curve_build():
    # Regression: building a curve LUT upstream can leave a sticky CPU FP flag
    # that made skimage's unsharp_mask return NaN on the next call. sharpen must
    # still emit only finite pixels (never NaN reaching an export).
    from nocturne.core.curves import build_lut
    build_lut([(0.0, 0.0), (0.15, 0.15), (0.45, 0.40), (0.79, 0.84), (1.0, 1.0)])
    data = np.random.default_rng(1).random((16, 16, 3)).astype(np.float32)
    out = sharpen(AstroImage(data), 0.5)
    assert np.all(np.isfinite(out.data))
