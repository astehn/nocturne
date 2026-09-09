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


@pytest.mark.parametrize("w", [1080, 3285, 101, 102, 103, 104])
def test_qimage_round_trip_survives_scanline_padding(w):
    """Qt pads every scanline to a 4-byte boundary, so bytesPerLine() is width*3
    only when the width is a multiple of 4.

    The old inline conversion in _annotated_rgb8 divided bytesPerLine() by 3, so
    Share crashed on any image whose width was not a multiple of 4 — three
    widths in four. It never showed on a native Seestar frame, which is 1080
    wide; it took a cropped drizzle to surface it:

        ValueError: cannot reshape array of size 40478592 into shape (4107,3285,3)
    """
    import numpy as np
    from nocturne.ui.preview import qimage_to_rgb8, rgb_to_qimage

    rng = np.random.default_rng(w)
    src = rng.integers(0, 256, (7, w, 3), dtype=np.uint8)
    back = qimage_to_rgb8(rgb_to_qimage(src))

    assert back.shape == src.shape
    assert np.array_equal(back, src), "the round trip must be lossless"
