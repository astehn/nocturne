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

from tests.stacking.synthetic import (  # noqa: E402
    make_star_field, write_cfa_fits, write_color_fits)


def _subs(tmp_path, n=8, seed=0, shift=0.0, noise=0.01):
    """n frames of one star field, each with its own noise, as CFA subs.

    CFA and not colour cubes, deliberately. `write_color_fits` produces a
    (3, H, W) cube, which is what an already-stacked master looks like on disk —
    `is_stacked_master` reads NAXIS=3 and says yes. Grading then rejects every
    frame, and the first version of these tests bypassed grading entirely and so
    never noticed. Real Seestar subs are 2D Bayer; the fixture is now too.

    `shift` moves the field per frame, which is what dithering does.

    Callers ask for more frames than they need: prepare() grades and rejects, as
    the Stack tool does, so a fixture sized exactly to the depth fails the moment
    grading throws one out.
    """
    rng = np.random.default_rng(seed)
    base = make_star_field(shape=(96, 96), n_stars=25, seed=99)
    paths = []
    for i in range(n):
        img = base.copy()
        if shift:
            img = np.roll(img, int(round(shift * (i % 3 - 1))), axis=1)
        img = np.clip(img + rng.normal(0, noise, img.shape), 0, 1).astype(np.float32)
        p = tmp_path / f"sub_{i:03d}.fit"
        write_cfa_fits(str(p), img)
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
    paths = _subs(tmp_path, n=14, shift=3.0)
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
    depth = 8
    cov_a = np.full((40, 40), depth, np.int32)
    cov_a[:, :6] = 0                         # A saw nothing in the left 6 columns
    cov_b = np.full((40, 40), depth, np.int32)
    cov_b[:, -5:] = 0                        # B saw nothing in the right 5
    top, bottom, left, right = P.common_bounds(cov_a, cov_b, depth)
    assert left >= 6, f"kept {6 - left} columns only half B saw"
    assert right <= 35, f"kept {right - 35} columns only half A saw"
    assert (top, bottom) == (0, 40)


def test_a_pixel_short_of_the_full_depth_is_cropped_away():
    """Coverage is a frame COUNT, not a fraction. Asking the app's own
    full_coverage_bounds with n_frames=1 means "at least one frame touched this"
    — and a real depth-16 pair came back containing pixels covered by a single
    frame, four times noisier than the depth it was labelled with. The synthetic
    dither was too tidy to show it; this is constructed so it cannot hide.
    """
    depth = 16
    cov_a = np.full((30, 30), depth, np.int32)
    cov_b = np.full((30, 30), depth, np.int32)
    cov_b[:, :4] = depth - 1                 # one frame short, not zero
    _, _, left, right = P.common_bounds(cov_a, cov_b, depth)
    assert left >= 4, "kept a column one frame short of the claimed depth"


def test_a_pair_with_no_common_ground_is_refused_not_returned_empty():
    depth = 4
    cov_a = np.zeros((20, 20), np.int32)
    cov_a[:, :10] = depth
    cov_b = np.zeros((20, 20), np.int32)
    cov_b[:, 10:] = depth                    # the halves overlap nowhere
    with pytest.raises(ValueError, match="no pixel is covered"):
        P.common_bounds(cov_a, cov_b, depth)


def test_a_pair_contains_no_partly_covered_pixel(tmp_path):
    """End to end: whatever survives the crop was seen by every frame of both
    halves, so its noise really is the depth the manifest claims."""
    paths = _subs(tmp_path, n=14, shift=4.0)
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
    paths = _subs(tmp_path, n=14, noise=0.01)
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
    paths = _subs(tmp_path, n=24, shift=2.0, noise=0.02)
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
    paths = _subs(tmp_path, n=14)
    prep = P.prepare(paths, workers=1)
    a1, _ = P.make_pair(prep, depth=4, rng=np.random.default_rng(7))
    a2, _ = P.make_pair(prep, depth=4, rng=np.random.default_rng(7))
    assert np.array_equal(a1, a2)


def test_registering_happens_once_for_any_number_of_pairs(tmp_path):
    """Registration is the expensive half. v1 re-registered per target depth,
    which cost a full pass over the frames for every rung."""
    paths = _subs(tmp_path, n=14)
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
    junk = tmp_path / "sub_junk.fit"
    write_cfa_fits(str(junk), np.zeros((96, 96), np.float32))
    prep = P.prepare(paths + [str(junk)], workers=1)
    assert str(junk) not in prep.paths
    assert len(prep.paths) >= 5


# --- why the split is interleaved and not random -----------------------------

def test_the_halves_are_dealt_alternately_from_a_contiguous_run():
    """Both halves must sample the same sky conditions.

    Measured on IC 1396A, which spans 2026-08-11..08-26, corr(A-B, mean) against
    a null of +-0.0006:

                     random split                interleaved
        depth 16   +0.210 +-0.319  max 0.637   +0.017 +-0.060  max 0.132
        depth 32   -0.232 +-0.163  max 0.430   -0.007 +-0.036  max 0.070
        depth 64   -0.002 +-0.303  max 0.534   -0.015 +-0.065  max 0.094

    A random draw across fifteen nights gives each half a different mix of
    conditions; the difference in average sky is a smooth gradient that tracks
    the scene, so A-B carries structure rather than only noise. The random
    split's worst case is WORSE than the 0.46 that retired v1.
    """
    ordered = list(range(100))
    a, b = P.split_disjoint(ordered, depth=8, rng=np.random.default_rng(0))
    both = sorted(a + b)
    assert both == list(range(both[0], both[0] + 16)), (
        f"the 16 frames are not contiguous in time: {both}")
    assert a == both[0::2] and b == both[1::2], (
        f"not dealt alternately — A={a} B={b}")


def test_neither_half_is_systematically_earlier_than_the_other():
    """The point of dealing alternately: if half A were simply the first N
    frames it would carry the start of the session and half B the end, which is
    the very condition difference this avoids."""
    for seed in range(6):
        a, b = P.split_disjoint(list(range(200)), depth=10,
                                rng=np.random.default_rng(seed))
        assert abs(np.mean(a) - np.mean(b)) <= 1.0, (
            f"halves sit at different points in the session: {np.mean(a)} vs {np.mean(b)}")


def test_frames_are_ordered_by_the_header_not_the_filename(tmp_path):
    """Seestar filenames do encode the timestamp, but a name is a convention and
    a header is a record — a renamed or re-exported frame would sort wrong and
    the damage would look like noise."""
    from astropy.io import fits
    base = make_star_field(shape=(96, 96), n_stars=20, seed=1)
    paths = []
    for name, when in (("z_last.fit", "2026-08-11T21:00:00"),
                       ("a_first.fit", "2026-08-26T23:00:00"),
                       ("m_mid.fit", "2026-08-20T22:00:00")):
        p = tmp_path / name
        write_cfa_fits(str(p), base)
        with fits.open(str(p), mode="update") as h:
            h[0].header["DATE-OBS"] = when
        paths.append(str(p))
    got = [os.path.basename(p) for p in P.time_order(paths)]
    assert got == ["z_last.fit", "m_mid.fit", "a_first.fit"], got


def test_a_frame_with_no_readable_date_still_sorts_somewhere(tmp_path):
    """An unreadable header must not take the build down; it sorts last, by
    name, and the pair is still usable."""
    base = make_star_field(shape=(96, 96), n_stars=20, seed=1)
    p = tmp_path / "no_date.fit"
    write_cfa_fits(str(p), base)
    assert P.time_order([str(p)]) == [str(p)]
