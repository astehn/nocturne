import numpy as np
import pytest
from skimage.transform import SimilarityTransform, warp

from nocturne.stacking.mosaic import discover_panels, read_pointings, stack_panels
from tests.stacking.synthetic import make_star_field, write_color_fits


def _panel_subs(tmp_path, prefix, ra, dec, n=5, seed=1):
    """n dithered subs of one pointing, with the pointing in the header."""
    base = make_star_field(shape=(80, 80), n_stars=40, seed=seed)
    paths = []
    for i in range(n):
        t = SimilarityTransform(translation=(i * 0.5, -i * 0.5))
        f = warp(base, t.inverse, order=1, preserve_range=True).astype(np.float32)
        p = tmp_path / f"{prefix}{i}.fit"
        write_color_fits(p, f, exptime=10.0,
                         header={"RA": ra + i * 0.001, "DEC": dec + i * 0.001})
        paths.append(str(p))
    return paths


def test_read_pointings_reads_ra_dec_from_headers(tmp_path):
    paths = _panel_subs(tmp_path, "a", 10.0, 41.0, n=3)
    pointings = read_pointings(paths)
    assert len(pointings) == 3
    assert pointings[paths[0]] == pytest.approx((10.0, 41.0))


def test_frames_without_usable_pointing_are_skipped(tmp_path):
    """The loader prefers OBJCTRA over RA, and OBJCTRA is sexagesimal on some
    files. A frame we cannot place numerically must be left out rather than
    guessed into the wrong panel."""
    good = _panel_subs(tmp_path, "g", 10.0, 41.0, n=2)
    base = make_star_field(shape=(80, 80), n_stars=40, seed=9)
    bad = tmp_path / "sexagesimal.fit"
    write_color_fits(bad, base, exptime=10.0,
                     header={"OBJCTRA": "00 42 44.3", "OBJCTDEC": "+41 16 09"})

    pointings = read_pointings(good + [str(bad)])
    assert set(pointings) == set(good)


def test_stack_panels_produces_one_master_per_panel(tmp_path):
    paths = (_panel_subs(tmp_path, "a", 10.0, 41.0, seed=1)
             + _panel_subs(tmp_path, "b", 10.0, 42.5, seed=2))
    panels = discover_panels(read_pointings(paths), max_spread_deg=0.56)
    assert len(panels) == 2

    stacks, dropped = stack_panels(panels, str(tmp_path), method="average",
                                   kappa=2.5, min_panel_subs=4)
    assert len(stacks) == 2
    assert dropped == []
    for s in stacks:
        assert s.frame_count == 5
        assert s.integration_seconds == 50.0
        assert s.peak > 0.0


def test_thin_panels_are_dropped_and_named(tmp_path):
    """A two-sub panel is a slew, not data: too shallow to solve reliably and
    too noisy to blend. Dropping it silently would leave the user wondering
    where the frames went."""
    paths = (_panel_subs(tmp_path, "a", 10.0, 41.0, n=5, seed=1)
             + _panel_subs(tmp_path, "stray", 10.0, 44.0, n=2, seed=3))
    panels = discover_panels(read_pointings(paths), max_spread_deg=0.56)

    stacks, dropped = stack_panels(panels, str(tmp_path), method="average",
                                   kappa=2.5, min_panel_subs=4)
    assert len(stacks) == 1
    assert len(dropped) == 2
    assert all("only 2 subs" in reason for _path, reason in dropped)
    assert {p for p, _ in dropped} == {p for p in paths if "stray" in p}


def _panel_wcs(ra, dec, shape=(80, 80)):
    from astropy.wcs import WCS
    w = WCS(naxis=2)
    w.wcs.crpix = [shape[1] / 2, shape[0] / 2]
    w.wcs.crval = [ra, dec]
    w.wcs.cdelt = [-0.001, 0.001]
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return w


def test_run_mosaic_assembles_a_canvas_bigger_than_one_panel(tmp_path):
    """Two pointings offset in Dec must produce a canvas taller than one frame —
    the whole point of the feature."""
    from nocturne.stacking.mosaic import MosaicOptions, run_mosaic

    paths = (_panel_subs(tmp_path, "a", 10.0, 41.00, seed=1)
             + _panel_subs(tmp_path, "b", 10.0, 41.05, seed=2))

    def fake_solver(master_path):
        # panels come back north-first, so panel_01 is the higher-Dec pointing
        dec = 41.05 if "panel_01" in master_path else 41.00
        return _panel_wcs(10.0, dec), (80, 80)

    out = tmp_path / "mosaic.fits"
    result = run_mosaic(
        MosaicOptions(include=paths, output_path=str(out), astap_path="unused",
                      method="average", kappa=2.5,
                      # 0.05 deg apart, so the default 0.56 deg radius (sized for
                      # the S30 Pro's 2.24 deg frame) would merge them into one
                      # panel; these synthetic frames are 0.08 deg across
                      max_spread_deg=0.02),
        solver=fake_solver)

    assert result.panel_count == 2
    assert result.frame_count == 10
    assert result.integration_seconds == 100.0
    assert result.image.data.shape[0] > 80, "canvas must be taller than one panel"
    assert result.image.data.ndim == 3
    assert out.exists()


