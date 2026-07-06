import numpy as np
import pytest
from nocturne.core.image import AstroImage
from nocturne.core.export import save_tiff, save_fits
from nocturne.core.fits_io import load_master


def _color():
    return AstroImage((np.random.rand(6, 8, 3)).astype(np.float32), is_linear=True)


def test_load_master_tiff_roundtrip(tmp_path):
    p = tmp_path / "m.tiff"
    save_tiff(_color(), str(p))
    img = load_master(str(p))
    assert img.data.shape == (6, 8, 3)
    assert img.data.max() <= 1.0 + 1e-6


def test_load_master_fits_roundtrip(tmp_path):
    p = tmp_path / "m.fits"
    save_fits(_color(), str(p))
    img = load_master(str(p))
    assert img.data.shape == (6, 8, 3)


def test_load_master_rejects_mono_fits(tmp_path):
    # A 2D (mono / raw-CFA) FITS must be rejected, not silently debayered into
    # fake colour by load_fits.
    from astropy.io import fits
    p = tmp_path / "mono.fits"
    fits.PrimaryHDU(np.zeros((6, 8), np.uint16)).writeto(str(p))
    with pytest.raises(ValueError):
        load_master(str(p))


def test_load_master_unsupported_extension(tmp_path):
    p = tmp_path / "m.jpg"
    p.write_text("x")
    with pytest.raises(ValueError):
        load_master(str(p))
