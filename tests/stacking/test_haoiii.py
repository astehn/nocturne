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


def test_the_master_names_its_camera_and_filter_like_a_normal_stack():
    """A Ha/OIII master dropped FILTER and INSTRUME while a normal stack of the
    same subs kept both, so a reloaded extract could not say what camera or
    filter made it — and Nocturne identifies the instrument from that header.
    The cause was a hand-rolled header beside a perfectly good master_header();
    pin the two together so they cannot drift apart again."""
    import inspect
    from nocturne.stacking import haoiii
    from nocturne.stacking.stacker import master_header

    src = inspect.getsource(haoiii.run_haoiii_extract)
    assert "master_header(" in src, "the extractor is hand-rolling its header again"

    meta = {"solve_cards": {"RA": 275.1, "DEC": -13.8}, "target": "M 16",
            "filter": "LP", "instrument": "ZWO Seestar S30 Pro"}
    h = master_header(meta, 333, 3330.0, trimmed=True)
    for card in ("FILTER", "INSTRUME", "OBJECT", "STACKCNT", "EXPTIME", "TRIMMED"):
        assert card in h, f"{card} is missing from a written master"
    assert h["FILTER"] == "LP" and h["INSTRUME"] == "ZWO Seestar S30 Pro"


def test_the_master_records_whether_it_was_trimmed(tmp_path):
    """Two masters of the same subs differ by ~45% in height depending on one
    checkbox, and nothing on disk said which was which — that is what made two
    of Andreas's masters look inexplicably different on 2026-08-28."""
    from astropy.io import fits
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    paths = _cfa_subs(tmp_path)
    for flag in (True, False):
        out = tmp_path / f"m_{flag}.fits"
        run_haoiii_extract(HaOIIIOptions("average", 2.5, paths, str(out), autocrop=flag))
        assert bool(fits.getheader(out)["TRIMMED"]) is flag, (
            f"a master built with autocrop={flag} does not say so")


def test_channel_files_are_written_only_when_asked(tmp_path):
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract, channel_paths
    import os
    paths = _cfa_subs(tmp_path)
    out = str(tmp_path / "m.fits")
    run_haoiii_extract(HaOIIIOptions("average", 2.5, paths, out))
    assert not any(os.path.exists(p) for p in channel_paths(out)), \
        "channel files appeared without being asked for"
    run_haoiii_extract(HaOIIIOptions("average", 2.5, paths, out, write_channels=True))
    for p in channel_paths(out):
        assert os.path.exists(p), f"{p} was not written"


def test_channel_files_are_mono_and_keep_the_true_gas_ratio(tmp_path):
    """Un-equalised is the whole point: OIII is genuinely fainter than Ha, and
    the recombiner decides the lift. renorm_oiii forces the two to the same
    median and spread, so if the fit leaked into these files the ratio would
    read 1.0 and could never be recovered."""
    from astropy.io import fits
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract, channel_paths
    paths = _cfa_subs(tmp_path)
    out = str(tmp_path / "m.fits")
    r = run_haoiii_extract(HaOIIIOptions("average", 2.5, paths, out, write_channels=True))
    ha_path, oiii_path = channel_paths(out)
    ha, oiii = fits.getdata(ha_path), fits.getdata(oiii_path)
    assert ha.ndim == 2 and oiii.ndim == 2, "each gas must be a mono plane"
    assert ha.shape == r.image.data.shape[:2], "channel files must match the master's framing"

    def mad(x):
        return float(np.median(np.abs(x - np.median(x))))
    # the master's two gases are forced to the same spread; these must not be
    assert mad(r.image.data[..., 0]) == pytest.approx(mad(r.image.data[..., 1]), rel=0.02)
    assert mad(oiii) != pytest.approx(mad(ha), rel=0.02), \
        "the OIII file has been equalised to Ha — the real ratio is lost"


