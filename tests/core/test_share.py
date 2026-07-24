import pytest
from nocturne.core.share import caption_line, centered_crop, share_filename, ASPECTS

def test_caption_all_fields():
    meta = {"target": "NGC 7000", "livetime": 3600.0, "exposure": 20.0, "frames": 180,
            "date": "2026-07-16T01:31:01"}
    line = caption_line(meta, "andreas")
    assert line == "NGC 7000 · 1h 00m · 180 × 20s · 2026-07-16 · @andreas"

def test_caption_omits_missing_and_blank_handle():
    assert caption_line({"target": "M31"}, "") == "M31"
    assert "@" not in caption_line({"target": "M31"}, "")

def test_caption_handle_at_optional():
    assert caption_line({"target": "M31"}, "@astro").endswith("@astro")  # not @@astro

def test_caption_empty_when_no_data():
    assert caption_line({}, "") == ""

def test_centered_crop_full_when_none():
    assert centered_crop(100, 200, None) == (0, 200, 0, 100)

def test_centered_crop_square_on_tall():
    # 100x200 tall frame, 1:1 → 100x100 centered vertically
    assert centered_crop(100, 200, 1.0) == (50, 150, 0, 100)

def test_centered_crop_landscape_on_square():
    # 200x200, 16:9 → limited by width → 200x112 (round(200/1.777)=113) centered
    top, bottom, left, right = centered_crop(200, 200, 16/9)
    assert (left, right) == (0, 200)
    assert bottom - top == round(200 / (16/9))

def test_share_filename():
    assert share_filename("NGC7000_182x20s_61min.fits", "4:5") == "NGC7000_182x20s_61min_4x5.jpg"
    assert share_filename(None, "1:1") == "share_1x1.jpg"

def test_aspects_are_width_over_height():
    d = dict(ASPECTS)
    assert d["Original"] is None and d["1:1"] == 1.0
    assert abs(d["9:16"] - 9/16) < 1e-9


import numpy as np

@pytest.fixture(scope="module")
def _qapp():
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])

def _grad(h, w):
    a = np.zeros((h, w, 3), np.uint8)
    a[..., 0] = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
    return a

def test_compose_crop_and_downscale(_qapp):
    from nocturne.core.share import compose_share, centered_crop
    img = _grad(500, 400)                       # tall 400x500
    crop = centered_crop(400, 500, 1.0)         # → 400x400
    out = compose_share(img, crop, "", longest_edge=200)
    assert out.width() == 200 and out.height() == 200   # square, downscaled

def test_compose_never_upscales(_qapp):
    from nocturne.core.share import compose_share
    img = _grad(100, 100)
    out = compose_share(img, (0, 100, 0, 100), "", longest_edge=2048)
    assert out.width() == 100 and out.height() == 100

def test_compose_band_darkens_bottom_only_with_caption(_qapp):
    from nocturne.core.share import compose_share
    img = _grad(300, 300); img[:] = 200          # uniform bright
    plain = compose_share(img, (0, 300, 0, 300), "", longest_edge=300)
    capped = compose_share(img, (0, 300, 0, 300), "NGC 7000 · @me", longest_edge=300)
    # bottom band row is darker with a caption; a top row is unchanged
    def lum(qi, y):
        c = qi.pixelColor(qi.width() // 2, y)
        return c.red() + c.green() + c.blue()
    assert lum(capped, 295) < lum(plain, 295)     # band burned at the bottom
    assert lum(capped, 5) == lum(plain, 5)        # top untouched

def test_compose_accepts_mono(_qapp):
    from nocturne.core.share import compose_share
    mono = (np.ones((120, 120), np.uint8) * 128)
    out = compose_share(mono, (0, 120, 0, 120), "", longest_edge=120)
    assert out.width() == 120 and out.height() == 120

def test_save_share_jpeg(_qapp, tmp_path):
    from nocturne.core.share import compose_share, save_share_jpeg
    out = compose_share(_grad(64, 64), (0, 64, 0, 64), "", longest_edge=64)
    p = tmp_path / "s.jpg"
    save_share_jpeg(out, str(p))
    assert p.exists() and p.stat().st_size > 0
