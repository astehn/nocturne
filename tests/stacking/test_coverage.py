import numpy as np
from nocturne.stacking.coverage import (
    coverage_map, full_coverage_bounds, _largest_true_rectangle,
)


def test_largest_true_rectangle_finds_block():
    mask = np.zeros((4, 5), bool)
    mask[1:3, 1:4] = True          # rows 1-2, cols 1-3 (a 2x3 block)
    assert _largest_true_rectangle(mask) == (1, 3, 1, 4)


def test_largest_true_rectangle_all_true():
    assert _largest_true_rectangle(np.ones((3, 6), bool)) == (0, 3, 0, 6)


def test_coverage_map_identity_transforms_full():
    # Three identity transforms -> every pixel covered by all three.
    cov = coverage_map([np.eye(3), np.eye(3), np.eye(3)], (6, 6))
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