def test_a_written_channel_file_is_not_mistaken_for_a_raw_sub(tmp_path):
    """The trap this feature walks into: a mono master is NAXIS=2, the same
    shape as a raw CFA sub. Ungarded, the next grading run would take one as a
    frame — and a stacked image is full of sharp stars, so it could grade BEST
    and become the registration reference, then be Bayer-split into nonsense."""
    from nocturne.core.fits_io import is_stacked_master
    from nocturne.stacking.grade import grade_frame
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract, channel_paths
    paths = _cfa_subs(tmp_path)
    out = str(tmp_path / "m.fits")
    run_haoiii_extract(HaOIIIOptions("average", 2.5, paths, out, write_channels=True))
    for p in channel_paths(out) + (out,):
        assert is_stacked_master(p), f"{p} would be graded as a raw sub"
        s = grade_frame(p)
        assert not s.included and s.error, f"the grader accepted {p} as a frame"
    # and a genuine raw sub is still a raw sub
    assert not is_stacked_master(paths[0])
    assert grade_frame(paths[0]).star_count > 0


def test_channel_files_share_one_scale_so_the_gas_ratio_survives(tmp_path):
    """Both planes must be divided by the SAME number. Scaling each by its own
    peak would land both at 1.0 and silently destroy the Ha:OIII ratio — the one
    quantity these files exist to carry, and the one you cannot recover
    afterwards. A mutation doing exactly that passed every other test here.
    """
    from astropy.io import fits
    from nocturne.stacking.haoiii import _write_channel_files, channel_paths

    ha = np.full((8, 8), 0.80, np.float32)
    ha[0, 0] = 1.0                      # a star, so the two planes peak differently
    oiii = np.full((8, 8), 0.20, np.float32)
    out = str(tmp_path / "m.fits")
    _write_channel_files(ha, oiii, {"STACKCNT": 3}, out)

    ha_path, oiii_path = channel_paths(out)
    a, b = fits.getdata(ha_path), fits.getdata(oiii_path)
    assert float(np.median(a)) / float(np.median(b)) == pytest.approx(0.80 / 0.20, rel=1e-3), (
        f"ratio came out {np.median(a)/np.median(b):.3f}, should be 4.0 — "
        "the planes were scaled independently")
    assert a.max() <= 1.0 and b.max() <= 1.0, "both must still fit in [0, 1]"
    assert b.max() < 0.9, "OIII must stay as faint as it really is, not be stretched to fill"


def _cfa_subs_varying_sky(tmp_path, n=8, shift=8.0):
    """Subs that drift AND whose sky level changes between them — a real
    session, where the target climbs and the moon moves. Measured across one
    M31 session the sky varied 262% frame to frame (see normalize.py)."""
    from skimage.transform import SimilarityTransform, warp
    base = make_star_field(shape=(160, 160), n_stars=80, seed=3)
    paths = []
    for i in range(n):
        t = SimilarityTransform(translation=(i * shift, -i * shift))
        f = warp(base, t.inverse, order=1, preserve_range=True).astype(np.float32)
        f = f + (100.0 + 60.0 * i)          # each frame sits on a different sky
        p = tmp_path / f"v{i}.fit"
        write_cfa_fits(p, f, exptime=10.0)
        paths.append(str(p))
    return paths


def test_the_rotation_envelope_is_not_drawn_onto_the_master(tmp_path):
    """Andreas, 2026-08-29, on a 1116-frame NGC 281 stack with trim off: the
    Ha/OIII master came out with bright wedges cutting across it while a normal
    stack of the same subs was clean.

    normalize.py already names this exactly — "every coverage boundary then
    becomes a step in background level and the rotation envelope gets drawn onto
    the finished picture as curved bands" — and the extractor never called it.
    It was hidden for as long as the extractor always cropped to the
    near-fully-covered middle; adding the Trim option exposed it.

    Take the sky level where every frame contributed and where only some did:
    they must match.
    """
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    paths = _cfa_subs_varying_sky(tmp_path)
    master = run_haoiii_extract(HaOIIIOptions(
        "average", 2.5, paths, str(tmp_path / "m.fits"), autocrop=False)).image.data

    ha = master[..., 0]
    # the drift runs down-right, so the middle sees every frame and the
    # top-left corner only the first few
    core = ha[70:90, 70:90]
    fringe = ha[4:24, 4:24]
    core_sky, fringe_sky = float(np.median(core)), float(np.median(fringe))
    step = abs(core_sky - fringe_sky) / max(core_sky, 1e-6)
    assert step < 0.10, (
        f"background steps {100 * step:.0f}% across a coverage boundary "
        f"(core {core_sky:.4f}, fringe {fringe_sky:.4f}) — the rotation "
        "envelope is being drawn onto the picture")


