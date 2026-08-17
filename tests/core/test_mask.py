import numpy as np
import pytest

from nocturne.core.mask import BAND_PRESETS, band_preset, range_mask, smoothstep


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


# --- band presets, derived from the image rather than fixed (2026-08-17) -----

def _sky_and_object(n=200, sky=0.256, sigma=0.041, seed=0):
    """Mostly sky at a realistic level, with a small bright object — the shape
    of a wide-field frame, where percentiles are dominated by sky."""
    rng = np.random.default_rng(seed)
    lum = np.clip(rng.normal(sky, sigma, (n, n)), 0.0, 1.0).astype(np.float32)
    y, x = np.mgrid[0:n, 0:n].astype(np.float32) / n
    r = np.hypot(y - 0.5, x - 0.5) * 4.0
    return np.clip(lum + 0.6 * np.exp(-4.0 * r * r), 0.0, 1.0).astype(np.float32)


def test_whole_image_covers_everything():
    assert band_preset(_sky_and_object(), "Whole image") == (0.0, 1.0)


def test_a_preset_sits_above_the_sky_not_below_it():
    """The failure this exists to prevent: the design specified fixed bounds of
    0.12..0.80, but a stretched M 31 mosaic has its SKY at 0.256 — so that band
    contained the whole sky and selected 87% of the frame, the exact inverse of
    "the object". Bounds have to be measured against the image's own sky."""
    lum = _sky_and_object()
    sky = float(np.median(lum[lum > 0]))
    for name in ("Bright areas", "Midtones", "Object, not the core"):
        lo, _hi = band_preset(lum, name)
        assert lo > sky, f"{name} starts at {lo:.3f}, at or below the sky ({sky:.3f})"


def test_object_not_the_core_excludes_the_bright_end():
    lum = _sky_and_object()
    lo, hi = band_preset(lum, "Object, not the core")
    assert 0.0 < lo < hi < 1.0, f"({lo}, {hi}) is not a band inside the range"
    assert (lum > hi).any(), "nothing was actually excluded at the top"


def test_a_preset_never_returns_an_empty_band():
    """An empty band makes the tool silently inert. A very bright image can push
    both bounds past 1.0, which is where this used to happen."""
    for lum in (np.full((32, 32), 0.99, np.float32),
                np.full((32, 32), 0.01, np.float32),
                np.zeros((32, 32), np.float32)):
        for name in BAND_PRESETS:
            lo, hi = band_preset(lum, name)
            assert hi > lo, f"{name} on {lum.mean():.2f}: empty band ({lo}, {hi})"
            assert 0.0 <= lo <= 1.0 and 0.0 <= hi <= 1.0


def test_presets_ignore_the_zero_padding_around_a_mosaic():
    """A mosaic is zero-padded outside its footprint. Counting that padding as
    sky drags the median down and every bound with it."""
    lum = _sky_and_object()
    padded = np.zeros((400, 400), np.float32)
    padded[100:300, 100:300] = lum
    for name in ("Bright areas", "Object, not the core"):
        a = band_preset(lum, name)
        b = band_preset(padded, name)
        assert abs(a[0] - b[0]) < 0.02, f"{name}: padding moved the low bound {a} -> {b}"


def test_an_unknown_preset_is_rejected():
    with pytest.raises(ValueError):
        band_preset(_sky_and_object(), "Sideways")
