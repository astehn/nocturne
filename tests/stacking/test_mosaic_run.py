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
    panels = discover_panels(read_pointings(paths), radius_deg=0.56)
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
    panels = discover_panels(read_pointings(paths), radius_deg=0.56)

    stacks, dropped = stack_panels(panels, str(tmp_path), method="average",
                                   kappa=2.5, min_panel_subs=4)
    assert len(stacks) == 1
    assert len(dropped) == 2
    assert all("only 2 subs" in reason for _path, reason in dropped)
    assert {p for p, _ in dropped} == {p for p in paths if "stray" in p}
