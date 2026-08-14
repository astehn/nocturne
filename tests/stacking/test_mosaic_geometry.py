import numpy as np
import pytest
from astropy.wcs import WCS

from nocturne.stacking.mosaic import (CanvasTooLarge, Panel, PanelStack,
                                      global_frame, solve_panels)


def _wcs(ra, dec, shape=(80, 80), scale_deg=0.001):
    w = WCS(naxis=2)
    w.wcs.crpix = [shape[1] / 2, shape[0] / 2]
    w.wcs.crval = [ra, dec]
    w.wcs.cdelt = [-scale_deg, scale_deg]
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return w


def _stack(path, ra, dec):
    return PanelStack(Panel(ra, dec, (path,)), path, 1.0, 5, 50.0)


class _FakeSolver:
    """Stands in for ASTAP: a real solve is far too slow and machine-dependent
    for a unit test. The real solver is exercised by the benchmark script."""

    def __init__(self, fails=()):
        self.fails = set(fails)
        self.calls = []

    def __call__(self, master_path):
        self.calls.append(master_path)
        if master_path in self.fails:
            return None
        return _wcs(10.0, 41.0), (80, 80)


def test_every_panel_is_solved_once():
    stacks = [_stack("a.fits", 10.0, 41.0), _stack("b.fits", 10.0, 42.5)]
    solver = _FakeSolver()
    solved, unsolved = solve_panels(stacks, "unused", solver=solver)
    assert len(solved) == 2
    assert unsolved == []
    assert solver.calls == ["a.fits", "b.fits"]


def test_an_unsolved_panel_is_reported_not_guessed():
    """Mosaic geometry comes from astrometry. A panel we could not solve has no
    place on the canvas, and inventing one would put its stars in the wrong
    sky."""
    stacks = [_stack("a.fits", 10.0, 41.0), _stack("b.fits", 10.0, 42.5)]
    solved, unsolved = solve_panels(stacks, "unused",
                                    solver=_FakeSolver(fails={"b.fits"}))
    assert [s.stack.master_path for s in solved] == ["a.fits"]
    assert len(unsolved) == 1
    assert unsolved[0][0] == "b.fits"
    assert "solve" in unsolved[0][1].lower()


# --- global frame ------------------------------------------------------------

def _solved(ra, dec, shape=(80, 80), scale_deg=0.001):
    from nocturne.stacking.mosaic import SolvedPanel
    return SolvedPanel(_stack(f"{ra}_{dec}.fits", ra, dec),
                       _wcs(ra, dec, shape, scale_deg), shape)


def test_canvas_covers_every_panel():
    panels = [_solved(10.0, 41.0), _solved(10.1, 41.0), _solved(10.0, 41.1)]
    wcs, (h, w) = global_frame(panels)
    for p in panels:
        ph, pw = p.shape
        sky = p.wcs.pixel_to_world_values([0, pw, 0, pw], [0, 0, ph, ph])
        x, y = wcs.world_to_pixel_values(sky[0], sky[1])
        assert x.min() >= -0.5 and x.max() <= w + 0.5
        assert y.min() >= -0.5 and y.max() <= h + 0.5


def test_a_single_panel_canvas_is_about_one_frame():
    _wcs_out, (h, w) = global_frame([_solved(10.0, 41.0)])
    assert 78 <= h <= 84 and 78 <= w <= 84


def test_too_large_a_canvas_is_refused_with_its_size_in_the_message():
    """An 8 GB Air is a target machine. Refusing loudly beats swapping.

    The threshold is lowered rather than the panels flung 30 degrees apart: at
    0.001 deg/px that separation is only ~2 megapixels, and pushing far enough
    to breach 250 would also drag the TAN projection into angles where its
    behaviour, not the guard, is what the test measures.
    """
    panels = [_solved(10.0, 41.0), _solved(11.0, 42.0)]     # ~1000x1000 px
    with pytest.raises(CanvasTooLarge) as exc:
        global_frame(panels, max_megapixels=0.5)
    message = str(exc.value).lower()
    assert "megapixel" in message
    assert "0.5" in message                                  # the limit it broke
    assert " x " in message                                  # and the size it wanted


def test_a_canvas_within_the_limit_is_allowed():
    """The complement: the guard must not fire on ordinary mosaics."""
    panels = [_solved(10.0, 41.0), _solved(10.1, 41.1)]
    _w, (h, w) = global_frame(panels, max_megapixels=250.0)
    assert h > 80 and w > 80
