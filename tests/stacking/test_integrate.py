import numpy as np
import pytest
from nocturne.stacking.integrate import average_integrate, sigma_clip_integrate


def test_average_equals_numpy_mean():
    frames = [np.full((2, 2), 0.2, np.float32), np.full((2, 2), 0.4, np.float32)]
    out, cov = average_integrate(frames)
    assert np.allclose(out, 0.3, atol=1e-6)
    assert np.array_equal(cov, np.full((2, 2), 2))


def test_average_empty_raises():
    with pytest.raises(ValueError):
        average_integrate([])


def test_sigma_clip_rejects_hot_frame():
    values = [0.5] * 9 + [5.0]  # one satellite/hot outlier at every pixel
    frames = [np.full((2, 2), v, np.float32) for v in values]
    out, cov = sigma_clip_integrate(lambda: iter(frames), kappa=2.5)
    assert np.allclose(out, 0.5, atol=1e-6)  # outlier rejected -> mean of the 9
    assert np.array_equal(cov, np.full((2, 2), 10))   # all ten COVERED the pixel


# --- partial coverage: the M31 border bug ------------------------------------
# A frame that does not cover a pixel must not vote on it. Before this, warp
# filled outside with 0 and the divisor was the frame COUNT, so an edge pixel
# covered by 10 of 80 frames came out at 12% of its true brightness — measured
# on real M31 subs 2026-08-03.

def _half_covered(value=0.2, n=8, covered=3):
    """n frames over a 1x4 strip; only `covered` of them see the last column."""
    frames = []
    for i in range(n):
        arr = np.full((1, 4), value, np.float32)
        valid = np.ones((1, 4), bool)
        if i >= covered:
            arr[0, 3] = 0.0            # warp's out-of-frame fill
            valid[0, 3] = False
        frames.append((arr, valid))
    return frames


def test_average_ignores_frames_that_did_not_cover_a_pixel():
    frames = _half_covered()
    out, cov = average_integrate(frames)
    assert np.allclose(out, 0.2, atol=1e-6), \
        f"partially-covered column diluted to {out[0, 3]:.4f} instead of 0.2"
    assert cov[0, 0] == 8 and cov[0, 3] == 3


def test_sigma_clip_ignores_frames_that_did_not_cover_a_pixel():
    """The subtle half. sigma-clip already divided by a per-pixel count, so it
    LOOKED immune — but the zeros were in its pass-1 mean and sigma, inflating
    the threshold until they survived their own rejection."""
    frames = _half_covered()
    out, cov = sigma_clip_integrate(lambda: iter(frames), kappa=2.5)
    assert np.allclose(out, 0.2, atol=1e-6), \
        f"partially-covered column diluted to {out[0, 3]:.4f} instead of 0.2"
    assert cov[0, 3] == 3


def test_a_pixel_no_frame_covered_is_zero_not_a_divide_by_zero():
    frames = [(np.zeros((1, 2), np.float32), np.array([[True, False]]))
              for _ in range(3)]
    out, cov = average_integrate(frames)
    assert np.isfinite(out).all() and cov[0, 1] == 0


def test_masks_are_optional_so_full_coverage_is_unchanged():
    """Acceptance #3: the common case (every frame covers everything) must be
    bit-identical to the old behaviour, mask or no mask."""
    plain = [np.full((2, 2), v, np.float32) for v in (0.1, 0.2, 0.3)]
    masked = [(f, np.ones((2, 2), bool)) for f in plain]
    a, _ = average_integrate(plain)
    b, _ = average_integrate(masked)
    assert np.array_equal(a, b)
    c, _ = sigma_clip_integrate(lambda: iter(plain), kappa=2.5)
    d, _ = sigma_clip_integrate(lambda: iter(masked), kappa=2.5)
    assert np.array_equal(c, d)


def test_partial_coverage_does_not_disable_outlier_rejection():
    """Both jobs at once: the uncovered frames must be ignored AND a genuine
    satellite among the covering frames must still be clipped."""
    frames = []
    for i in range(10):
        arr = np.full((1, 2), 0.5, np.float32)
        valid = np.ones((1, 2), bool)
        if i == 0:
            arr[0, 0] = 5.0             # satellite, in a fully-covered column
        if i >= 4:
            arr[0, 1] = 0.0             # not covered
            valid[0, 1] = False
        frames.append((arr, valid))
    out, cov = sigma_clip_integrate(lambda: iter(frames), kappa=2.5)
    assert np.allclose(out[0, 0], 0.5, atol=1e-6), "satellite survived"
    assert np.allclose(out[0, 1], 0.5, atol=1e-6), "partial column diluted"
    assert cov[0, 0] == 10 and cov[0, 1] == 4


def test_thin_coverage_does_not_clip_away_the_only_real_samples():
    """Why pass 1 must be WEIGHTED, not merely pass 2 filtered.

    If the uncovered zeros are left in the pass-1 statistics, a thinly-covered
    pixel gets a mean near zero and a sigma inflated by the 0-vs-signal split.
    The genuine samples then sit OUTSIDE kappa*sigma of that bogus mean and are
    all rejected, leaving nothing to average — a black pixel where the data was
    merely sparse. Measured at 10-of-80 coverage: mean 0.019 against a true
    0.151, sigma 0.050, and 0 of 10 real samples survive.

    10/80 is not hypothetical — it is the right-hand column of the real M31
    stack that started this work.
    """
    n_tot, n_cov, true = 80, 10, 0.15
    rng = np.random.default_rng(1)
    reals = rng.normal(true, true * 0.03, n_cov)
    frames = []
    for i in range(n_tot):
        arr = np.zeros((1, 1), np.float32)
        valid = np.zeros((1, 1), bool)
        if i < n_cov:
            arr[0, 0] = reals[i]
            valid[0, 0] = True
        frames.append((arr, valid))
    out, cov = sigma_clip_integrate(lambda: iter(frames), kappa=2.5)
    assert cov[0, 0] == n_cov
    assert out[0, 0] == pytest.approx(reals.mean(), rel=0.02), \
        f"thinly-covered pixel came out {out[0, 0]:.4f}, expected ~{reals.mean():.4f}"
    assert out[0, 0] > 0.1, "the real samples were clipped away — pixel went black"
