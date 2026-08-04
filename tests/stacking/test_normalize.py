"""Bringing every frame to a common sky level before they are combined.

Why this exists: on a real M31 session the sky background varied 262% between
frames (0.088 to 0.427). An interior pixel averages every frame, so its
background is the mean of all of them; a fringe pixel averages only the subset
that reached it, whose mean background is different. Every coverage boundary
therefore became a step in sky level, and the rotation envelope was drawn on the
finished picture as curved bands — seen 2026-08-03.
"""
import numpy as np
import pytest

from nocturne.stacking.normalize import frame_stats, normalize_to


def _sky(loc, scale, shape=(64, 64, 3), seed=0):
    rng = np.random.default_rng(seed)
    return (rng.normal(0.0, 1.0, shape) * scale + loc).astype(np.float32)


def test_an_offset_frame_is_brought_back_to_the_reference_level():
    ref = _sky(0.20, 0.01, seed=1)
    dim = _sky(0.50, 0.01, seed=2)          # much brighter sky, same signal
    out = normalize_to(dim, frame_stats(dim), frame_stats(ref))
    assert np.median(out) == pytest.approx(np.median(ref), abs=0.005)


def test_a_differently_scaled_frame_is_brought_back():
    ref = _sky(0.20, 0.01, seed=1)
    stretched = _sky(0.20, 0.04, seed=2)    # same level, 4x the spread
    out = normalize_to(stretched, frame_stats(stretched), frame_stats(ref))
    ref_s, out_s = frame_stats(ref)[1], frame_stats(out)[1]
    assert np.allclose(out_s, ref_s, rtol=0.15)


def test_each_channel_is_normalized_independently():
    """Real skies are not grey. On the M31 frames the channel medians were
    R 25020, G 21404, B 37546 — a global correction would leave the colour
    cast in place and it would still vary frame to frame."""
    ref = np.stack([_sky(0.20, 0.01, (32, 32), 1),
                    _sky(0.30, 0.01, (32, 32), 2),
                    _sky(0.50, 0.01, (32, 32), 3)], axis=2)
    other = np.stack([_sky(0.40, 0.01, (32, 32), 4),
                      _sky(0.35, 0.01, (32, 32), 5),
                      _sky(0.25, 0.01, (32, 32), 6)], axis=2)
    out = normalize_to(other, frame_stats(other), frame_stats(ref))
    for c, expect in enumerate((0.20, 0.30, 0.50)):
        assert np.median(out[..., c]) == pytest.approx(expect, abs=0.01), \
            f"channel {c} not matched to the reference"


def test_the_reference_frame_is_left_alone():
    ref = _sky(0.20, 0.01, seed=1)
    s = frame_stats(ref)
    out = normalize_to(ref, s, s)
    assert np.allclose(out, ref, atol=1e-5)


def test_stars_do_not_drag_the_estimate():
    """Location and scale must be robust. A mean/std pair would be pulled by
    every bright star, and a frame full of stars would be 'corrected' for
    signal it was supposed to keep."""
    plain = _sky(0.20, 0.01, seed=1)
    starry = plain.copy()
    rng = np.random.default_rng(9)
    ys, xs = rng.integers(0, 64, 200), rng.integers(0, 64, 200)
    starry[ys, xs] = 1.0                    # 5% of pixels are saturated stars
    a, b = frame_stats(plain), frame_stats(starry)
    assert np.allclose(a[0], b[0], atol=0.005), "stars moved the location estimate"
    assert np.allclose(a[1], b[1], rtol=0.25), "stars moved the scale estimate"


def test_a_flat_frame_does_not_blow_up():
    """A frame with no variation has zero scale. Dividing by it would produce
    inf/NaN and poison every pixel it touches."""
    flat = np.full((16, 16, 3), 0.3, np.float32)
    ref = _sky(0.20, 0.01, (16, 16, 3), seed=1)
    out = normalize_to(flat, frame_stats(flat), frame_stats(ref))
    assert np.isfinite(out).all()


def test_mono_frames_work_too():
    ref = _sky(0.20, 0.01, (32, 32), seed=1)
    other = _sky(0.45, 0.01, (32, 32), seed=2)
    out = normalize_to(other, frame_stats(other), frame_stats(ref))
    assert out.shape == other.shape
    assert np.median(out) == pytest.approx(np.median(ref), abs=0.005)


def test_stats_are_subsampled_but_still_accurate():
    """Full-resolution median/MAD costs 338 ms per frame — 13 minutes on a
    2361-frame stack. A stride-8 subsample costs 6 ms and was measured on a real
    frame to agree to 0.004% on the median and 0.18% on the MAD."""
    big = _sky(0.20, 0.01, (512, 512, 3), seed=4)
    loc, scale = frame_stats(big)
    exact_loc = np.median(big, axis=(0, 1))
    exact_scale = np.median(np.abs(big - exact_loc), axis=(0, 1)) * 1.4826
    assert np.allclose(loc, exact_loc, rtol=0.02)
    assert np.allclose(scale, exact_scale, rtol=0.05)


def test_normalization_preserves_relative_signal():
    """The point is to move the BACKGROUND, not to flatten the picture. A star
    sitting N sigma above sky in the input must still be N sigma above sky
    afterwards, or normalization would be destroying the data it exists to
    combine."""
    ref = _sky(0.20, 0.01, seed=1)
    other = _sky(0.50, 0.03, seed=2)
    loc, scale = frame_stats(other)
    other[10, 10] = loc[0] + 8.0 * scale[0]        # an 8-sigma star
    out = normalize_to(other, frame_stats(other), frame_stats(ref))
    r_loc, r_scale = frame_stats(ref)
    sigmas = (out[10, 10, 0] - r_loc[0]) / r_scale[0]
    assert sigmas == pytest.approx(8.0, rel=0.15), \
        f"the star came out at {sigmas:.1f} sigma instead of 8"