def test_frames_are_normalised_before_they_are_warped():
    """A structural guard, and honestly labelled as one: swapping the order
    changes no pixel today, because coverage-aware integration excludes the
    warp's out-of-frame fill through the validity mask either way. It is still
    wrong, and run_stack says why — normalising afterwards turns that clean zero
    fill into a plausible-looking sky value, so the correctness of every edge
    pixel comes to depend on the mask being perfect rather than on the fill
    being obviously invalid.

    Asserting on output would prove nothing here, so assert on the order.
    """
    import inspect
    from nocturne.stacking import haoiii
    src = inspect.getsource(haoiii.run_haoiii_extract)
    norm_at = src.index("normalize_to(")
    warp_at = src.index("warp_with_validity(", norm_at - 400 if norm_at > 400 else 0)
    assert norm_at < warp_at, "frames must be normalised before warping, not after"


def test_a_long_extract_can_be_cancelled(tmp_path):
    """Andreas, 2026-08-29: a 1116-frame extract runs for a long time and there
    was no way to stop it. Stack has had a Cancel button since the task
    controller landed; the extractor never checked the ambient token at all.

    Cancelled derives from BaseException on purpose, so an `except Exception`
    anywhere in the pipeline cannot swallow it.
    """
    from nocturne.core.tasks import CancelToken, Cancelled, clear_ambient, set_ambient
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    paths = _cfa_subs(tmp_path, n=6)
    token = CancelToken()
    token.cancel()                      # already cancelled before it starts
    set_ambient(token)
    try:
        with pytest.raises(Cancelled):
            run_haoiii_extract(HaOIIIOptions(
                "average", 2.5, paths, str(tmp_path / "m.fits")))
    finally:
        clear_ambient()


def test_cancelling_partway_through_stops_the_run(tmp_path):
    """Not just the trivial pre-cancelled case: cancel once work is under way
    and it must stop rather than run to completion."""
    from nocturne.core.tasks import CancelToken, Cancelled, clear_ambient, set_ambient
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    paths = _cfa_subs(tmp_path, n=8)
    token = CancelToken()
    seen = {"n": 0}

    def on_progress(i, n, label):
        seen["n"] += 1
        if seen["n"] == 3:
            token.cancel()

    set_ambient(token)
    try:
        with pytest.raises(Cancelled):
            run_haoiii_extract(HaOIIIOptions(
                "average", 2.5, paths, str(tmp_path / "m.fits")),
                on_progress=on_progress)
    finally:
        clear_ambient()
    assert seen["n"] < 8 * 3, "the run kept going after being cancelled"


def test_a_cancelled_extract_writes_no_master(tmp_path):
    """A half-written master is worse than none — it would be graded as a real
    one on the next run."""
    import os
    from nocturne.core.tasks import CancelToken, Cancelled, clear_ambient, set_ambient
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    paths = _cfa_subs(tmp_path, n=6)
    out = tmp_path / "m.fits"
    token = CancelToken()
    token.cancel()
    set_ambient(token)
    try:
        with pytest.raises(Cancelled):
            run_haoiii_extract(HaOIIIOptions("average", 2.5, paths, str(out)))
    finally:
        clear_ambient()
    assert not os.path.exists(out), "a cancelled run left a master behind"


