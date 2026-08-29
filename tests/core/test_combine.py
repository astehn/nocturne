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


def test_combine_packs_ha_to_red_and_oiii_to_green_and_blue():
    from nocturne.core.combine import combine_gases
    ha = np.full((8, 8), 0.8, np.float32)
    oiii = np.full((8, 8), 0.2, np.float32)
    img = combine_gases(ha, oiii, balance=0.0)
    assert img.is_linear and img.data.shape == (8, 8, 3)
    assert np.allclose(img.data[..., 1], img.data[..., 2]), "OIII fills green AND blue"
    assert img.data[..., 0].mean() > img.data[..., 1].mean(), "Ha is the red channel"


def test_balance_zero_keeps_the_measured_ratio():
    """The reason the channel files are un-equalised. Pin the RATIO itself: a
    spread comparison is too weak — an equivalent mistake survived a MAD-based
    test on the extractor (see 9b18437)."""
    from nocturne.core.combine import combine_gases
    rng = np.random.default_rng(4)
    ha = (0.80 + 0.02 * rng.standard_normal((64, 64))).astype(np.float32)
    oiii = (0.20 + 0.02 * rng.standard_normal((64, 64))).astype(np.float32)
    img = combine_gases(ha, oiii, balance=0.0)
    r = float(np.median(img.data[..., 0])) / float(np.median(img.data[..., 1]))
    assert r == pytest.approx(0.80 / 0.20, rel=0.02), f"ratio came out {r:.3f}, want 4.0"


def test_balance_one_matches_oiii_to_ha():
    from nocturne.core.combine import combine_gases
    rng = np.random.default_rng(5)
    ha = (0.80 + 0.02 * rng.standard_normal((64, 64))).astype(np.float32)
    oiii = (0.20 + 0.02 * rng.standard_normal((64, 64))).astype(np.float32)
    img = combine_gases(ha, oiii, balance=1.0)
    r = float(np.median(img.data[..., 0])) / float(np.median(img.data[..., 1]))
    assert r == pytest.approx(1.0, rel=0.02), "at full balance the two must sit level"


def test_balance_moves_monotonically_between_the_two_ends():
    from nocturne.core.combine import combine_gases
    rng = np.random.default_rng(6)
    ha = (0.80 + 0.02 * rng.standard_normal((64, 64))).astype(np.float32)
    oiii = (0.20 + 0.02 * rng.standard_normal((64, 64))).astype(np.float32)
    levels = [float(np.median(combine_gases(ha, oiii, balance=t).data[..., 1]))
              for t in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert levels == sorted(levels), f"OIII must rise steadily with balance: {levels}"


def test_the_source_metadata_travels_with_the_combined_master():
    """A combined master must name its camera and filter like every other master
    — the provenance report and the instrument profile both read it, and a
    master that cannot say what took it is the bug fixed in 535f156."""
    from nocturne.core.combine import combine_gases
    img = combine_gases(np.full((8, 8), 0.8, np.float32),
                        np.full((8, 8), 0.2, np.float32),
                        metadata={"instrument": "ZWO Seestar S30 Pro",
                                  "filter": "LP", "target": "M 16"})
    assert img.metadata["instrument"] == "ZWO Seestar S30 Pro"
    assert img.metadata["filter"] == "LP" and img.metadata["target"] == "M 16"
    assert img.metadata["width"] == 8 and img.metadata["height"] == 8


def test_balance_defaults_to_matched():
    """A first-time user gets the familiar balanced result; the true ratio is
    something you reach for deliberately."""
    import inspect
    from nocturne.core.combine import combine_gases
    assert inspect.signature(combine_gases).parameters["balance"].default == 1.0


def test_combine_refuses_mismatched_shapes():
    from nocturne.core.combine import combine_gases
    with pytest.raises(ValueError, match="8"):
        combine_gases(np.zeros((8, 8), np.float32), np.zeros((4, 4), np.float32))
