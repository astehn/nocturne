import numpy as np
import tifffile
from PIL import Image
from nocturne.core.image import AstroImage
from nocturne.core.export import save_tiff, save_jpeg, save_png, save_fits


def test_save_tiff_is_16bit_color(tmp_path):
    # is_linear=False: this checks the BIT DEPTH, and a real export happens
    # after Stretch, which clears the flag. Left linear (the AstroImage default)
    # the picture formats now autostretch it, exactly as the canvas does, and
    # the full-range value under test is no longer the thing being measured.
    img = AstroImage(np.linspace(0, 1, 48, dtype=np.float32).reshape(4, 4, 3),
                     is_linear=False)
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


# --- a picture file must match the canvas (2026-09-01) -----------------------

def test_exporting_a_linear_image_gives_what_the_canvas_showed(tmp_path):
    """Reaching Export without running Stretch wrote a file about 10x darker
    than the picture on screen — measured on a faint linear frame, canvas mean
    61.7 of 255 against a file mean of 6.4. It looks like a black image and
    nothing says why.

    CLAUDE.md: "The preview at any step must equal what export would produce."
    """
    from nocturne.ui.preview import to_rgb8
    rng = np.random.default_rng(0)
    linear = AstroImage((rng.random((32, 32, 3)) * 0.03 + 0.01).astype(np.float32),
                        is_linear=True)
    out = tmp_path / "linear.png"
    save_png(linear, str(out))
    written = np.asarray(Image.open(str(out)).convert("RGB"), dtype=np.float32)
    canvas = to_rgb8(linear).astype(np.float32)
    assert abs(written.mean() - canvas.mean()) <= 1.0, (
        f"file mean {written.mean():.1f} vs canvas {canvas.mean():.1f}")


def test_a_stretched_image_is_exported_untouched(tmp_path):
    """The overwhelmingly common case, and the one that must not change: after
    Stretch the flag is cleared, so nothing is applied twice."""
    data = np.linspace(0.0, 1.0, 3072, dtype=np.float32).reshape(32, 32, 3)
    img = AstroImage(data, is_linear=False)
    out = tmp_path / "stretched.png"
    save_png(img, str(out))
    written = np.asarray(Image.open(str(out)).convert("RGB"), dtype=np.float32)
    expected = np.clip(data, 0, 1) * 255
    assert np.abs(written - expected).max() <= 1.0, "a stretched image was altered"


def test_fits_export_keeps_linear_data_linear(tmp_path):
    """FITS carries DATA, not a picture. Autostretching it would destroy the
    thing a FITS is for, and the header records that it is linear."""
    from astropy.io import fits as _fits
    rng = np.random.default_rng(1)
    data = (rng.random((16, 16, 3)) * 0.03 + 0.01).astype(np.float32)
    img = AstroImage(data.copy(), is_linear=True)
    out = tmp_path / "linear.fits"
    save_fits(img, str(out))
    back = np.transpose(_fits.getdata(str(out)), (1, 2, 0))
    assert np.abs(back - data).max() < 1e-6, "FITS export altered linear data"
