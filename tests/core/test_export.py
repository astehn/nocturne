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


def test_export_paints_a_nan_pixel_the_same_black_the_canvas_shows():
    """WYSIWYG: np.clip leaves NaN as NaN and casting NaN to uint is undefined,
    so export used to write whatever that platform's conversion produced while
    the canvas (which guards) showed black. Both must be 0."""
    import warnings
    from nocturne.core.export import _to_uint
    data = np.full((4, 4, 3), 0.5, np.float32)
    data[1, 1, 0] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)   # the invalid-cast warning
        out = _to_uint(data, 16)
    assert out[1, 1, 0] == 0, "a NaN pixel exports as black, as the canvas shows it"
    assert out[0, 0, 0] == 32768, "ordinary pixels are unaffected"


def test_export_and_canvas_agree_pixel_for_pixel_on_a_nan_frame():
    """The invariant that matters is agreement, not either value alone.

    Honest about its own strength: removing export's guard does NOT fail this on
    macOS/ARM, because the undefined NaN→uint cast happens to yield 0 here too.
    That is precisely why it is undefined and must not be relied on — on a
    platform where it yields 255 this test is the one that catches it. The test
    above is the guard with teeth everywhere, via the RuntimeWarning."""
    from nocturne.core.export import _to_uint
    from nocturne.ui.preview import to_rgb8
    from nocturne.core.image import AstroImage
    data = np.full((4, 4, 3), 0.5, np.float32)
    data[2, 3, 2] = np.nan
    img = AstroImage(data, is_linear=False)      # non-linear: no autostretch
    assert np.array_equal(to_rgb8(img), _to_uint(data, 8))
