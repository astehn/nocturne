import numpy as np
import pytest

from nocturne.core.inspect import Sample, sample


def test_sample_colour_returns_channels_and_mean_luminance():
    data = np.zeros((4, 5, 3), np.float32)
    data[2, 3] = (0.8, 0.6, 0.4)
    s = sample(data, x=3, y=2)
    assert s.channels == pytest.approx((0.8, 0.6, 0.4))
    assert s.luminance == pytest.approx(0.6)      # equal-weight mean, not Rec.709


def test_sample_mono_has_single_channel_and_no_luminance():
    data = np.full((4, 5), 0.25, np.float32)
    s = sample(data, x=1, y=1)
    assert s.channels == pytest.approx((0.25,))
    assert s.luminance is None


def test_sample_luminance_matches_the_convention_used_by_curves():
    # curves.py:74 uses data.mean(axis=2); the readout must agree or it will
    # contradict the tool it exists to inform.
    rng = np.random.default_rng(0)
    data = rng.random((6, 7, 3), dtype=np.float32)
    expected = data.mean(axis=2)
    for y, x in ((0, 0), (3, 4), (5, 6)):
        assert sample(data, x, y).luminance == pytest.approx(expected[y, x], abs=1e-6)


@pytest.mark.parametrize("x,y", [(-1, 0), (0, -1), (5, 0), (0, 4), (99, 99)])
def test_sample_outside_the_image_returns_none(x, y):
    assert sample(np.zeros((4, 5, 3), np.float32), x, y) is None


def test_sample_accepts_the_last_valid_pixel():
    data = np.zeros((4, 5, 3), np.float32)
    data[3, 4] = (1.0, 1.0, 1.0)
    assert sample(data, x=4, y=3).channels == pytest.approx((1.0, 1.0, 1.0))


def test_sample_is_a_named_tuple():
    s = sample(np.zeros((2, 2), np.float32), 0, 0)
    assert isinstance(s, Sample)


from nocturne.core.inspect import Clipping, clip_masks, clipping_from_histogram


def _hist(r_top=0, r_bot=0, g_top=0, g_bot=0, b_top=0, b_bot=0, total=1000):
    """A 256-bin histogram per channel with the given top/bottom bin counts and
    everything else parked in the middle."""
    out = {}
    for key, top, bot in (("r", r_top, r_bot), ("g", g_top, g_bot), ("b", b_top, b_bot)):
        counts = np.zeros(256, np.int64)
        counts[0] = bot
        counts[255] = top
        counts[128] = total - top - bot
        out[key] = counts
    return out


def test_clipping_reports_the_worst_channel_for_highlights():
    c = clipping_from_histogram(_hist(r_top=5, g_top=30, b_top=1, total=1000))
    assert c.hi_frac == pytest.approx(0.03)
    assert c.hi_channel == "G"


def test_clipping_reports_the_worst_channel_for_shadows_independently():
    # The red-crushed-background failure from the pipeline audit: shadows worst
    # in R while highlights are worst in B. They must not be merged.
    c = clipping_from_histogram(_hist(r_bot=120, b_top=40, total=1000))
    assert c.lo_frac == pytest.approx(0.12)
    assert c.lo_channel == "R"
    assert c.hi_frac == pytest.approx(0.04)
    assert c.hi_channel == "B"


def test_clipping_mono_uses_the_l_channel():
    counts = np.zeros(256, np.int64)
    counts[255] = 10
    counts[128] = 90
    c = clipping_from_histogram({"l": counts})
    assert c.hi_frac == pytest.approx(0.1) and c.hi_channel == "L"


def test_clipping_with_nothing_at_the_extremes_is_zero():
    c = clipping_from_histogram(_hist(total=1000))
    assert c.hi_frac == 0.0 and c.lo_frac == 0.0


def test_clipping_of_an_empty_histogram_is_all_zero():
    assert clipping_from_histogram({}) == Clipping(0.0, "", 0.0, "")
    assert clipping_from_histogram(None) == Clipping(0.0, "", 0.0, "")


def test_clipping_of_an_all_zero_histogram_does_not_divide_by_zero():
    c = clipping_from_histogram({"l": np.zeros(256, np.int64)})
    assert c.hi_frac == 0.0 and c.lo_frac == 0.0


def test_clip_masks_flag_only_the_extreme_uint8_values():
    rgb = np.full((1, 4, 3), 128, np.uint8)
    rgb[0, 0] = (255, 10, 10)     # highlight, red only
    rgb[0, 1] = (0, 200, 200)     # shadow, red only
    rgb[0, 2] = (254, 1, 1)       # one step inside both — not clipped
    sh, hi = clip_masks(rgb)
    assert hi[..., 0].tolist() == [[True, False, False, False]]
    assert sh[..., 0].tolist() == [[False, True, False, False]]
    assert not hi[..., 1].any() and not hi[..., 2].any()
    assert not sh[..., 1].any() and not sh[..., 2].any()


