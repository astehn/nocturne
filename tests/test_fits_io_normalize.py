import numpy as np
from astropy.io import fits
from nocturne.core.fits_io import load_fits


def _write_color(path, peak):
    # (3, H, W) cube the loader reads as color (no debayer); values scaled to `peak`.
    data = np.zeros((3, 8, 10), np.float32)
    data[:, 2:6, 3:7] = peak
    fits.PrimaryHDU(data).writeto(str(path), overwrite=True)


def test_load_fits_default_normalizes(tmp_path):
    p = tmp_path / "n.fits"
    _write_color(p, 1000.0)
    img = load_fits(str(p))            # default normalize=True
    assert img.data.max() <= 1.0 + 1e-6


def test_load_fits_no_normalize_keeps_raw(tmp_path):
    p = tmp_path / "r.fits"
    _write_color(p, 1000.0)
    img = load_fits(str(p), normalize=False)
    assert img.data.max() > 500.0     # raw ADU preserved, not divided to 0..1
