import numpy as np
import tifffile
from PIL import Image
from seestar_processor.core.image import AstroImage
from seestar_processor.core.export import save_tiff, save_jpeg


def test_save_tiff_is_16bit_color(tmp_path):
    img = AstroImage(np.linspace(0, 1, 48, dtype=np.float32).reshape(4, 4, 3))
    out = tmp_path / "o.tiff"
    save_tiff(img, str(out))
    arr = tifffile.imread(str(out))
    assert arr.shape == (4, 4, 3)
    assert arr.dtype == np.uint16
    # full-range value preserved at the bright end
    assert arr.max() == 65535


def test_save_tiff_is_16bit_mono(tmp_path):
    img = AstroImage(np.full((4, 4), 0.5, dtype=np.float32))
    out = tmp_path / "m.tiff"
    save_tiff(img, str(out))
    arr = tifffile.imread(str(out))
    assert arr.shape == (4, 4)
    assert arr.dtype == np.uint16


def test_save_jpeg_roundtrips(tmp_path):
    img = AstroImage(np.full((4, 4, 3), 0.5, dtype=np.float32))
    out = tmp_path / "o.jpg"
    save_jpeg(img, str(out))
    with Image.open(out) as im:
        assert im.size == (4, 4)
