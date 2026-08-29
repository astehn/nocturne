import numpy as np
import pytest
from astropy.io import fits


def _write(path, data, **cards):
    hdu = fits.PrimaryHDU(np.asarray(data, np.float32))
    for k, v in cards.items():
        hdu.header[k] = v
    hdu.writeto(path, overwrite=True)


def test_load_mono_master_reads_a_2d_fits(tmp_path):
    from nocturne.core.fits_io import load_mono_master
    p = tmp_path / "ha.fits"
    _write(p, np.full((8, 8), 0.25, np.float32), STACKCNT=20)
    arr = load_mono_master(str(p))
    assert arr.shape == (8, 8) and arr.dtype == np.float32
    assert np.allclose(arr, 0.25)


def test_load_mono_master_does_not_rescale(tmp_path):
    """Ha and OIII must be divided by the SAME number or the ratio between them
    is gone, and the ratio is the whole reason the channel files are written
    un-equalised. Per-file normalisation on load would destroy it silently."""
    from nocturne.core.fits_io import load_mono_master
    p = tmp_path / "faint.fits"
    _write(p, np.full((8, 8), 0.02, np.float32), STACKCNT=20)
    assert np.allclose(load_mono_master(str(p)), 0.02), "values were rescaled on load"


def test_load_mono_master_refuses_a_raw_sub(tmp_path):
    """A raw CFA sub is 2D — exactly the shape of a legitimate channel file.
    Combining raw subs is meaningless, so it must be refused by name. Same
    discriminator that stops the grader eating our own channel files."""
    from nocturne.core.fits_io import load_mono_master
    p = tmp_path / "sub.fit"
    _write(p, np.zeros((8, 8), np.float32), BAYERPAT="GRBG")   # no STACKCNT
    with pytest.raises(ValueError, match="raw sub"):
        load_mono_master(str(p))


def test_load_mono_master_accepts_a_stacked_file_that_names_its_bayer_pattern(tmp_path):
    """A master may legitimately carry BAYERPAT inherited from its reference
    sub. STACKCNT is what says it has been stacked."""
    from nocturne.core.fits_io import load_mono_master
    p = tmp_path / "ha.fits"
    _write(p, np.full((8, 8), 0.3, np.float32), BAYERPAT="GRBG", STACKCNT=20)
    assert load_mono_master(str(p)).shape == (8, 8)


def test_load_mono_master_refuses_a_colour_cube(tmp_path):
    from nocturne.core.fits_io import load_mono_master
    p = tmp_path / "rgb.fits"
    _write(p, np.zeros((3, 8, 8), np.float32), STACKCNT=20)
    with pytest.raises(ValueError, match="mono"):
        load_mono_master(str(p))
