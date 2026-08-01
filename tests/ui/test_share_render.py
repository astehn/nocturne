"""Qt-side Share rendering. These moved out of tests/core/test_share.py when
core/share.py was split: they exercise QImage compositing and file IO, which is
UI-layer work and was the reason core/ was importing PySide6 at all."""
import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.core.share import centered_crop  # noqa: E402  (pure half)
from nocturne.ui.share_render import (  # noqa: E402
    compose_share, qimage_from_rgb8, save_share, save_share_jpeg, to_clipboard,
)


def _grad(h, w):
    a = np.zeros((h, w, 3), np.uint8)
    a[..., 0] = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
    a[..., 1] = np.linspace(0, 255, h, dtype=np.uint8)[:, None]
    return a


def test_compose_crop_and_downscale(qapp):
    img = _grad(500, 400)                       # tall 400x500
    crop = centered_crop(400, 500, 1.0)         # → 400x400
    out = compose_share(img, crop, "", longest_edge=200)
    assert out.width() == 200 and out.height() == 200   # square, downscaled


def test_compose_never_upscales(qapp):
    img = _grad(100, 100)
    out = compose_share(img, (0, 100, 0, 100), "", longest_edge=2048)
    assert out.width() == 100 and out.height() == 100


def test_compose_band_darkens_bottom_only_with_caption(qapp):
    img = _grad(300, 300); img[:] = 200          # uniform bright
    plain = compose_share(img, (0, 300, 0, 300), "", longest_edge=300)
    capped = compose_share(img, (0, 300, 0, 300), "NGC 7000 · @me", longest_edge=300)
    # bottom band row is darker with a caption; a top row is unchanged
    def lum(qi, y):
        c = qi.pixelColor(qi.width() // 2, y)
        return c.red() + c.green() + c.blue()
    assert lum(capped, 295) < lum(plain, 295)     # band burned at the bottom
    assert lum(capped, 5) == lum(plain, 5)        # top untouched


def test_compose_accepts_mono(qapp):
    mono = (np.ones((120, 120), np.uint8) * 128)
    out = compose_share(mono, (0, 120, 0, 120), "", longest_edge=120)
    assert out.width() == 120 and out.height() == 120


def test_save_share_jpeg(qapp, tmp_path):
    out = compose_share(_grad(64, 64), (0, 64, 0, 64), "", longest_edge=64)
    p = tmp_path / "s.jpg"
    save_share_jpeg(out, str(p))
    assert p.exists() and p.stat().st_size > 0