def test_cancelling_during_integration_stops_it_too():
    """Registration is the short phase; integration is where the minutes go, and
    it is what a user watching a stalled progress bar wants to stop. The first
    version of the cancel test only ever cancelled during registration, so a
    missing check in the integration loop went unnoticed."""
    import inspect
    from nocturne.stacking import haoiii
    src = inspect.getsource(haoiii.run_haoiii_extract)
    frames_fn = src[src.index("def frames("):src.index("if opts.method ==")]
    assert "_check_cancel()" in frames_fn, (
        "the integration loop never looks at the cancel token — only "
        "registration does, so cancelling during the long phase does nothing")


def test_cancelling_after_registration_raises(tmp_path):
    """The behavioural half: let registration finish, then cancel on the first
    stacking callback and require the run to stop."""
    from nocturne.core.tasks import CancelToken, Cancelled, clear_ambient, set_ambient
    from nocturne.stacking.haoiii import HaOIIIOptions, run_haoiii_extract
    paths = _cfa_subs(tmp_path, n=8)
    token = CancelToken()

    def on_progress(i, n, label):
        if label.startswith("stacking"):
            token.cancel()

    set_ambient(token)
    try:
        with pytest.raises(Cancelled):
            run_haoiii_extract(HaOIIIOptions(
                "average", 2.5, paths, str(tmp_path / "m.fits")),
                on_progress=on_progress)
    finally:
        clear_ambient()


def test_registration_uses_the_process_pool():
    """Phase A was a plain serial loop while the normal stacker had used a
    process pool since v0.16.0. Measured on 80 real NGC 281 subs it was 84.8% of
    the entire run — 40.6s of 48.0s — and the pool took the run to 15.4s.

    astroalign matches triangles in Python, so this phase is GIL-bound and needs
    processes, not threads; the token cannot cross a process boundary, so
    check_cancel must still be handed in to be polled between results."""
    import inspect
    from nocturne.stacking import haoiii
    src = inspect.getsource(haoiii.run_haoiii_extract)
    assert "register_frames(" in src, "Phase A is serial again"
    call = src[src.index("register_frames("):]
    call = call[:call.index("):") + 2]
    assert "gas=True" in call, "the pool must use the CFA path, not the debayered one"
    assert "check_cancel=" in call, "a parallel Phase A must still be cancellable"


def test_the_gas_worker_returns_what_the_serial_loop_did(tmp_path):
    """Same fields, same rejection wording — those strings reach the user in the
    extraction report."""
    from nocturne.stacking import register_pool as rp
    paths = _cfa_subs(tmp_path, n=3)
    rp._init(paths[0], gas=True)

    good = rp._register_one_gas(paths[1])
    assert good.reason is None
    assert good.matrix is not None and good.matrix.shape == (3, 3)
    assert good.exposure == 10.0
    loc, scale = good.stats
    assert len(loc) == 2 and len(scale) == 2, "stats must cover BOTH gases"

    # a colour cube is not a raw sub
    from astropy.io import fits
    rgb = tmp_path / "rgb.fits"
    fits.PrimaryHDU(np.zeros((3, 8, 8), np.float32)).writeto(rgb, overwrite=True)
    assert "not raw CFA" in rp._register_one_gas(str(rgb)).reason

    # a CFA frame of the wrong size
    small = tmp_path / "small.fit"
    write_cfa_fits(small, np.zeros((40, 40), np.float32), exptime=10.0)
    assert rp._register_one_gas(str(small)).reason == "dimension mismatch"


def test_the_gas_reference_is_the_ha_plane_not_a_debayered_luminance(tmp_path):
    """Registering the extractor's frames on a debayered luminance would align
    them to a different picture than the one being stacked."""
    from nocturne.stacking import register_pool as rp
    from nocturne.stacking.cfa import extract_cfa_planes, load_cfa
    paths = _cfa_subs(tmp_path, n=3)
    rp._init(paths[0], gas=True)
    cfa, pattern, _ = load_cfa(paths[0])
    assert np.allclose(rp._REF["lum"], extract_cfa_planes(cfa, pattern)[0])
    assert rp._REF["shape"] == cfa.shape


