import numpy as np
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
