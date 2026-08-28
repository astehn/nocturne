import numpy as np
import pytest
from astropy.io import fits
from nocturne.stacking.haoiii import (
    load_cfa, extract_cfa_planes, renorm_oiii, _site_offsets, _upsample_site,
    _OIII_GREEN_WEIGHT,
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
    # OIII combines green and blue by SNR, not evenly
    w = _OIII_GREEN_WEIGHT
    assert np.allclose(oiii, (w * 0.4 + 0.2) / (w + 1.0), atol=1e-4)


def test_the_oiii_green_weight_is_the_measured_one():
    """Pinned by value, not just by formula: the test above would pass with any
    weight at all, because it asks the code what it uses. 4:1 is SNR-squared
    weighting — green measured 2.0x blue's SNR on both M16 and IC 1396A, and
    sweeping confirmed the optimum at 4:1 on both, worth 26% of OIII SNR over
    the even split. Changing it means re-measuring, not re-guessing."""
    assert _OIII_GREEN_WEIGHT == 4.0


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
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
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
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
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
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    paths = _cfa_subs(tmp_path)
    bad = tmp_path / "prior_master.fits"
    fits.PrimaryHDU(np.zeros((3, 120, 120), np.float32)).writeto(str(bad))
    result = run_haoiii_extract(
        HaOIIIOptions("average", 2.5, [str(bad)] + paths, str(tmp_path / "m.fits")))
    assert any(str(bad) == p for p, _ in result.rejected)
    assert result.frame_count == 4
    assert result.image.data.ndim == 3


def test_run_haoiii_extract_too_few(tmp_path):
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    paths = _cfa_subs(tmp_path, n=2)
    with pytest.raises(ValueError):
        run_haoiii_extract(HaOIIIOptions("average", 2.5, paths, str(tmp_path / "m.fits")))


def _count_calls(monkeypatch, module, name):
    """Count how often a function runs during one extract."""
    calls = {"n": 0}
    real = getattr(module, name)

    def counted(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(module, name, counted)
    return calls


def test_both_channels_come_from_one_pass(tmp_path, monkeypatch):
    """Profiled on 12 real subs: extraction was 41.6% of the run and warping
    34.2%, while reading the files off disk was 2.4%. The cost was never the
    I/O — it was doing the Bayer split five times per sub and the warp four
    times, because Ha and OIII were integrated as two independent passes over
    the same frames. Both channels come out of ONE read, so they belong in one
    pass: extraction 5 calls -> 3, warp 4 -> 2, matching the main stacker's
    streaming shape.
    """
    import nocturne.stacking.haoiii as H
    paths = _cfa_subs(tmp_path, n=4)
    extracts = _count_calls(monkeypatch, H, "extract_cfa_planes")
    warps = _count_calls(monkeypatch, H, "warp_with_validity")
    out = tmp_path / "m.fits"
    H.run_haoiii_extract(H.HaOIIIOptions("sigma_clip", 2.5, paths, str(out)))
    n = len(paths)
    assert extracts["n"] <= 3 * n, (
        f"{extracts['n']} extractions for {n} subs — should be at most 3 per sub "
        f"(one to register, two for the sigma-clip passes)")
    assert warps["n"] <= 2 * n, (
        f"{warps['n']} warps for {n} subs — should be at most 2 per sub, one per "
        f"sigma-clip pass, with both channels warped together")


def test_autocrop_off_keeps_the_full_frame(tmp_path):
    """Stack lets you keep the ragged border; on a 2 MP sensor those pixels are
    worth having, and Ha/OIII used to crop with no say in it."""
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    paths = _cfa_subs(tmp_path)
    trimmed = run_haoiii_extract(HaOIIIOptions(
        "average", 2.5, paths, str(tmp_path / "a.fits"), autocrop=True)).image.data
    kept = run_haoiii_extract(HaOIIIOptions(
        "average", 2.5, paths, str(tmp_path / "b.fits"), autocrop=False)).image.data
    assert kept.shape[:2] == (120, 120), "untrimmed must be the full sensor frame"
    assert trimmed.shape[0] < 120 or trimmed.shape[1] < 120, (
        "the frames are dithered, so trimming must actually remove something")


def _widely_dithered_subs(tmp_path, n=4, shift=10.0):
    """Deliberately coarse dithering, so the under-covered border is a real
    fraction of the frame (43.8% of the pixels at shift=10 on 120x120) rather
    than the two-pixel rim the 0.5px fixture leaves."""
    from skimage.transform import SimilarityTransform, warp
    base = make_star_field(shape=(120, 120), n_stars=60, seed=2)
    paths = []
    for i in range(n):
        t = SimilarityTransform(translation=(i * shift, -i * shift))
        f = warp(base, t.inverse, order=1, preserve_range=True).astype(np.float32)
        p = tmp_path / f"w{i}.fit"
        write_cfa_fits(p, f, exptime=10.0)
        paths.append(str(p))
    return paths


def test_the_oiii_fit_is_measured_where_every_frame_contributed(tmp_path):
    """renorm is a median and a MAD over an array, and matching OIII's median to
    Ha's is the whole guarantee. Measure it over the untrimmed frame and the
    ragged border — built from a fraction of the frames — drags the pedestal off:
    the medians came out 1.2e-4 apart instead of equal. So the fit is taken on the
    covered core and only the *output* crop is the user's choice.
    """
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    paths = _widely_dithered_subs(tmp_path)
    master = run_haoiii_extract(HaOIIIOptions(
        "average", 2.5, paths, str(tmp_path / "m.fits"), autocrop=True)).image.data
    gap = abs(float(np.median(master[..., 0])) - float(np.median(master[..., 1])))
    assert gap < 1e-5, f"OIII median must land on Ha's, off by {gap:.6f}"


def _centroid(a):
    """Intensity-weighted centre, in pixels."""
    a = np.clip(a.astype(np.float64) - np.median(a), 0, None)
    rows, cols = np.indices(a.shape)
    tot = a.sum()
    return (float((rows * a).sum() / tot), float((cols * a).sum() / tot))


def test_ha_and_oiii_land_on_the_same_pixels():
    """Ha comes off the red sites, OIII off the green and blue ones, and in a
    GRBG tile those sit at (0,1), (0,0)+(1,1) and (1,0) — three differently
    offset grids. Decimating each to half res and resizing them all onto the
    full frame the same way put the two gases about 1px apart: predicted (0.75,
    0.75) from the tile geometry, measured (0.84, 1.02) on two 20-sub M16
    masters. A star was landing in a different place depending on which gas you
    looked at, which is colour fringing and lost sharpness on every frame.

    A grey scene samples identically at every site, so whatever Ha reconstructs
    OIII must reconstruct in the same place.
    """
    yy, xx = np.mgrid[0:120, 0:120]
    scene = np.exp(-(((yy - 60.3) ** 2 + (xx - 59.7) ** 2) / (2 * 2.5 ** 2)))
    scene = (scene * 1000 + 10).astype(np.float32)

    ha, oiii = extract_cfa_planes(scene, "GRBG")
    hr, hc = _centroid(ha)
    orow, ocol = _centroid(oiii)
    assert abs(hr - orow) < 0.10 and abs(hc - ocol) < 0.10, (
        f"Ha at ({hr:.3f}, {hc:.3f}) but OIII at ({orow:.3f}, {ocol:.3f}) — "
        f"offset ({hr-orow:+.3f}, {hc-ocol:+.3f}) px")


def test_each_gas_lands_where_the_scene_actually_is():
    """Aligned with each other is necessary but not sufficient — both could be
    shifted together off the true position, which would misalign the master
    against a plate solve and against any other stack of the same subs."""
    yy, xx = np.mgrid[0:120, 0:120]
    scene = np.exp(-(((yy - 60.3) ** 2 + (xx - 59.7) ** 2) / (2 * 2.5 ** 2)))
    scene = (scene * 1000 + 10).astype(np.float32)
    truth = _centroid(scene)

    ha, oiii = extract_cfa_planes(scene, "GRBG")
    for name, plane in (("Ha", ha), ("OIII", oiii)):
        r, c = _centroid(plane)
        assert abs(r - truth[0]) < 0.15 and abs(c - truth[1]) < 0.15, (
            f"{name} centred ({r:.3f}, {c:.3f}), scene is at "
            f"({truth[0]:.3f}, {truth[1]:.3f})")


def test_the_separable_upsample_matches_a_general_interpolator():
    """_lerp_axis is an optimisation: two 1D passes standing in for a 2D
    map_coordinates, worth 2.8x. Pin it to the reference so a future tweak
    cannot quietly change the interpolation the masters are built from."""
    from scipy.ndimage import map_coordinates
    from nocturne.stacking.haoiii import _upsample_site

    rng = np.random.default_rng(3)
    cfa = rng.random((64, 48)).astype(np.float32) * 1000
    for r, c in ((0, 0), (0, 1), (1, 0), (1, 1)):
        sub = cfa[r::2, c::2]
        rows = (np.arange(cfa.shape[0], dtype=np.float32) - r) / 2.0
        cols = (np.arange(cfa.shape[1], dtype=np.float32) - c) / 2.0
        reference = map_coordinates(
            sub, np.array(np.meshgrid(rows, cols, indexing="ij")),
            order=1, mode="nearest")
        assert np.allclose(_upsample_site(cfa, r, c, cfa.shape), reference,
                           atol=1e-4), f"site ({r},{c}) diverges from the reference"


def test_oiii_uses_every_green_site_not_just_one():
    """A GRBG tile has two green sites, and using both is what halves the green
    noise. Dropping one passed the whole suite: alignment tests still pass on a
    single sub-plane, because one green site is just as well-aligned as two.
    Poke each site in turn and require the output to notice."""
    from nocturne.stacking.haoiii import _site_offsets
    off = _site_offsets("GRBG")
    assert len(off["G"]) == 2, "fixture assumes the two-green Bayer tile"

    for site in off["G"]:
        cfa = np.zeros((32, 32), np.float32)
        r, c = site
        cfa[10 * 2 + r, 10 * 2 + c] = 1000.0     # one sample, at this green site
        _, oiii = extract_cfa_planes(cfa, "GRBG")
        assert oiii.max() > 0, f"green site {site} never reaches the OIII plane"

    cfa = np.zeros((32, 32), np.float32)
    br, bc = off["B"][0]
    cfa[10 * 2 + br, 10 * 2 + bc] = 1000.0
    _, oiii = extract_cfa_planes(cfa, "GRBG")
    assert oiii.max() > 0, "the blue site never reaches the OIII plane"

    cfa = np.zeros((32, 32), np.float32)
    rr, rc = off["R"][0]
    cfa[10 * 2 + rr, 10 * 2 + rc] = 1000.0
    ha, oiii = extract_cfa_planes(cfa, "GRBG")
    assert ha.max() > 0, "the red site never reaches the Ha plane"
    assert oiii.max() == 0, "red must not leak into OIII — that is the whole point"


def test_averaging_both_greens_actually_lowers_the_noise():
    """The structural test above proves both greens are read; this proves that
    reading both is worth something. Two independent samples averaged should cut
    the standard deviation by about root two."""
    rng = np.random.default_rng(11)
    cfa = rng.normal(100.0, 10.0, (256, 256)).astype(np.float32)
    _, oiii = extract_cfa_planes(cfa, "GRBG")
    single = _upsample_site(cfa, 0, 0, cfa.shape)      # one green site alone
    assert oiii.std() < 0.85 * single.std(), (
        f"OIII noise {oiii.std():.3f} vs a single green site {single.std():.3f} — "
        "combining the sites is not buying anything")
