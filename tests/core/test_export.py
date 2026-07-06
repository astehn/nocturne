import numpy as np
import tifffile
from PIL import Image
from nocturne.core.image import AstroImage
from nocturne.core.export import save_tiff, save_jpeg, save_png, save_fits


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


def test_save_png(tmp_path):
    img = AstroImage(np.full((4, 4, 3), 0.5, dtype=np.float32))
    out = tmp_path / "o.png"
    save_png(img, str(out))
    with Image.open(out) as im:
        assert im.size == (4, 4) and im.format == "PNG"


def test_save_fits_roundtrips_float(tmp_path):
    from astropy.io import fits as _fits
    img = AstroImage(np.linspace(0, 1, 48, dtype=np.float32).reshape(4, 4, 3))
    out = tmp_path / "o.fits"
    save_fits(img, str(out))
    with _fits.open(out) as h:
        assert h[0].data.shape == (3, 4, 4)
        # FITS reads back as big-endian float32 (>f4); check kind + width.
        assert h[0].data.dtype.kind == "f" and h[0].data.dtype.itemsize == 4
