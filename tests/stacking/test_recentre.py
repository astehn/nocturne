"""The stacking canvas anchors on the middle of the drift, not the first frame.

Andreas' 186-frame NGC 7000 set stacked with a wide band of barely-covered data
down one side (2026-09-06). The cause was the reference frame: registration
anchors on paths[0], and over a session the field drifts, so the first sub sits
at one END of that drift and half its footprint only ever saw the early frames.
"""
import numpy as np
import pytest

from nocturne.stacking.stacker import _recentre


def _shift(dx, dy):
    m = np.eye(3)
    m[0, 2], m[1, 2] = dx, dy
    return m


def test_anchor_moves_to_the_middle_of_a_one_way_drift():
    # Frames march steadily right: 0, 100, ... 400. The middle is +200.
    used = [f"f{i}" for i in range(5)]
    transforms = {p: _shift(100 * i, 0) for i, p in enumerate(used)}
    _recentre(transforms, used)
    xs = sorted(float(transforms[p][0, 2]) for p in used)
    assert xs == [-200.0, -100.0, 0.0, 100.0, 200.0]
    # The drift is now centred on the canvas rather than running off one side.
    assert abs(np.median(xs)) < 1e-9


def test_relative_alignment_is_untouched():
    """Re-basing must move the canvas, never the frames within it.

    The invariant is the map from frame i's pixels to frame j's, which is
    inv(M_j) @ M_i; re-basing by T cancels, since (T M_j)^-1 (T M_i) is
    M_j^-1 M_i. The first version of this test asserted M_i @ inv(M_j) instead.
    That form is a CONJUGATION by T, so it changes by hundreds of pixels under a
    perfectly correct re-base — and it passed anyway, because every matrix in
    the fixture was a pure translation and translations commute. Measured on
    real data it read 2.2e+02 for the wrong form against 2.9e-13 for this one:
    a fixture with no rotation cannot tell a correct re-base from a broken one.
    """
    rot = np.eye(3)
    c, s = np.cos(0.2), np.sin(0.2)
    rot[:2, :2] = [[c, -s], [s, c]]
    used = [f"f{i}" for i in range(5)]
    before = {p: rot @ _shift(100 * i, 50 * i) if i % 2 else _shift(100 * i, 50 * i)
              for i, p in enumerate(used)}
    after = {k: v.copy() for k, v in before.items()}
    _recentre(after, used)
    for a in used:
        for b in used:
            was = np.linalg.inv(before[b]) @ before[a]
            now = np.linalg.inv(after[b]) @ after[a]
            assert np.allclose(was, now), f"{a} -> {b} moved"


def test_a_set_that_does_not_drift_is_left_exactly_alone():
    used = [f"f{i}" for i in range(4)]
    transforms = {p: _shift(0, 0) for p in used}
    _recentre(transforms, used)
    for p in used:
        assert np.array_equal(transforms[p], np.eye(3))


def test_rotation_is_carried_through_not_dropped():
    a = np.eye(3)
    a[:2, :2] = [[0.0, -1.0], [1.0, 0.0]]      # 90 degrees
    used = ["f0", "f1", "f2"]
    transforms = {"f0": np.eye(3), "f1": a.copy(), "f2": _shift(500, 0)}
    _recentre(transforms, used)
    # f1 keeps its rotation relative to f0 whatever the anchor is.
    rel = transforms["f1"] @ np.linalg.inv(transforms["f0"])
    assert np.allclose(rel[:2, :2], a[:2, :2])


def test_frames_that_failed_to_register_are_skipped():
    """`used` and `transforms` can disagree: a rejected frame is in neither, but
    the caller passes both and the helper must not KeyError on a mismatch."""
    used = ["f0", "f1", "missing", "f2"]
    transforms = {"f0": _shift(0, 0), "f1": _shift(100, 0), "f2": _shift(200, 0)}
    _recentre(transforms, used)
    assert "missing" not in transforms
    assert len(transforms) == 3


def test_the_anchor_is_the_median_not_the_mean():
    """One frame far from the rest must not drag the canvas towards it — the
    reason for a median. A mean anchor would sit between the cluster and the
    outlier, where no frames are."""
    used = [f"f{i}" for i in range(6)]
    transforms = {p: _shift(x, 0) for p, x in
                  zip(used, [0, 10, 20, 30, 40, 5000])}
    _recentre(transforms, used)
    xs = [float(transforms[p][0, 2]) for p in used]
    # The anchor landed inside the cluster, not out towards the stray frame.
    assert abs(xs[2]) <= 10, xs


def test_composes_as_a_change_of_output_coordinates():
    """inv(anchor) @ m, not m @ inv(anchor).

    Both orders leave the anchor itself at the identity and both are invisible
    while every transform is a pure translation, because translations commute —
    which is exactly how the wrong order survives a plausible-looking test suite.
    It only separates once the anchor carries a rotation, and then it warps every
    other frame about the wrong origin.

    A point in frame i reaches frame-0 coordinates via M_i, and frame-c
    coordinates via inv(M_c). So the composition is inv(M_c) @ M_i, in that
    order.
    """
    rot = np.eye(3)
    c, s = np.cos(0.3), np.sin(0.3)
    rot[:2, :2] = [[c, -s], [s, c]]
    anchor = rot @ _shift(120, 40)          # the middle frame, rotated
    outer = _shift(400, 90)

    # Positions chosen so the median lands on the anchor.
    used = ["a", "b", "c"]
    transforms = {"a": _shift(-400, -90), "b": anchor, "c": outer}
    _recentre(transforms, used)

    inv = np.linalg.inv(anchor)
    assert np.allclose(transforms["b"], np.eye(3)), "anchor must become identity"
    assert np.allclose(transforms["c"], inv @ outer)
    assert not np.allclose(transforms["c"], outer @ inv), \
        "composed in the wrong order — every frame warped about the wrong origin"
