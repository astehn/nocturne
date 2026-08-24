"""Does the realism gate have teeth?

The gate exists to answer one question -- is manufactured noise the same animal
as the camera's real noise -- and a gate that cannot tell white Gaussian noise
from spatially correlated stacked noise answers nothing. That is not a
hypothetical failure mode here: on 2026-08-23 an independence probe on this
project measured starlight, reported it as sensor noise, and nearly killed the
project on a false negative. Every test below is aimed at the comparison's
ability to CATCH a difference, not at its ability to agree with itself.
"""
import numpy as np
import pytest

from realism import compare_noise


def _mask(shape):
    return np.ones(shape[:2], bool)


def _correlate(field, sigma=1.0):
    """Spatially correlate a field, then restore its original sigma.

    Real stacked noise is correlated because registration resamples every frame
    and demosaicing mixes neighbours; a Gaussian generator produces the same
    sigma with none of that structure. Rescaling is what makes the pair differ
    ONLY in structure, so a statistic that passes them as alike is blind to the
    one thing this gate is for.
    """
    from scipy.ndimage import gaussian_filter

    out = np.stack(
        [gaussian_filter(field[:, :, c], sigma) for c in range(field.shape[2])], -1
    )
    return (out * (field.std() / out.std())).astype(np.float32)


def test_identical_noise_compares_as_identical():
    rng = np.random.default_rng(0)
    n = rng.normal(0, 0.01, (256, 256, 3)).astype(np.float32)
    r = compare_noise(n, n.copy(), _mask(n.shape))
    for key, (_, _, rel) in r.items():
        assert abs(rel) < 0.02, f"{key} differs on identical input: {rel}"


def test_gaussian_noise_is_caught_as_unlike_correlated_noise():
    """THE POINT OF THIS GATE. Real stacked noise is spatially correlated --
    registration warps every frame with interpolation and demosaicing mixes
    neighbours. White Gaussian noise of the SAME sigma has no such correlation.
    If the comparison cannot tell those apart it proves nothing, which is the
    trap the independence probe fell into on 2026-08-23 when it measured
    starlight and reported it as sensor noise.
    """
    rng = np.random.default_rng(1)
    white = rng.normal(0, 0.01, (256, 256, 3)).astype(np.float32)
    corr = _correlate(white, 1.0)
    assert np.std(corr) == pytest.approx(np.std(white), rel=0.02), (
        "the control must differ in structure only, not in level"
    )
    r = compare_noise(corr, white, _mask(white.shape))
    assert abs(r["autocorr_1"][2]) > 0.20, "white noise passed as correlated noise"


def test_a_per_channel_imbalance_is_caught():
    """Bayer gives green half the samples of red and blue together, hence less
    noise. A generator that made all three equal would be wrong in a way that
    shows up as colour blotching -- the artefact this project keeps fighting."""
    rng = np.random.default_rng(2)
    real = rng.normal(0, 0.01, (256, 256, 3)).astype(np.float32)
    real[:, :, 1] *= 0.7                       # green quieter, as Bayer gives it
    flat = rng.normal(0, real.std(), (256, 256, 3)).astype(np.float32)
    r = compare_noise(real, flat, _mask(real.shape))
    assert abs(r["channel_ratios"][2]) > 0.10


def test_a_partial_mask_pairs_each_pixel_with_its_own_neighbour():
    """A shifted-correlation over a mask has to select the SAME pixel pairs on
    both sides of the shift. Selecting `mask[:, :-lag]` from one side and
    `mask[:, lag:]` from the other pairs each pixel with ITSELF wherever the
    mask stops short of the border -- so it reports 1.000 for any field at all,
    and the gate would pass white noise as perfectly correlated.

    The mask here is a disc, deliberately symmetric: both selections then hold
    the same NUMBER of pixels, so the broken version returns a wrong number
    instead of raising. A test that a mispaired selection merely crashes numpy
    is not a test of this code -- and every real mask here (coverage, dark
    region) stops short of the border, so this is the normal case, not an edge
    case.
    """
    rng = np.random.default_rng(3)
    field = _correlate(rng.normal(0, 0.01, (256, 256, 3)).astype(np.float32), 1.5)
    full = compare_noise(field, field, _mask(field.shape), per_axis=True)

    y, x = np.mgrid[0:256, 0:256]
    mask = ((y - 127.5) ** 2 + (x - 127.5) ** 2) < 100.0 ** 2
    assert not mask[0].any() and not mask[:, 0].any(), "disc must clear the border"
    masked = compare_noise(field, field, mask, per_axis=True)

    assert full["autocorr_1"][0] > 0.5, "the control field is not actually correlated"
    for key in ("autocorr_1", "autocorr_1_x", "autocorr_1_y", "autocorr_2"):
        assert masked[key][0] == pytest.approx(full[key][0], abs=0.05), (
            f"{key} through a disc mask reads {masked[key][0]:.3f} against the "
            f"full-frame {full[key][0]:.3f} -- the mask is not pairing neighbours"
        )


def test_a_field_that_is_correlated_in_one_axis_only_is_caught():
    """Averaging the two axes into one number must not let an anisotropic
    difference cancel. Vertical-only correlation against horizontal-only
    correlation would read identically if only one axis were measured."""
    from scipy.ndimage import gaussian_filter1d

    rng = np.random.default_rng(4)
    white = rng.normal(0, 0.01, (256, 256, 3)).astype(np.float32)
    horiz = np.stack([gaussian_filter1d(white[:, :, c], 1.5, axis=1)
                      for c in range(3)], -1)
    vert = np.stack([gaussian_filter1d(white[:, :, c], 1.5, axis=0)
                     for c in range(3)], -1)
    r = compare_noise(horiz.astype(np.float32), vert.astype(np.float32),
                      _mask(white.shape))
    assert abs(r["autocorr_1"][2]) < 0.02, (
        "these two have the same correlation, just rotated; the averaged "
        "statistic should read them as alike"
    )
    per_axis = compare_noise(horiz.astype(np.float32), vert.astype(np.float32),
                             _mask(white.shape), per_axis=True)
    assert abs(per_axis["autocorr_1_x"][2]) > 0.5
    assert abs(per_axis["autocorr_1_y"][2]) > 0.5


def test_variance_that_does_not_grow_with_signal_is_caught():
    """Shot noise grows with intensity. A field of constant variance laid over
    a nebula is the tell of a synthetic generator, and it is invisible to every
    other statistic here."""
    rng = np.random.default_rng(5)
    h = w = 256
    intensity = np.linspace(0.02, 1.0, w, dtype=np.float32)[None, :].repeat(h, 0)
    shot = (rng.normal(0, 1, (h, w, 3)) * np.sqrt(intensity)[:, :, None]
            * 0.01).astype(np.float32)
    flat = (rng.normal(0, 1, (h, w, 3)) * 0.01 * np.sqrt(intensity.mean())
            ).astype(np.float32)
    r = compare_noise(shot, flat, _mask(shot.shape), intensity=intensity)
    assert r["variance_slope"][0] > 0.5, "shot noise should show a positive slope"
    assert abs(r["variance_slope"][1]) < 0.2, "flat noise should show no slope"
    assert abs(r["variance_slope"][2]) > 0.5
