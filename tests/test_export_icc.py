"""Every export must declare what colour space it is in.

Andreas' M 16 TIFF rendered differently in Photoshop. The FILE WAS CORRECT —
verified by rendering its raw pixel values, which reproduced the app preview
exactly. What it lacked was a declaration, so Photoshop assigned its own working
space and rendered a file encoded for sRGB as if it were ProPhoto.
"""
import numpy as np
import pytest

from nocturne.core.export import save_jpeg, save_png, save_tiff
from nocturne.core.image import AstroImage


def _img(h=32, w=48):
    rng = np.random.default_rng(0)
    return AstroImage((rng.random((h, w, 3)) * 0.6 + 0.2).astype(np.float32),
                      is_linear=False, metadata={})


def _icc():
    from nocturne.colour_profiles import icc_bytes
    return icc_bytes("sRGB")


def test_a_tiff_carries_the_profile(tmp_path):
    import tifffile
    p = tmp_path / "a.tiff"
    save_tiff(_img(), str(p), icc=_icc())
    with tifffile.TiffFile(str(p)) as tf:
        tags = {t.name: t.value for t in tf.pages[0].tags.values()}
    assert "InterColorProfile" in tags, f"no ICC tag; got {sorted(tags)}"
    assert bytes(tags["InterColorProfile"])[36:40] == b"acsp"


def test_a_png_carries_the_profile(tmp_path):
    from PIL import Image
    p = tmp_path / "a.png"
    save_png(_img(), str(p), icc=_icc())
    with Image.open(str(p)) as im:
        assert im.info.get("icc_profile"), "PNG has no embedded profile"


def test_a_jpeg_carries_the_profile(tmp_path):
    from PIL import Image
    p = tmp_path / "a.jpg"
    save_jpeg(_img(), str(p), icc=_icc())
    with Image.open(str(p)) as im:
        assert im.info.get("icc_profile"), "JPEG has no embedded profile"


@pytest.mark.parametrize("saver,ext", [(save_tiff, ".tiff"), (save_png, ".png"),
                                       (save_jpeg, ".jpg")])
def test_the_pixels_are_unchanged_by_tagging(tmp_path, saver, ext):
    """Assert-UNCHANGED. Embedding a profile must not touch a single pixel —
    otherwise every existing file silently shifts, which is precisely the
    complaint this work started from.
    """
    from PIL import Image
    img = _img()
    bare, tagged = tmp_path / f"bare{ext}", tmp_path / f"tag{ext}"
    saver(img, str(bare))
    saver(img, str(tagged), icc=_icc())
    with Image.open(str(bare)) as a, Image.open(str(tagged)) as b:
        assert np.array_equal(np.array(a), np.array(b)), "tagging changed the pixels"


@pytest.mark.parametrize("saver,ext", [(save_tiff, ".tiff"), (save_png, ".png"),
                                       (save_jpeg, ".jpg")])
def test_no_profile_still_works(tmp_path, saver, ext):
    """icc=None is the old behaviour, and batch or a future caller may pass
    nothing. It must write a readable file rather than fail."""
    from PIL import Image
    p = tmp_path / f"n{ext}"
    saver(_img(), str(p), icc=None)
    with Image.open(str(p)) as im:
        assert im.size == (48, 32)