def test_clip_masks_say_WHICH_channel_is_clipped():
    """The point of the per-channel form. A pixel whose red alone is at zero is
    still a perfectly ordinary teal on screen — reporting only "this pixel is
    clipped" made that look like a false alarm."""
    rgb = np.full((1, 3, 3), 128, np.uint8)
    rgb[0, 0] = (0, 46, 54)       # red alone dead — looks teal, red is gone
    rgb[0, 1] = (0, 0, 0)         # genuinely black
    rgb[0, 2] = (10, 10, 0)       # blue alone dead
    sh, _ = clip_masks(rgb)
    assert sh[0, 0].tolist() == [True, False, False]
    assert sh[0, 1].tolist() == [True, True, True]
    assert sh[0, 2].tolist() == [False, False, True]


def test_clip_masks_return_per_channel_boolean_arrays():
    sh, hi = clip_masks(np.zeros((3, 5, 3), np.uint8))
    assert sh.shape == (3, 5, 3) and sh.dtype == bool
    assert hi.shape == (3, 5, 3) and hi.dtype == bool


def test_clipping_selects_worst_by_fraction_not_count():
    """The channel with the worst (highest) clipped FRACTION is reported, even
    if another channel has a higher raw clipped COUNT. This is the core fix for
    per-channel sums: 40/100 (40% clipped) is worse than 41/1,000,000 (0.0041%
    clipped) despite 41 > 40 in absolute count."""
    hist = {
        "r": np.zeros(256, np.int64),
        "g": np.zeros(256, np.int64),
    }
    hist["r"][255] = 40
    hist["r"][128] = 60
    # R: 40 clipped out of 100 → 40% → 0.4 fraction

    hist["g"][255] = 41
    hist["g"][128] = 999959
    # G: 41 clipped out of 1,000,000 → 0.0041% → 0.000041 fraction

    c = clipping_from_histogram(hist)
    # R's fraction (0.4) is vastly worse than G's (0.000041)
    # Must select R despite G having higher count (41 > 40)
    assert c.hi_channel == "R"
    assert c.hi_frac == pytest.approx(0.4)


def test_clipping_not_suppressed_when_one_channel_sum_is_zero():
    """When one channel's histogram sums to 0 (all values were NaN),
    real clipping in other channels must not be suppressed."""
    hist = {}
    # R: all pixels were NaN, dropped by np.histogram
    hist["r"] = np.zeros(256, np.int64)  # sum = 0

    # G and B: normal histograms with real clipping
    counts_g = np.zeros(256, np.int64)
    counts_g[255] = 100
    counts_g[128] = 900
    hist["g"] = counts_g  # sum = 1000, hi_frac = 0.1

    counts_b = np.zeros(256, np.int64)
    counts_b[255] = 50
    counts_b[128] = 950
    hist["b"] = counts_b  # sum = 1000, hi_frac = 0.05

    c = clipping_from_histogram(hist)
    # R has count 0, G has count 100 (worst), B has count 50
    # G should be selected even though R's sum is 0
    assert c.hi_channel == "G"
    assert c.hi_frac == pytest.approx(0.1)


def test_clipping_shadow_only_not_suppressed_by_zero_highlights():
    """Regression: shadows and highlights are independent. A histogram with NO
    highlight clipping but real shadow clipping must report the shadows, not
    suppress them. This is the most common real case (user dragged black point
    too far)."""
    c = clipping_from_histogram(_hist(r_bot=120, total=1000))
    # R: 120 shadows out of 1000 → lo_frac = 0.12
    # No highlights anywhere
    assert c.lo_frac == pytest.approx(0.12)
    assert c.lo_channel == "R"
    assert c.hi_frac == 0.0
    assert c.hi_channel == ""


def test_clipping_highlight_only_not_suppressed_by_zero_shadows():
    """Symmetric case: highlights present, shadows absent. Both must be reported
    independently."""
    c = clipping_from_histogram(_hist(b_top=80, total=1000))
    # B: 80 highlights out of 1000 → hi_frac = 0.08
    # No shadows anywhere
    assert c.hi_frac == pytest.approx(0.08)
    assert c.hi_channel == "B"
    assert c.lo_frac == 0.0
    assert c.lo_channel == ""


def test_clipping_with_neither_highlight_nor_shadow():
    """When there is no clipping at all (all pixels in mid-range), fractions are
    zero but are still reported with channel names."""
    c = clipping_from_histogram(_hist(total=1000))
    # No clipping anywhere
    assert c.hi_frac == 0.0
    assert c.lo_frac == 0.0
    # Channel names may vary based on dict iteration, but fractions must be clear


# --- what background extraction removed ---------------------------------------

def _with_gradient(shape=(120, 160), slope=0.06, base=0.05):
    """A flat sky plus a linear ramp — the thing background extraction exists to
    remove."""
    import numpy as np
    y, x = np.mgrid[0:shape[0], 0:shape[1]]
    ramp = (x / shape[1]) * slope
    data = np.full((*shape, 3), base, np.float32) + ramp[..., None].astype(np.float32)
    return data


