import numpy as np
import pytest
from astropy.io import fits
from seestar_processor.stacking.haoiii import (
    load_cfa, extract_cfa_planes, renorm_oiii, _site_offsets,
)
from tests.stacking.synthetic import make_star_field, write_cfa_fits


def test_site_offsets_grbg():
    off = _site_offsets("GRBG")   # G R / B G
    assert off["R"] == [(0, 1)]
    assert off["B"] == [(1, 0)]
    assert sorted(off["G"]) == [(0, 0), (1, 1)]


def test_extract_cfa_planes_known_values():
    # constant sites: R=0.8, G=0.4, B=0.2 on an 8x8 GRBG frame
    cfa = np.zeros((8, 8), np.float32)
    cfa[0::2, 1::2] = 0.8   # R
    cfa[0::2, 0::2] = 0.4   # G
    cfa[1::2, 1::2] = 0.4   # G
    cfa[1::2, 0::2] = 0.2   # B
    ha, oiii = extract_cfa_planes(cfa, "GRBG")
    assert ha.shape == (8, 8) and oiii.shape == (8, 8)
    assert np.allclose(ha, 0.8, atol=1e-4)              # Ha = red
    assert np.allclose(oiii, 0.3, atol=1e-4)            # OIII = (G+B)/2 = 0.3


def test_extract_cfa_planes_rejects_3d():
    with pytest.raises(ValueError):
        extract_cfa_planes(np.zeros((4, 4, 3), np.float32), "GRBG")


def test_load_cfa_reads_2d_and_pattern(tmp_path):
    p = tmp_path / "s.fit"
    write_cfa_fits(p, make_star_field(shape=(40, 40), n_stars=20, seed=1))
    cfa, pattern, exp = load_cfa(str(p))
    assert cfa.ndim == 2 and pattern == "GRBG" and exp == 10.0


def test_load_cfa_rejects_3d(tmp_path):
    p = tmp_path / "color.fits"
    fits.PrimaryHDU(np.zeros((3, 8, 8), np.float32)).writeto(str(p))
    with pytest.raises(ValueError):
        load_cfa(str(p))


def test_renorm_oiii_matches_median_and_mad():
    ha = np.array([1.0, 2.0, 3.0, 4.0], np.float32)
    oiii = ha * 0.5 + 10.0                    # scaled + offset copy
    out = renorm_oiii(ha, oiii)
    assert np.isclose(np.median(out), np.median(ha), atol=1e-4)
    def mad(x): return np.median(np.abs(x - np.median(x)))
    assert np.isclose(mad(out), mad(ha), atol=1e-4)


def _cfa_subs(tmp_path, n=4, seed=2):
    from skimage.transform import SimilarityTransform, warp
    base = make_star_field(shape=(120, 120), n_stars=60, seed=seed)
    paths = []
    for i in range(n):
        t = SimilarityTransform(translation=(i * 0.5, -i * 0.5))
        f = warp(base, t.inverse, order=1, preserve_range=True).astype(np.float32)
        p = tmp_path / f"s{i}.fit"
        write_cfa_fits(p, f, exptime=10.0)
        paths.append(str(p))
    return paths


def test_run_haoiii_extract_produces_combined_master(tmp_path):
    from seestar_processor.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    import os
    paths = _cfa_subs(tmp_path)
    out = tmp_path / "HaOIII_master.fits"
    result = run_haoiii_extract(HaOIIIOptions("average", 2.5, paths, str(out)))
    assert result.image.is_linear and result.image.data.ndim == 3
    assert result.frame_count == 4
    assert result.integration_seconds == 40.0
    # OIII packed into G and B -> those channels are identical
    g, b = result.image.data[..., 1], result.image.data[..., 2]
    assert np.allclose(g, b, atol=1e-6)
    assert os.path.exists(result.output_path)


def test_run_haoiii_extract_rejects_non_cfa(tmp_path):
    from seestar_processor.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    paths = _cfa_subs(tmp_path)
    bad = tmp_path / "color.fits"
    fits.PrimaryHDU(np.zeros((3, 120, 120), np.float32)).writeto(str(bad))
    result = run_haoiii_extract(
        HaOIIIOptions("average", 2.5, paths + [str(bad)], str(tmp_path / "m.fits")))
    assert any(str(bad) == p for p, _ in result.rejected)
    assert result.frame_count == 4


def test_run_haoiii_extract_rejects_non_cfa_reference(tmp_path):
    # A debayered FITS graded FIRST (best) must be rejected and the next raw sub
    # promoted to reference — not abort the run. The tool writes its master back
    # into the graded folder, so a prior RGB master can grade highest.
    from seestar_processor.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    paths = _cfa_subs(tmp_path)
    bad = tmp_path / "prior_master.fits"
    fits.PrimaryHDU(np.zeros((3, 120, 120), np.float32)).writeto(str(bad))
    result = run_haoiii_extract(
        HaOIIIOptions("average", 2.5, [str(bad)] + paths, str(tmp_path / "m.fits")))
    assert any(str(bad) == p for p, _ in result.rejected)
    assert result.frame_count == 4
    assert result.image.data.ndim == 3


def test_run_haoiii_extract_too_few(tmp_path):
    from seestar_processor.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    paths = _cfa_subs(tmp_path, n=2)
    with pytest.raises(ValueError):
        run_haoiii_extract(HaOIIIOptions("average", 2.5, paths, str(tmp_path / "m.fits")))