def test_run_mosaic_refuses_a_single_pointing(tmp_path):
    """One pointing is an ordinary stack. Silently producing a one-panel
    'mosaic' would be a worse answer than saying so."""
    from nocturne.stacking.mosaic import MosaicOptions, run_mosaic

    paths = _panel_subs(tmp_path, "a", 10.0, 41.0, n=5)
    opts = MosaicOptions(include=paths, output_path=str(tmp_path / "m.fits"),
                         astap_path="unused")
    with pytest.raises(ValueError, match="one pointing"):
        run_mosaic(opts, solver=lambda p: (_panel_wcs(10.0, 41.0), (80, 80)))


def test_run_mosaic_needs_two_panels_on_the_sky(tmp_path):
    """Panels that will not solve cannot be placed. One survivor is not a
    mosaic, and saying so beats writing a single-panel file called one."""
    from nocturne.stacking.mosaic import MosaicOptions, run_mosaic

    paths = (_panel_subs(tmp_path, "a", 10.0, 41.00, seed=1)
             + _panel_subs(tmp_path, "b", 10.0, 41.05, seed=2))
    opts = MosaicOptions(include=paths, output_path=str(tmp_path / "m.fits"),
                         astap_path="unused", method="average", max_spread_deg=0.02)

    def only_one_solves(master_path):
        if "panel_01" in master_path:
            return _panel_wcs(10.0, 41.05), (80, 80)
        return None

    with pytest.raises(ValueError, match="two panels"):
        run_mosaic(opts, solver=only_one_solves)


def test_a_missing_astap_is_refused_before_any_stacking(tmp_path):
    """Mosaic geometry comes from astrometry, so no solver is fatal. The
    benchmark showed what finding out late costs: every panel stacked, twenty
    minutes spent, then an ImportError. One stat call up front instead — and
    nothing may be written."""
    from nocturne.stacking.mosaic import MosaicOptions, run_mosaic

    paths = (_panel_subs(tmp_path, "a", 10.0, 41.00, seed=1)
             + _panel_subs(tmp_path, "b", 10.0, 41.05, seed=2))
    out = tmp_path / "m.fits"
    opts = MosaicOptions(include=paths, output_path=str(out),
                         astap_path=str(tmp_path / "no-such-astap"),
                         method="average", max_spread_deg=0.02)

    with pytest.raises(ValueError, match="ASTAP"):
        run_mosaic(opts)                 # no solver injected: the real path
    assert not out.exists()


def test_read_pointings_does_not_decode_pixels(tmp_path, monkeypatch):
    """Grouping needs two header cards. Decoding and debayering every frame to
    get them cost 191 ms against getheader's 1 ms — 75 seconds of dead air on
    the real 392-sub set before the first progress line."""
    import nocturne.stacking.mosaic as mosaic

    paths = _panel_subs(tmp_path, "a", 10.0, 41.0, n=3)

    def explode(*a, **k):
        raise AssertionError("read_pointings must not load pixel data")

    monkeypatch.setattr(mosaic, "load_fits", explode)
    pointings = mosaic.read_pointings(paths)
    assert len(pointings) == 3
    assert pointings[paths[0]] == pytest.approx((10.0, 41.0))


def test_work_dir_keeps_the_panel_masters(tmp_path):
    """A 40-minute stack must not be thrown away. With work_dir set, the panel
    masters survive the run — for the user to inspect, and so blending can be
    re-tried without re-stacking."""
    from nocturne.stacking.mosaic import MosaicOptions, run_mosaic

    paths = (_panel_subs(tmp_path, "a", 10.0, 41.00, seed=1)
             + _panel_subs(tmp_path, "b", 10.0, 41.05, seed=2))
    work = tmp_path / "work"

    def fake_solver(master_path):
        dec = 41.05 if "panel_01" in master_path else 41.00
        return _panel_wcs(10.0, dec), (80, 80)

    run_mosaic(MosaicOptions(include=paths, output_path=str(tmp_path / "m.fits"),
                             astap_path="unused", method="average",
                             max_spread_deg=0.02, work_dir=str(work)),
               solver=fake_solver)

    masters = sorted(p.name for p in work.glob("panel_*.fits"))
    assert masters == ["panel_01.fits", "panel_02.fits"]


def test_an_existing_panel_master_is_reused_not_restacked(tmp_path):
    """Resuming must skip the expensive part. If a panel master is already on
    disk from an earlier run, run_stack must not be called for it again."""
    import nocturne.stacking.mosaic as mosaic
    from nocturne.stacking.mosaic import MosaicOptions, run_mosaic

    paths = (_panel_subs(tmp_path, "a", 10.0, 41.00, seed=1)
             + _panel_subs(tmp_path, "b", 10.0, 41.05, seed=2))
    work = tmp_path / "work"

    def fake_solver(master_path):
        dec = 41.05 if "panel_01" in master_path else 41.00
        return _panel_wcs(10.0, dec), (80, 80)

    opts = MosaicOptions(include=paths, output_path=str(tmp_path / "m.fits"),
                         astap_path="unused", method="average",
                         max_spread_deg=0.02, work_dir=str(work))
    run_mosaic(opts, solver=fake_solver)

    calls = []
    real = mosaic.run_stack
    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)
    mosaic.run_stack = counting
    try:
        result = run_mosaic(opts, solver=fake_solver)
    finally:
        mosaic.run_stack = real

    assert calls == [], "panel masters already on disk must not be re-stacked"
    assert result.panel_count == 2
    assert result.frame_count == 10       # still reported from the panel groups