def test_the_model_shows_the_gradient_that_was_removed():
    """The point of showing it: a user can see WHAT was taken out, which is how
    you tell a real gradient from the tool eating your object."""
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.inspect import background_model

    before = _with_gradient()
    after = np.full_like(before, 0.05)                 # the ramp removed
    m = background_model(AstroImage(before), AstroImage(after))

    assert m.removed_anything
    row = m.image.data[60, :, 0]
    assert row[-1] > row[0] + 0.5, "the ramp must be visible across the frame"
    assert 0.0 <= m.image.data.min() and m.image.data.max() <= 1.0


def test_nothing_removed_is_reported_not_amplified():
    """If the step did nothing, the difference is float noise. Normalising that
    would paint a vivid pattern out of rounding error and look like a bug in the
    data — so say 'nothing' instead."""
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.inspect import background_model

    same = _with_gradient()
    m = background_model(AstroImage(same), AstroImage(same.copy()))
    assert not m.removed_anything
    assert float(np.ptp(m.image.data)) == 0.0


def test_the_model_reports_how_strong_the_gradient_was():
    """In the image's own units, so it can be stated rather than guessed at."""
    from nocturne.core.image import AstroImage
    from nocturne.core.inspect import background_model
    import numpy as np

    before = _with_gradient(slope=0.06)
    after = np.full_like(before, 0.05)
    m = background_model(AstroImage(before), AstroImage(after))
    assert abs(m.span - 0.06) < 0.005, m.span


def test_a_mono_image_is_handled():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.inspect import background_model

    y, x = np.mgrid[0:80, 0:80]
    before = (0.04 + x / 80 * 0.03).astype(np.float32)
    after = np.full_like(before, 0.04)
    m = background_model(AstroImage(before), AstroImage(after))
    assert m.removed_anything
    assert m.image.data.ndim == 2


def _ramp(nx=40, ny=30):
    import numpy as np
    x = np.linspace(0.0, 1.0, nx, dtype=np.float32)
    return np.tile(x, (ny, 1))


def test_a_per_channel_pedestal_does_not_tint_the_model():
    """Measured on NGC7000_163x20s_54min (2026-08-16): background extraction
    removed a DIFFERENT CONSTANT from each channel — the diff's per-channel
    medians were R -0.000428, G +0.000179, B +0.000222 against a total span of
    0.00106. Normalising all three channels through one lo/hi turned that offset
    into more than half the output range and painted the model vivid cyan, while
    the actual ramp was strongest in RED (spans 0.000419 / 0.000274 / 0.000376).
    A pedestal is a level, not a gradient; it must not become colour."""
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.inspect import background_model

    ramp = _ramp() * 0.001
    before = np.stack([ramp + 0.02] * 3, axis=-1)
    # identical ramp in every channel, but a different constant per channel
    after = before - np.stack([ramp - 0.0004, ramp + 0.0002, ramp + 0.0002], axis=-1)

    m = background_model(AstroImage(before, is_linear=True),
                         AstroImage(after, is_linear=True))
    d = m.image.data
    assert np.allclose(d[..., 0], d[..., 1], atol=1e-3), "red drifted from green"
    assert np.allclose(d[..., 1], d[..., 2], atol=1e-3), "blue drifted from green"


def test_a_channel_with_a_stronger_ramp_still_shows_as_colour():
    """The pedestal must go, but a genuinely stronger gradient in one channel is
    real and worth seeing — sky-glow is not grey. Removing the offset must not
    flatten this too."""
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.inspect import background_model

    ramp = _ramp() * 0.001
    before = np.stack([ramp + 0.02] * 3, axis=-1)
    after = before - np.stack([ramp * 2.0, ramp, ramp], axis=-1)   # red twice as steep

    d = background_model(AstroImage(before, is_linear=True),
                         AstroImage(after, is_linear=True)).image.data
    red_swing = d[..., 0].max() - d[..., 0].min()
    green_swing = d[..., 1].max() - d[..., 1].min()
    assert red_swing > green_swing * 1.8, "the stronger red ramp was flattened away"


def test_a_real_gradient_is_not_dismissed_as_nothing():
    """NGC 7000, 54 min: the removed gradient spanned 0.00106 and the step changed
    the image 5.2%. The old floor was 1e-3 — six percent below that measurement,
    so a slightly flatter sky would have answered "removed nothing measurable"
    for a plainly visible correction."""
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.inspect import background_model

    ramp = _ramp() * 0.0005          # half the NGC 7000 gradient, still real
    before = np.stack([ramp + 0.019] * 3, axis=-1)
    after = before - np.stack([ramp] * 3, axis=-1)

    m = background_model(AstroImage(before, is_linear=True),
                         AstroImage(after, is_linear=True))
    assert m.removed_anything, f"span {m.span} dismissed as nothing"
