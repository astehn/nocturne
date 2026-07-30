import numpy as np
import pytest
from nocturne.core.image import AstroImage

pytest.importorskip("PySide6")
from nocturne.ui.preview import to_qimage, to_rgb8  # noqa: E402


def test_to_qimage_dimensions(qapp):
    img = AstroImage(np.random.rand(6, 10, 3).astype(np.float32))
    qimg = to_qimage(img)
    assert qimg.width() == 10
    assert qimg.height() == 6


def test_to_qimage_mono(qapp):
    img = AstroImage(np.random.rand(6, 10).astype(np.float32))
    qimg = to_qimage(img)
    assert qimg.width() == 10


def _channel_medians(qimg):
    w, h = qimg.width(), qimg.height()
    bpl = qimg.bytesPerLine()
    buf = np.frombuffer(qimg.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)
    arr = buf[:, : w * 3].reshape(h, w, 3)
    return np.array([np.median(arr[..., c]) for c in range(3)], dtype=float)


def _tinted_linear():
    rng = np.random.default_rng(0)
    data = np.zeros((8, 12, 3), np.float32)
    data[..., 0] = 0.02 + rng.random((8, 12)) * 0.01  # R low
    data[..., 1] = 0.05 + rng.random((8, 12)) * 0.01  # G mid
    data[..., 2] = 0.12 + rng.random((8, 12)) * 0.01  # B elevated -> blue cast
    return AstroImage(data, is_linear=True)


def test_preview_neutralizes_tint_on_linear(qapp):
    # The display stretch is per-channel (unlinked), so a tinted linear image
    # renders with a near-neutral background — no single channel is crushed.
    spread = np.ptp(_channel_medians(to_qimage(_tinted_linear())))
    assert spread < 20.0  # channel medians close together (0..255 scale)


def test_to_rgb8_treats_nan_as_zero_without_warning(qapp, recwarn):
    # fits_io._normalize() can leave NaN untouched (when arr.max() is NaN), so
    # the canvas must not blow up or warn on the uint8 cast — it should render
    # NaN pixels as 0, matching histogram._counts_256's convention.
    data = np.full((4, 5, 3), 0.5, np.float32)
    data[0, 0, 0] = np.nan
    img = AstroImage(data, is_linear=False)
    rgb = to_rgb8(img)
    assert rgb[0, 0, 0] == 0
    assert not any(issubclass(w.category, RuntimeWarning) for w in recwarn.list)
