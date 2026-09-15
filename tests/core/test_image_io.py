"""Reading a TIFF, and deciding whether it is still linear.

Why the decision is measured rather than asked: people bring masters from Siril,
APP and DeepSkyStacker — often a 32-bit float TIFF that is STILL LINEAR and wants
the whole pipeline — and finished pictures that want only the toolbar tools. The
user usually cannot say which they have; that is rather the point of asking us.
"""
import os

import numpy as np
import pytest
import tifffile

from nocturne.core.fits_io import load_fits
from nocturne.core.image import AstroImage
from nocturne.core.image_io import LINEAR_P999_MAX, load_tiff, looks_linear
from nocturne.core.stretch import apply_stretch

MASTERS = [
    "/Volumes/Work/Astro/IC 1396A_sub/IC1396A_drizzle_1975x10s_329min.fits",
    "/Volumes/Work/Astro/NGC 6888/Stacked_183_NGC 6888_10.0s_LP_20260811-235732.fit",
]


def _synthetic_linear():
    """Crushed near zero with a sparse bright tail — the shape of real linear
    astro data, so these run without the Astro drive attached."""
    rng = np.random.default_rng(0)
    d = np.clip(rng.normal(0.02, 0.005, (400, 300, 3)), 0, 1).astype(np.float32)
    d[10:14, 10:14] = 0.9        # stars: 0.004% of pixels, far under p99.9
    return d


def test_linear_data_reads_as_linear():
    assert looks_linear(_synthetic_linear()) is True


def test_a_stretch_at_any_amount_reads_as_stretched():
    """p99.9 was chosen over the median because the median moves 0.10 -> 0.45
    across this range, so its margin collapses at the dark end."""
    img = AstroImage(_synthetic_linear(), is_linear=True)
    for amount in (0.0, 0.3, 1.0):
        for linked in (True, False):
            out = apply_stretch(img, amount, linked=linked).data
            assert looks_linear(out) is False, (amount, linked)


@pytest.mark.parametrize("path", MASTERS)
def test_real_masters_and_their_stretches(path):
    """The evidence for the threshold. Skipped when the drive is not attached."""
    if not os.path.exists(path):
        pytest.skip("master not available")
    img = load_fits(path)
    assert looks_linear(img.data) is True
    assert looks_linear(apply_stretch(img, 0.30).data) is False


def test_the_threshold_keeps_its_margin():
    """10x above every linear measurement, 4x below every stretched one. An edit
    that narrows it should have to come back and disagree with the numbers."""
    assert LINEAR_P999_MAX == 0.20


def test_a_16bit_tiff_normalises_like_a_fits(tmp_path):
    """0-65535 must land on the same footing as a float file, or the statistic
    means something different for each."""
    p = tmp_path / "s.tif"
    tifffile.imwrite(str(p), (_synthetic_linear() * 65535).astype(np.uint16))
    img = load_tiff(str(p))
    assert img.data.max() <= 1.0
    assert img.is_linear is True


def test_a_32bit_stretched_tiff_reads_as_stretched(tmp_path):
    st = apply_stretch(AstroImage(_synthetic_linear(), is_linear=True), 0.3).data
    p = tmp_path / "st.tif"
    tifffile.imwrite(str(p), st.astype(np.float32))
    assert load_tiff(str(p)).is_linear is False


def test_a_mono_tiff_is_promoted_to_three_channels(tmp_path):
    p = tmp_path / "m.tif"
    tifffile.imwrite(str(p), (_synthetic_linear()[..., 0] * 65535).astype(np.uint16))
    img = load_tiff(str(p))
    assert img.data.ndim == 3 and img.data.shape[2] == 3


def test_an_alpha_channel_is_dropped(tmp_path):
    """Photoshop writes RGBA readily. A fourth channel downstream would be read
    as data by everything that indexes [..., :3] and ignored inconsistently."""
    rgba = np.dstack([_synthetic_linear(), np.ones((400, 300), np.float32)])
    p = tmp_path / "a.tif"
    tifffile.imwrite(str(p), rgba.astype(np.float32))
    assert load_tiff(str(p)).data.shape[2] == 3


def test_non_finite_samples_do_not_poison_the_verdict(tmp_path):
    """_normalize zeroes them FIRST and its docstring records why the order
    matters — one NaN previously left a 16-bit frame completely unscaled."""
    d = _synthetic_linear(); d[0, 0] = np.nan
    p = tmp_path / "n.tif"
    tifffile.imwrite(str(p), d)
    img = load_tiff(str(p))
    assert np.isfinite(img.data).all()
    assert img.is_linear is True


def test_a_file_that_is_not_a_tiff_raises(tmp_path):
    p = tmp_path / "x.tif"; p.write_text("not a tiff")
    with pytest.raises(Exception):
        load_tiff(str(p))


def test_core_stays_qt_free():
    """core/ imports no Qt, by rule. A reader is exactly the place that gets
    this wrong, because Qt has a perfectly good image loader."""
    import pathlib
    src = pathlib.Path("nocturne/core/image_io.py").read_text()
    assert "PySide6" not in src and "QtGui" not in src
