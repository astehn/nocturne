"""Compressed FITS must open.

A plain FITS keeps its image in HDU 0. A tile-compressed one (RICE/GZIP, often
.fits.fz) has an EMPTY primary HDU and the image in HDU 1 as a CompImageHDU.
Every reader in fits_io assumed index 0, so hdul[0].data was None and the file
could not be opened at all.
"""
import numpy as np
import pytest
from astropy.io import fits

from nocturne.core.fits_io import (
    image_hdu, is_stacked_master, load_fits, load_master, load_mono_master,
)


def _plain(path, data, **cards):
    hdu = fits.PrimaryHDU(data)
    for k, v in cards.items():
        hdu.header[k] = v
    hdu.writeto(str(path), overwrite=True)


def _compressed(path, data, **cards):
    """What a tile-compressed FITS looks like: empty primary, image in HDU 1."""
    comp = fits.CompImageHDU(data=data, compression_type="RICE_1")
    for k, v in cards.items():
        comp.header[k] = v
    fits.HDUList([fits.PrimaryHDU(), comp]).writeto(str(path), overwrite=True)


def test_a_compressed_mono_frame_opens(tmp_path):
    data = (np.random.rand(64, 64) * 1000).astype(np.uint16)
    p = tmp_path / "sub.fits"
    _compressed(p, data)
    img = load_fits(str(p))
    assert img.data.shape[:2] == (64, 64)
    assert np.isfinite(img.data).all()


def test_a_compressed_colour_master_opens(tmp_path):
    data = (np.random.rand(3, 32, 48) * 1000).astype(np.uint16)
    p = tmp_path / "master.fits"
    _compressed(p, data, STACKCNT=120)
    img = load_master(str(p))
    assert img.data.shape == (32, 48, 3)


def test_the_header_is_read_from_the_image_hdu_not_the_empty_one(tmp_path):
    """STACKCNT and BAYERPAT live on the image HDU. Reading the empty primary
    header instead makes a master look like a raw sub, and vice versa."""
    data = (np.random.rand(3, 16, 16) * 1000).astype(np.uint16)
    p = tmp_path / "m.fits"
    _compressed(p, data, STACKCNT=200)
    assert is_stacked_master(str(p)) is True


def test_a_compressed_raw_sub_is_still_recognised_as_raw(tmp_path):
    """The guard that stops a raw CFA sub being loaded as a stacked gas plane
    must keep working when the header moved to HDU 1."""
    data = (np.random.rand(32, 32) * 1000).astype(np.uint16)
    p = tmp_path / "raw.fits"
    _compressed(p, data, BAYERPAT="GRBG")
    with pytest.raises(ValueError, match="raw sub"):
        load_mono_master(str(p))


def test_a_compressed_mono_master_loads_unnormalised(tmp_path):
    data = (np.random.rand(24, 24) * 1000).astype(np.uint16)
    p = tmp_path / "ha.fits"
    _compressed(p, data, STACKCNT=90)
    out = load_mono_master(str(p))
    assert out.shape == (24, 24)
    assert out.max() > 1.0, "a mono master must NOT be normalised to 0..1"


def test_plain_files_are_untouched(tmp_path):
    """The overwhelming majority of files. A fix for compressed FITS that
    changed which HDU a normal file reads from would be far worse than the bug."""
    data = (np.random.rand(48, 48) * 1000).astype(np.uint16)
    p = tmp_path / "plain.fits"
    _plain(p, data)
    img = load_fits(str(p))
    assert img.data.shape[:2] == (48, 48)
    with fits.open(str(p)) as hdul:
        assert image_hdu(hdul) is hdul[0]


def test_an_empty_file_does_not_crash_the_chooser(tmp_path):
    """image_hdu must always return something — callers index into it."""
    fits.HDUList([fits.PrimaryHDU()]).writeto(str(tmp_path / "e.fits"))
    with fits.open(str(tmp_path / "e.fits")) as hdul:
        assert image_hdu(hdul) is hdul[0]
