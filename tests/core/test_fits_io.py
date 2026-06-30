import numpy as np
import pytest
from astropy.io import fits
from seestar_processor.core.fits_io import load_fits


def _write(path, arr):
    fits.PrimaryHDU(arr).writeto(path, overwrite=True)


def test_loads_planar_color_as_hwc(tmp_path):
    arr = np.random.randint(0, 4096, size=(3, 16, 16)).astype(np.uint16)
    p = tmp_path / "color.fits"
    _write(str(p), arr)
    img = load_fits(str(p))
    assert img.is_color is True
    assert img.data.shape == (16, 16, 3)
    assert img.data.max() <= 1.0
    assert img.is_linear is True


def test_debayers_mono_to_color(tmp_path):
    arr = np.random.randint(0, 4096, size=(16, 16)).astype(np.uint16)
    p = tmp_path / "mono.fits"
    _write(str(p), arr)
    img = load_fits(str(p))
    assert img.is_color is True
    assert img.data.shape == (16, 16, 3)
    assert img.data.dtype == np.float32
    assert img.data.max() <= 1.0 and img.data.min() >= 0.0
    assert img.is_linear is True


def test_all_zero_image_does_not_divide_by_zero(tmp_path):
    arr = np.zeros((16, 16), dtype=np.uint16)
    p = tmp_path / "zero.fits"
    _write(str(p), arr)
    img = load_fits(str(p))
    assert np.all(np.isfinite(img.data))
    assert img.data.max() == 0.0


def test_metadata_parsed_from_header(tmp_path):
    from seestar_processor.core.fits_io import format_metadata
    arr = np.random.randint(0, 4096, size=(3, 16, 16)).astype(np.uint16)
    hdu = fits.PrimaryHDU(arr)
    hdu.header["EXPTIME"] = 30.0
    hdu.header["OBJECT"] = "M31"
    hdu.header["STACKCNT"] = 120
    p = tmp_path / "m.fits"
    hdu.writeto(str(p), overwrite=True)
    img = load_fits(str(p))
    assert img.metadata["exposure"] == 30.0
    assert img.metadata["target"] == "M31"
    assert img.metadata["frames"] == 120
    assert img.metadata["width"] == 16 and img.metadata["height"] == 16
    summary = format_metadata(img.metadata)
    assert "M31" in summary and "30" in summary


def test_unsupported_3d_shape_raises(tmp_path):
    arr = np.zeros((5, 16, 16), dtype=np.uint16)
    p = tmp_path / "bad.fits"
    _write(str(p), arr)
    with pytest.raises(ValueError):
        load_fits(str(p))
