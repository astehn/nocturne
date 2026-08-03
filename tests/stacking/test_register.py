import numpy as np
from skimage.transform import SimilarityTransform, warp
from nocturne.stacking.register import find_transform, warp_to
from tests.stacking.synthetic import make_star_field


def test_register_recovers_shift_and_rotation():
    ref = make_star_field(n_stars=40, seed=1)
    t = SimilarityTransform(translation=(3, -2), rotation=np.deg2rad(2))
    moved = warp(ref, t.inverse, order=1, preserve_range=True).astype(np.float32)

    matrix = find_transform(moved, ref)
    aligned = warp_to(moved, matrix)

    c = (slice(12, -12), slice(12, -12))
    corr = np.corrcoef(aligned[c].ravel(), ref[c].ravel())[0, 1]
    assert corr > 0.9


def test_warp_to_handles_color():
    data = np.zeros((20, 20, 3), np.float32)
    out = warp_to(data, np.eye(3))
    assert out.shape == (20, 20, 3)


def test_warp_with_validity_marks_the_area_the_frame_did_not_reach():
    """The mask is what stops partial coverage diluting the average. `warp`
    fills outside with ZERO and zero is a legal pixel value, so the warped array
    alone cannot say whether a dark pixel was sky or absence."""
    from skimage.transform import SimilarityTransform
    from nocturne.stacking.register import warp_with_validity
    data = np.full((20, 20), 0.5, np.float32)
    shift = np.asarray(SimilarityTransform(translation=(6, 0)).params, float)
    warped, valid = warp_with_validity(data, shift)
    assert valid.shape == (20, 20) and valid.dtype == bool
    assert valid[:, 10].all(), "the interior must be valid"
    assert not valid[:, 0].any(), "shifted-in columns are not covered"
    # the crux: those columns ARE zero in the data, and must not read as sky
    assert warped[:, 0].max() == 0.0


def test_warp_with_validity_excludes_partially_interpolated_edge_pixels():
    """Bilinear interpolation blends real data with the zero fill at the
    boundary, so a fractionally-covered pixel is already too dark. Counting it
    as valid would reintroduce a one-pixel version of the border ramp."""
    from skimage.transform import SimilarityTransform
    from nocturne.stacking.register import warp_with_validity
    data = np.full((20, 20), 0.5, np.float32)
    half = np.asarray(SimilarityTransform(translation=(3.5, 0)).params, float)
    warped, valid = warp_with_validity(data, half)
    partial = (warped > 0) & (warped < 0.5 - 1e-6)
    assert partial.any(), "expected a partially-interpolated column to exist"
    assert not (partial & valid).any(), "a partly-covered pixel was called valid"
