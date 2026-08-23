import numpy as np
import pytest

from probe_independence import common_mode_fraction


def _noise(rng, shape=(256, 256, 3), sigma=0.01):
    return rng.normal(0.0, sigma, shape).astype(np.float32)


def test_independent_noise_reads_as_independent():
    """Two stacks whose noise shares nothing must read near zero. This is the
    premise the whole Noise2Noise spec rests on: if it does not hold on real
    frames, the approach is wrong for this data."""
    rng = np.random.default_rng(0)
    scene = np.zeros((256, 256, 3), np.float32) + 0.05
    a = scene + _noise(rng)
    b = scene + _noise(rng)
    assert abs(common_mode_fraction(a, b)) < 0.10


def test_a_shared_fixed_pattern_is_detected():
    """A defect identical in both halves -- the exact thing Noise2Noise would
    learn as signal -- must push rho up. This proves the probe has teeth;
    without it, `rho < 0.10` could be reporting on a metric that cannot see
    the failure it exists to catch.

    The pattern is ZERO-MEAN (hot and cold pixels), which is what dark-current
    and read-noise non-uniformity actually look like, and it is deliberately
    not a uniformly-bright one: a bright defect on a perfectly flat synthetic
    field raises its own neighbourhood past the 60th percentile and deletes
    itself from the dark mask, so a bright fixture would be measuring that
    flat-field artefact rather than the probe's real sensitivity. See the
    KNOWN BLIND SPOT note in common_mode_fraction.
    """
    rng = np.random.default_rng(1)
    scene = np.zeros((256, 256, 3), np.float32) + 0.05
    fixed = np.zeros((256, 256, 3), np.float32)
    fixed[:, ::8, :] = 0.03            # a fixed-pattern stripe, same in both
    fixed[:, 4::8, :] = -0.03          # ...balanced, so it cannot self-mask
    a = scene + fixed + _noise(rng)
    b = scene + fixed + _noise(rng)
    assert common_mode_fraction(a, b) > 0.25


def test_a_shared_star_field_is_not_common_mode():
    """THE REGRESSION THAT MATTERS. Stars are 3-4 px across, so the high-pass
    does not remove them, and both halves contain the SAME stars -- they are
    sky, not noise. A metric that counts them reports a target's star density
    instead of its sensor behaviour.

    This is not hypothetical. Estimating the dark mask at 25 px instead of
    hp_sigma made this fixture read +0.78, and made the real probe return
    rho=0.78 on M8 and M45 and a STOP verdict that was pure starlight -- while
    the same real stacks with sharp structure excluded read +0.03. The smooth
    sinusoid fixture below cannot catch that, because a 2 px high-pass deletes
    it long before the mask is consulted.
    """
    rng = np.random.default_rng(4)
    yy, xx = np.mgrid[0:256, 0:256]
    stars = np.zeros((256, 256), np.float32)
    for _ in range(120):
        cy, cx = rng.integers(10, 246, 2)
        amp = rng.uniform(0.05, 0.6)
        stars += amp * np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * 1.5 ** 2))
    scene = np.repeat(stars[:, :, None], 3, axis=2) + 0.05
    a = scene + _noise(rng)
    b = scene + _noise(rng)
    assert abs(common_mode_fraction(a, b)) < 0.10


def test_the_scene_itself_does_not_count_as_common_mode():
    """Both halves contain the SAME sky. If the metric measured raw
    correlation it would read ~1.0 on any real pair and be useless -- the
    high-pass is what makes it measure noise rather than signal."""
    rng = np.random.default_rng(2)
    yy, xx = np.mgrid[0:256, 0:256]
    scene = (0.05 + 0.02 * np.sin(xx / 40.0) * np.cos(yy / 40.0)).astype(np.float32)
    scene = np.repeat(scene[:, :, None], 3, axis=2)
    a = scene + _noise(rng)
    b = scene + _noise(rng)
    assert abs(common_mode_fraction(a, b)) < 0.10


def test_perfectly_identical_inputs_read_as_fully_common_mode():
    """Sanity anchor at the other end of the range."""
    rng = np.random.default_rng(3)
    a = np.zeros((256, 256, 3), np.float32) + 0.05 + _noise(rng)
    assert common_mode_fraction(a, a) > 0.95
