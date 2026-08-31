"""Noise2Noise pairs: two stacks of the same sky that share no frame.

The whole method rests on the two halves being the same scene with independent
noise. Every test here is about that, because v1 died of the two halves quietly
not being comparable — different coverage at the rotation envelope meant
subtracting them left scene rather than noise.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

import pairs as P  # noqa: E402

from tests.stacking.synthetic import make_star_field, write_color_fits  # noqa: E402


def _subs(tmp_path, n=8, seed=0, shift=0.0, noise=0.01):
    """n frames of one star field, each with its own noise.

    `shift` moves the field a little per frame, which is what dithering does and
    what makes the covered region differ between any two subsets.
    """
    rng = np.random.default_rng(seed)
    base = make_star_field(shape=(64, 64), n_stars=12, seed=99)
    paths = []
    for i in range(n):
        img = base.copy()
        if shift:
            k = int(round(shift * (i % 3 - 1)))
            img = np.roll(img, k, axis=1)
        img = np.clip(img + rng.normal(0, noise, img.shape), 0, 1).astype(np.float32)
        p = tmp_path / f"sub_{i:03d}.fits"
        write_color_fits(str(p), img)
        paths.append(str(p))
    return paths


# --- the property v1 broke ---------------------------------------------------

def test_the_two_halves_share_no_frame():
    """If a frame appears in both halves its noise is common to both, and the
    model can lower its loss by reproducing that noise instead of removing it."""
    rng = np.random.default_rng(0)
    for _ in range(20):
        a, b = P.split_disjoint(list(range(12)), depth=4, rng=rng)
        assert len(a) == len(b) == 4
        assert not set(a) & set(b), f"frame in both halves: {set(a) & set(b)}"


def test_a_pair_uses_exactly_twice_the_depth_it_was_asked_for():
    rng = np.random.default_rng(0)
    a, b = P.split_disjoint(list(range(100)), depth=17, rng=rng)
    assert len(set(a) | set(b)) == 34


def test_asking_for_more_depth_than_frames_allows_is_refused(tmp_path):
    """Silently returning a shallower pair would mislabel the depth in the
    manifest, and depth is what the model is conditioned on."""
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError, match="needs 20 frames|only 9"):
        P.split_disjoint(list(range(9)), depth=10, rng=rng)


def test_the_halves_land_on_the_same_pixel_grid(tmp_path):
    """v1 integrated each half to its own extent. Where one covered a pixel and
    the other did not, the difference between them was SCENE, not noise — which
    is how a noise field ended up correlated with its own target."""
    paths = _subs(tmp_path, n=8, shift=3.0)
    prep = P.prepare(paths, workers=1)
    a, b = P.make_pair(prep, depth=4, rng=np.random.default_rng(1))
    assert a.shape == b.shape
    assert a.ndim == 3 and a.shape[2] == 3


def test_the_crop_is_where_BOTH_halves_are_covered_not_either_one(tmp_path):
    """Constructed rather than stacked, because a synthetic dither is too tidy
    to produce halves whose coverage differs — the first version of this test
    passed against the very bug it was written for.

    Half A is blind down the left edge, half B down the right. Either half's own
    extent, or their union, keeps a strip only one of them saw; there the
    difference between the halves is SCENE, and that is what v1 was training on.
    """
    cov_a = np.ones((40, 40), np.float32)
    cov_a[:, :6] = 0.0                       # A saw nothing in the left 6 columns
    cov_b = np.ones((40, 40), np.float32)
    cov_b[:, -5:] = 0.0                      # B saw nothing in the right 5
    top, bottom, left, right = P.common_bounds(cov_a, cov_b)
    assert left >= 6, f"kept {6 - left} columns only half B saw"
    assert right <= 35, f"kept {right - 35} columns only half A saw"
    assert (top, bottom) == (0, 40)


def test_a_pair_contains_no_partly_covered_pixel(tmp_path):
    """End to end: whatever survives the crop was seen by every frame of both
    halves, so its noise really is the depth the manifest claims."""
    paths = _subs(tmp_path, n=8, shift=4.0)
    prep = P.prepare(paths, workers=1)
    _, _, cov_a, cov_b = P.make_pair(prep, depth=4, rng=np.random.default_rng(2),
                                     return_coverage=True)
    assert cov_a.min() >= 0.999, f"half A has partly-covered pixels: {cov_a.min()}"
    assert cov_b.min() >= 0.999, f"half B has partly-covered pixels: {cov_b.min()}"


def test_the_scale_is_one_number_taken_from_both_halves():
    """Comparing the halves' means is NOT enough — the first version of this
    test did that with a 2% tolerance and passed happily while each half was
    being divided by its own peak. Two halves of one stack have nearly equal
    means by construction, so that test could never have failed.

    The discriminating property: one shared divisor cannot map both halves to
    the same peak unless they already had one."""
    a = np.full((8, 8), 0.5, np.float32)
    b = np.full((8, 8), 0.5, np.float32)
    a[0, 0], b[0, 0] = 1.0, 0.6              # A is the brighter half
    assert P.shared_scale(a, b) == pytest.approx(0.8)   # peak of their mean
    assert P.shared_scale(a, b) == P.shared_scale(b, a), "must not favour a half"


def test_a_brighter_half_stays_brighter_after_scaling(tmp_path):
    """End to end. Per-half scaling forces both peaks to exactly 1.0 and erases
    the difference between them; one shared divisor preserves it."""
    paths = _subs(tmp_path, n=8, noise=0.01)
    prep = P.prepare(paths, workers=1)
    a, b = P.make_pair(prep, depth=4, rng=np.random.default_rng(3))
    assert not (a.max() == pytest.approx(1.0, abs=1e-6)
                and b.max() == pytest.approx(1.0, abs=1e-6)), (
        "both halves peak at exactly 1.0 — each was scaled by its own maximum")


def test_the_difference_between_halves_is_noise_not_scene(tmp_path):
    """THE test. D = A - B must be uncorrelated with M = (A + B) / 2.

    Measured on v1's manufactured tiles, this correlation reached 0.46 against a
    null of 0.03 — the field partly cancelled the target's noise where the target
    was bright, a structured noise-scene relationship a model can learn instead
    of denoising. Real disjoint halves must not do that.
    """
    paths = _subs(tmp_path, n=16, shift=2.0, noise=0.02)
    prep = P.prepare(paths, workers=1)
    rs = []
    for s in range(6):
        a, b = P.make_pair(prep, depth=6, rng=np.random.default_rng(s))
        d, m = (a - b).ravel(), ((a + b) / 2).ravel()
        d, m = d - d.mean(), m - m.mean()
        denom = np.sqrt((d * d).sum() * (m * m).sum())
        rs.append(abs(float((d * m).sum() / denom)) if denom else 0.0)
    assert max(rs) < 0.2, f"difference tracks the scene: |r| up to {max(rs):.3f}"


def test_the_same_seed_gives_the_same_pair(tmp_path):
    """A pair that cannot be reproduced cannot be investigated later."""
    paths = _subs(tmp_path, n=10)
    prep = P.prepare(paths, workers=1)
    a1, _ = P.make_pair(prep, depth=4, rng=np.random.default_rng(7))
    a2, _ = P.make_pair(prep, depth=4, rng=np.random.default_rng(7))
    assert np.array_equal(a1, a2)


def test_registering_happens_once_for_any_number_of_pairs(tmp_path):
    """Registration is the expensive half. v1 re-registered per target depth,
    which cost a full pass over the frames for every rung."""
    paths = _subs(tmp_path, n=10)
    calls = {"n": 0}
    real = P.register_frames

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    P.register_frames = counting
    try:
        prep = P.prepare(paths, workers=1)
        for s in range(4):
            P.make_pair(prep, depth=3, rng=np.random.default_rng(s))
    finally:
        P.register_frames = real
    assert calls["n"] == 1, f"registered {calls['n']} times for 4 pairs"


def test_frames_that_fail_to_register_are_dropped_not_stacked(tmp_path):
    """A frame with no transform cannot be placed on the grid. Including it
    would put an unregistered field into one half."""
    paths = _subs(tmp_path, n=6)
    junk = tmp_path / "sub_junk.fits"
    write_color_fits(str(junk), np.zeros((64, 64), np.float32))
    prep = P.prepare(paths + [str(junk)], workers=1)
    assert str(junk) not in prep.paths
    assert len(prep.paths) >= 5