def test_combining_the_extractors_own_channel_files_reproduces_its_master(tmp_path):
    """The invariant that keeps the two tools honest. The extractor writes Ha and
    OIII un-equalised and separately packs a colour master; Combine at full
    balance must arrive at the same place. If it drifts, one of them changed.

    It holds because every step is scale-invariant: the channel files are the
    same planes divided by a shared peak, oiii_fit's scale is a ratio of MADs,
    and the master is normalised by its own peak either way.
    """
    from nocturne.core.combine import combine_gases
    from nocturne.core.fits_io import load_mono_master
    from nocturne.stacking.haoiii import (HaOIIIOptions, channel_paths,
                                          run_haoiii_extract)
    paths = _cfa_subs(tmp_path)
    out = str(tmp_path / "m.fits")
    master = run_haoiii_extract(HaOIIIOptions(
        "average", 2.5, paths, out, write_channels=True)).image.data

    ha_path, oiii_path = channel_paths(out)
    rebuilt = combine_gases(load_mono_master(ha_path),
                            load_mono_master(oiii_path), balance=1.0).data

    assert rebuilt.shape == master.shape
    assert np.allclose(rebuilt, master, atol=1e-4), (
        f"max difference {np.abs(rebuilt - master).max():.6f} — the extractor and "
        "the combiner no longer agree")


def test_the_master_you_get_matches_the_master_you_saved(tmp_path):
    """The in-memory result was hand-rolled with frames/exposure/dimensions
    only, while the FILE it wrote got a full header — so an Ha/OIII master
    handed straight to the app could not name its own target, camera or filter,
    and the same master reopened from disk could.

    Since the Share title plate shipped (v0.23.0) that is user-visible:
    combining and sharing gave a plate with no object and no common name, where
    saving and reopening filled it in. Same image, two different plates.
    """
    from nocturne.stacking.stacker import master_header, master_metadata
    ref = {"target": "NGC 7000", "instrument": "Sony IMX585", "filter": "LP",
           "gain": 200, "focal_length": 160.0, "pixel_size": 2.9,
           "date": "2026-08-26T20:06:02", "date_end": "2026-08-27T03:24:30"}
    mem = master_metadata(ref, 300, 3000.0, 3840, 2160)
    hdr = master_header(ref, 300, 3000.0)

    assert mem["target"] == hdr["OBJECT"] == "NGC 7000"
    assert mem["filter"] == hdr["FILTER"] == "LP"
    assert mem["instrument"] == hdr["INSTRUME"] == "Sony IMX585"
    assert mem["gain"] == hdr["GAIN"] == 200
    assert mem["date"] == hdr["DATE-OBS"]
    assert mem["date_end"] == hdr["DATE-END"]


def test_the_share_plate_is_filled_in_either_way(tmp_path):
    """The consequence, stated as the user meets it."""
    from nocturne.core.plate import plate_text
    from nocturne.stacking.stacker import master_metadata
    ref = {"target": "NGC 7000", "exposure": 10.0,
           "date": "2026-08-26T20:06:02", "date_end": "2026-08-27T03:24:30"}
    mem = master_metadata(ref, 300, 3000.0, 3840, 2160)
    t = plate_text(mem, "@Andreas Stehn")
    assert t.designation == "NGC 7000"
    assert t.common == "North America Nebula", "the plate cannot name the object"
    assert "26–27 Aug 2026" in t.credit


def test_haoiii_builds_both_from_one_reference():
    """Guards the shape of the fix, not just its result: the file and the
    in-memory master must be derived from the SAME ref_meta, or they drift
    apart again the next time one of them gains a field."""
    from pathlib import Path
    src = (Path(__file__).parents[2] / "nocturne" / "stacking" / "haoiii.py").read_text()
    assert "metadata=master_metadata(ref_meta" in src, \
        "the in-memory master is hand-rolled again"
    assert "master_header(ref_meta" in src
