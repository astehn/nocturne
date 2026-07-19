import numpy as np
import pytest
from nocturne.core.image import AstroImage

pytest.importorskip("PySide6")
from nocturne.ui.preview import to_qimage  # noqa: E402


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


def test_unlinked_neutralizes_tint_on_linear(qapp):
    img = _tinted_linear()
    linked_spread = np.ptp(_channel_medians(to_qimage(img, unlinked=False)))
    unlinked_spread = np.ptp(_channel_medians(to_qimage(img, unlinked=True)))
    assert unlinked_spread < linked_spread


def test_unlinked_is_noop_when_not_linear(qapp):
    data = _tinted_linear().data
    img = AstroImage(data, is_linear=False)
    a = to_qimage(img, unlinked=False)
    b = to_qimage(img, unlinked=True)
    assert a == b  # QImage equality: identical pixels
