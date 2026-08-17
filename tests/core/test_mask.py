import numpy as np
import pytest

from nocturne.core.mask import range_mask, smoothstep


def _ramp(h=64, w=64):
    """A horizontal luminance ramp 0..1 — every band has a known location."""
    return np.tile(np.linspace(0.0, 1.0, w, dtype=np.float32), (h, 1))


def test_whole_image_is_exactly_one_everywhere():
    """lo=0, hi=1 must be a TRUE no-op so the mask can be switched off without a
    special case in every caller. Anything less than exactly 1.0 would apply the
    tool at partial strength with no control explaining why."""
    m = range_mask(_ramp(), 0.0, 1.0, feather=0.2)
    assert np.all(m == 1.0), f"min {m.min()}"


def test_inside_the_band_is_fully_included():
    m = range_mask(_ramp(), 0.3, 0.7, feather=0.05, smooth_frac=0.0)
    lum = _ramp()
    inside = (lum >= 0.32) & (lum <= 0.68)
    assert np.all(m[inside] > 0.99), f"min inside {m[inside].min()}"


def test_outside_the_band_plus_feather_is_fully_excluded():
    m = range_mask(_ramp(), 0.3, 0.7, feather=0.05, smooth_frac=0.0)
    lum = _ramp()
    outside = (lum < 0.24) | (lum > 0.76)
    assert np.all(m[outside] < 0.01), f"max outside {m[outside].max()}"


def test_a_feather_wider_than_the_band_still_reaches_one():
    """Holds by construction because the ramps sit OUTSIDE the band. Kept as a
    guard: a rewrite that moves them inside would silently apply the tool at
    partial strength everywhere, which no control would explain."""
    m = range_mask(_ramp(), 0.48, 0.52, feather=0.4, smooth_frac=0.0)
    assert m.max() > 0.999, f"never reached 1: max {m.max()}"


def test_the_band_edges_are_soft_not_stepped():
    """A hard edge would show as a visible seam in the finished picture.

    Measured against the hard-edged case rather than a threshold plucked from
    the air: a smoothstep's steepest slope is 1.5/feather, so over a 64-px ramp
    a 0.1 feather necessarily steps 0.24 per pixel and an absolute bound says
    nothing. Sampling finely and contrasting with feather=0 does — the hard case
    must fail the same bound the soft case passes, which is what proves the
    assertion can see the difference at all.
    """
    hard = range_mask(_ramp(8, 512), 0.3, 0.7, feather=0.0, smooth_frac=0.0)
    soft = range_mask(_ramp(8, 512), 0.3, 0.7, feather=0.1, smooth_frac=0.0)
    hard_step = float(np.max(np.abs(np.diff(hard[0]))))
    soft_step = float(np.max(np.abs(np.diff(soft[0]))))
    assert hard_step == pytest.approx(1.0), f"feather=0 should be a cliff, got {hard_step}"
    assert soft_step < 0.05, f"the edge steps: {soft_step}"


def test_noise_does_not_speckle_the_mask():
    """The decision "is this pixel in the band" must be made on signal, not
    noise. A speckled mask means colour noise in the result, which is the whole
    reason the luminance is blurred before the band is applied."""
    rng = np.random.default_rng(0)
    lum = np.full((128, 128), 0.5, np.float32) + rng.normal(0, 0.05, (128, 128)).astype(np.float32)
    m = range_mask(np.clip(lum, 0, 1), 0.45, 0.55, feather=0.02, smooth_frac=0.02)
    assert m.std() < 0.15, f"mask is speckled: std {m.std()}"


def _blob(n):
    """A ringed radial blob, generated analytically at whatever size is asked.

    Two things this fixture is carefully NOT. It is not a linear ramp: a linear
    function is unchanged by convolution with a symmetric kernel, so a ramp is
    invariant to sigma and this test passed against a hard-coded sigma. And the
    small version is not a resize of the big one — that measures the resampler,
    which dominated the comparison so thoroughly that the WRONG implementation
    scored better than the right one.
    """
    y, x = np.mgrid[0:n, 0:n].astype(np.float32) / n
    r = np.hypot(y - 0.5, x - 0.5) * 2.0
    return np.clip(0.9 * np.exp(-3.0 * r * r) * (0.75 + 0.25 * np.cos(8.0 * r))
                   + 0.05, 0.0, 1.0).astype(np.float32)


def test_the_mask_is_scale_covariant():
    """The same content at two sizes must give the same mask, or a decimated
    preview stops agreeing with a full-resolution export. Smoothing is a
    FRACTION of the image for exactly this reason: a sigma in pixels blurs a
    half-size image twice as hard relative to its content.

    Threshold from measurement, not taste — mean absolute difference is 0.0045
    with a fractional sigma and 0.0415 with a fixed one, so 0.02 sits between
    them with room either side. Mean, not max: a handful of pixels on a steep
    edge take the max to 1.0 in both cases and discriminate nothing.
    """
    from skimage.transform import resize
    mb = range_mask(_blob(256), 0.3, 0.7, feather=0.05)
    ms = range_mask(_blob(128), 0.3, 0.7, feather=0.05)
    mb_down = resize(mb, (128, 128), preserve_range=True, anti_aliasing=True)
    diff = float(np.mean(np.abs(mb_down - ms)))
    assert diff < 0.02, f"mean difference {diff:.4f}"


def test_returns_float32_in_range():
    m = range_mask(_ramp(), 0.2, 0.8, feather=0.1)
    assert m.dtype == np.float32
    assert m.min() >= 0.0 and m.max() <= 1.0


def test_smoothstep_endpoints():
    x = np.array([0.0, 0.5, 1.0], np.float32)
    out = smoothstep(x, 0.0, 1.0)
    assert out[0] == pytest.approx(0.0)
    assert out[1] == pytest.approx(0.5)
    assert out[2] == pytest.approx(1.0)
