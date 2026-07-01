import numpy as np
from skimage.transform import SimilarityTransform, warp
from seestar_processor.stacking.register import find_transform, warp_to
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
