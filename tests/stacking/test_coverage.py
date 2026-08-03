import numpy as np
from nocturne.stacking.coverage import full_coverage_bounds, _largest_true_rectangle


def test_largest_true_rectangle_finds_block():
    mask = np.zeros((4, 5), bool)
    mask[1:3, 1:4] = True          # rows 1-2, cols 1-3 (a 2x3 block)
    assert _largest_true_rectangle(mask) == (1, 3, 1, 4)


def test_largest_true_rectangle_all_true():
    assert _largest_true_rectangle(np.ones((3, 6), bool)) == (0, 3, 0, 6)


def test_identity_transforms_cover_every_pixel():
    """Coverage now comes from integration itself rather than a second warp of a
    ones mask, so this asserts the property where it is actually produced."""
    from nocturne.stacking.integrate import average_integrate
    frames = [np.full((6, 6), 0.5, np.float32) for _ in range(3)]
    _, cov = average_integrate(frames)
    assert cov.shape == (6, 6)
    assert np.all(cov == 3)


def test_full_coverage_bounds_crops_to_covered_core():
    # A hand-built coverage map: only a central 4x4 core got all 5 frames.
    cov = np.zeros((10, 10), np.int32)
    cov[:] = 2                       # edges: partial coverage
    cov[3:7, 3:7] = 5                # core: full coverage
    top, bottom, left, right = full_coverage_bounds(cov, n_frames=5)
    assert (top, bottom, left, right) == (3, 7, 3, 7)


def test_full_coverage_bounds_falls_back_when_none_meets_threshold():
    cov = np.ones((8, 8), np.int32)  # every pixel covered by only 1 frame
    assert full_coverage_bounds(cov, n_frames=10) == (0, 8, 0, 8)


def test_the_default_threshold_keeps_pixels_within_sqrt2_of_interior_noise():
    """Pins the tuned constant, which the test above does not: it passes at any
    frac between ~0.3 and ~1.0 because its bands are far apart.

    The default is set by noise. Shot noise falls as sqrt(N), so half-covered
    pixels are sqrt(2) = 1.41x noisier than the fully covered interior — the
    point where a grainy border starts reading as a defect. Concentric bands at
    45% and 55% coverage straddle that line: the 55% band must be kept and the
    45% band must not.
    """
    import inspect
    from nocturne.stacking import coverage as c

    n = 20
    cov = np.full((n, n), 9, np.int32)      # 45% — one sqrt(2)+ too noisy
    cov[4:16, 4:16] = 11                    # 55% — inside the budget
    cov[8:12, 8:12] = n                     # fully covered core
    assert full_coverage_bounds(cov, n_frames=n) == (4, 16, 4, 16), \
        "the default no longer sits between 45% and 55% coverage"

    frac = inspect.signature(c.full_coverage_bounds).parameters["frac"].default
    assert np.sqrt(1.0 / frac) <= 1.45, \
        f"frac={frac} admits pixels {np.sqrt(1/frac):.2f}x noisier than the interior"
    assert frac <= 0.6, f"frac={frac} discards area the coverage fix made usable"


def test_a_sparse_fringe_is_still_cut_off():
    """The relaxation must not become 'keep everything'. A rim covered by a
    handful of frames is genuinely poor data and stays outside the crop."""
    n = 40
    cov = np.full((30, 30), 3, np.int32)    # 7.5% — a sparse rim
    cov[5:25, 5:25] = n
    assert full_coverage_bounds(cov, n_frames=n) == (5, 25, 5, 25)
