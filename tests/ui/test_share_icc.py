"""The write paths that do NOT go through core/export.

Share and the annotated PNG save a QImage directly. Fixing only core/export
would have left the Share tool — the one aimed at posting images publicly —
writing untagged files, which is the case that matters most for anything shared
onward. Found while self-reviewing the design, not by the tests.
"""
import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QImage  # noqa: E402


def _qimage(w=24, h=16):
    img = QImage(w, h, QImage.Format.Format_RGB888)
    img.fill(0x336699)
    return img


@pytest.mark.parametrize("ext", [".png", ".jpg"])
def test_share_output_carries_a_profile(tmp_path, ext):
    from PIL import Image
    from nocturne.ui.share_render import save_share
    p = tmp_path / f"share{ext}"
    save_share(_qimage(), str(p))
    with Image.open(str(p)) as im:
        assert im.info.get("icc_profile"), f"{ext} from Share is untagged"


def test_share_jpeg_helper_carries_a_profile(tmp_path):
    """save_share_jpeg is kept for callers that specifically want JPEG, so it
    needs the same treatment — a second door into the same room."""
    from PIL import Image
    from nocturne.ui.share_render import save_share_jpeg
    p = tmp_path / "s.jpg"
    save_share_jpeg(_qimage(), str(p))
    with Image.open(str(p)) as im:
        assert im.info.get("icc_profile"), "save_share_jpeg is untagged"


def test_share_declares_srgb_specifically(tmp_path):
    """Not just any profile. Share is for posting to the web, where sRGB is what
    every browser assumes — tagging it anything else would make it render
    differently in exactly the place it is meant to be seen."""
    from PIL import Image
    from nocturne.colour_profiles import icc_bytes
    from nocturne.ui.share_render import save_share
    p = tmp_path / "s.png"
    save_share(_qimage(), str(p))
    with Image.open(str(p)) as im:
        assert im.info["icc_profile"] == icc_bytes("sRGB")


def test_the_annotated_png_carries_a_profile(qtbot, tmp_path):
    """The second QImage path. A plain PNG export and an annotated one go
    through completely different code, so an untagged annotated PNG would ship
    while the plain one was fixed — and both are the same Export button to the
    user."""
    import numpy as np
    from PIL import Image
    from nocturne.core.image import AstroImage
    from nocturne.ui.preview import to_qimage
    from nocturne.colour_profiles import qt_colour_space

    a = AstroImage((np.zeros((16, 16, 3)) + 0.4).astype(np.float32),
                   is_linear=False, metadata={})
    out = to_qimage(a)
    out.setColorSpace(qt_colour_space("sRGB"))
    p = tmp_path / "ann.png"
    out.save(str(p))
    with Image.open(str(p)) as im:
        assert im.info.get("icc_profile"), "annotated PNG is untagged"
