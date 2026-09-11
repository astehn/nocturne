import numpy as np
import pytest

from nocturne.core.inspect import (CLIP_HIGHLIGHT, CLIP_MARK_OFF, CLIP_MARK_ON,
                                   Sample, clip_overlay, paint_clipping, sample)


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


from nocturne.core.inspect import (Clipping, ClipBaseline, capture_clip_baseline,
                                   clip_masks, clipping_from_histogram)


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


# --- baseline: report what the CURRENT settings ADD, not the crushed total --
#
# Mid-grey background throughout, never zeros: a black background is itself
# shadow-clipped, so a "not lit" assertion on it would pass whether or not the
# baseline subtraction did anything. This exact mistake has shipped twice on
# this branch already.

def test_baseline_pixel_already_clipped_is_not_relit():
    """The whole point: something the pipeline crushed before the dialog
    opened (e.g. auto_levels's black point) must not sit lit from the first
    frame with no slider move that could ever clear it."""
    rgb = np.full((4, 4, 3), 128, np.uint8)
    rgb[0, 0] = 0                       # crushed already, at baseline settings
    baseline = capture_clip_baseline(rgb)
    sh, _ = clip_masks(rgb, baseline=baseline)
    assert not sh[0, 0].any(), "a pixel clipped at baseline must not relight"


def test_baseline_newly_clipped_pixel_is_lit():
    """What the current settings add IS the signal the overlay exists to show."""
    base_rgb = np.full((4, 4, 3), 128, np.uint8)
    baseline = capture_clip_baseline(base_rgb)      # nothing clipped at baseline
    current = base_rgb.copy()
    current[1, 1] = 0                                # newly crushed by this session
    sh, _ = clip_masks(current, baseline=baseline)
    assert sh[1, 1].all(), "a pixel newly clipped now must be lit"


def test_baseline_pixel_that_recovers_is_not_lit():
    """A pixel clipped at baseline that the CURRENT settings pull back out of
    zero (e.g. black point dragged past it) must not be lit, and the AND-NOT
    against a now-false mask must not misbehave."""
    base_rgb = np.full((4, 4, 3), 128, np.uint8)
    base_rgb[2, 2] = 0
    baseline = capture_clip_baseline(base_rgb)
    current = base_rgb.copy()
    current[2, 2] = 128                              # recovered under current settings
    sh, _ = clip_masks(current, baseline=baseline)
    assert not sh[2, 2].any()


def test_baseline_fraction_reports_the_total():
    """The figure a caller needs to say, in words, how much was already gone —
    per-pixel (any channel dead), matching what the overlay actually lights."""
    rgb = np.full((4, 4, 3), 128, np.uint8)
    rgb[0, 0] = 0
    rgb[0, 1] = 0
    baseline = capture_clip_baseline(rgb)
    assert baseline.shadow_frac == pytest.approx(2 / 16)
    assert baseline.highlight_frac == 0.0


def test_clip_masks_with_no_baseline_is_unchanged():
    """Existing callers (paint_clipping on every live-preview tick chief among
    them) must see byte-for-byte identical behaviour."""
    rgb = np.full((4, 4, 3), 128, np.uint8)
    rgb[0, 0] = 0
    rgb[1, 1] = 255
    sh_a, hi_a = clip_masks(rgb)
    sh_b, hi_b = clip_masks(rgb, baseline=None)
    assert np.array_equal(sh_a, sh_b) and np.array_equal(hi_a, hi_b)


def test_clip_masks_baseline_shape_mismatch_raises():
    """A silently misaligned baseline (e.g. captured against a different zoom
    crop) would AND-NOT the wrong pixels against each other rather than fail —
    a fault a caller could ship without ever seeing it break."""
    baseline = capture_clip_baseline(np.full((4, 4, 3), 128, np.uint8))
    with pytest.raises(ValueError):
        clip_masks(np.full((8, 8, 3), 128, np.uint8), baseline=baseline)


def test_clip_overlay_with_baseline_only_lights_whats_new():
    """End-to-end through the actual painted overlay, not just the masks."""
    base_rgb = np.full((8, 8, 3), 128, np.uint8)
    base_rgb[0, 0] = 0                  # crushed already, e.g. by auto_levels
    baseline = capture_clip_baseline(base_rgb)
    current = base_rgb.copy()
    current[7, 7] = 0                   # newly crushed by the current settings
    out = clip_overlay(current, (8, 8), baseline=baseline)
    assert not out[0, 0].any(), "pre-existing shadow clipping must not relight"
    assert out[7, 7].tolist() == [255, 255, 255], "newly clipped pixel must be lit"


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


def test_a_single_clipped_pixel_survives_reduction_to_a_smaller_preview():
    """The defect this function exists to prevent: averaging down a 64x64 frame
    with one blown pixel to 8x8 dilutes it to 255/64 = 4, invisible. The user
    drags looking for the first speck and never sees it.

    The background is mid-grey, NOT zeros: at 0 every background pixel is itself
    shadow-clipped, the whole overlay lights up, and the assertion passes whether
    the reduction is a max or a mean — i.e. it cannot fail for the right reason.
    """
    rgb = np.full((64, 64, 3), 128, np.uint8)
    rgb[10, 10] = 255
    out = clip_overlay(rgb, (8, 8))
    assert out.shape == (8, 8, 3)
    # Exact value, not .any(): under a mean reduction one blown pixel in a
    # 64-px block yields 255/64 = 3, which is truthy. Only == 255 separates a
    # max reduction from a mean one.
    assert out[1, 1, 0] == 255, "the clipped pixel was averaged away, not maxed"
    assert not out[0, 0].any(), "a clean block must stay black"


def test_padding_preserves_a_pixel_in_the_trailing_partial_block():
    """65x65 is not a multiple of the 8x8 target — Task 3's real call site
    (a decimated 3840x2160 frame) is essentially never an exact multiple. The
    trailing block is real data plus padding, not a clean multiple; a naive
    crop instead of a pad would silently drop a pixel that falls in that
    overhang."""
    rgb = np.full((65, 65, 3), 128, np.uint8)
    rgb[64, 64] = 255           # last real row/col, inside the padded trailing block
    out = clip_overlay(rgb, (8, 8))
    assert out.shape == (8, 8, 3)
    assert out[7, 7, 0] == 255, "the trailing block was dropped or diluted by padding"


def test_clean_frame_produces_a_black_overlay():
    rgb = np.full((16, 16, 3), 128, np.uint8)
    out = clip_overlay(rgb, (4, 4))
    assert not out.any()


def test_overlay_is_coloured_by_the_channel_that_died():
    """Which channel died is the whole story — a background where only red is
    at zero still looks a healthy teal, so a flat OR-ed mask hides the fault.

    Red CRUSHED, not blown: crushed is the per-channel half of the legend.
    Blown is a single amber whatever the channel — see the test below."""
    rgb = np.full((8, 8, 3), 128, np.uint8)
    rgb[..., 0] = 0            # red at zero everywhere, green and blue mid
    out = clip_overlay(rgb, (8, 8))
    assert tuple(out[0, 0]) == (CLIP_MARK_ON, CLIP_MARK_OFF, CLIP_MARK_OFF)


def test_shadow_and_highlight_clipping_are_distinguishable():
    """Exact values, not just !=: a wrong tint could still satisfy an
    inequality. Highlight paints full intensity, shadow paints half, in the
    channel that actually clipped."""
    rgb = np.full((8, 8, 3), 128, np.uint8)
    rgb[0, 0] = 0              # all three channels at zero
    rgb[7, 7] = 255            # all three channels blown
    out = clip_overlay(rgb, (8, 8))
    assert tuple(out[0, 0]) == (255, 255, 255)     # white: the pixel really is black
    assert tuple(out[7, 7]) == CLIP_HIGHLIGHT      # amber: blown


def test_a_blown_channel_wins_over_a_crushed_one_in_the_same_pixel():
    """Highlights are painted LAST, deliberately: "a blown core is the more
    urgent of the two". So a pixel that is crushed in red and blown in green
    reads as blown, not as a third colour.

    This is the app's own legend, not this function's opinion — the main
    window's Show Clipping has always painted it this way, and the reason
    there is ONE painting now is that the two used to disagree."""
    rgb = np.full((8, 8, 3), 128, np.uint8)
    rgb[2, 2] = (0, 255, 128)  # red crushed, green blown, blue clean
    out = clip_overlay(rgb, (8, 8))
    assert tuple(out[2, 2]) == CLIP_HIGHLIGHT


def test_non_square_shapes_are_not_transposed():
    """h and w are handled independently, so a transposed bh/bw would pass
    every other test here since all other shapes are square — the production
    case is a 16:9 sensor. 64x32 -> 8x4: correct block height is 64/8=8,
    correct block width is 32/4=8, but src height (64) and width (32) differ,
    so a swap of which source dimension pairs with which target dimension
    still misplaces this pixel even though the correct block sizes coincide.
    """
    rgb = np.full((64, 32, 3), 128, np.uint8)
    rgb[40, 10] = 255           # row-block 40//8=5, col-block 10//8=1
    out = clip_overlay(rgb, (8, 4))
    assert out.shape == (8, 4, 3)
    assert tuple(out[5, 1]) == CLIP_HIGHLIGHT, "pixel landed in the wrong block — axes may be transposed"
    assert np.count_nonzero(out) == 2, \
        "exactly one blown block should survive (amber is 255,160,0 — two non-zero channels)"


def test_identity_shape_is_not_reduced():
    rgb = np.full((8, 8, 3), 128, np.uint8)   # grey, so only [3, 3] clips
    rgb[3, 3] = 255
    out = clip_overlay(rgb, (8, 8))
    assert out[3, 3].any()
    assert not out[0, 0].any()


# --- one legend, one implementation ---------------------------------------

def test_the_dialog_overlay_and_the_canvas_agree_on_what_white_means():
    """The defect: `clip_overlay` had invented a second legend (blown 255,
    crushed 128), so WHITE meant "all three crushed" on the canvas and "all
    three blown" in the Starless Levels dialog. A user who learned the main
    window's tooltip pulled the white point in, saw white specks, and read them
    as crushed to black — exactly inverted.

    Asserted through the SHARED painter against the canvas's own path, so the
    two cannot drift apart again.
    """
    rgb = np.full((4, 4, 3), 128, np.uint8)
    rgb[0, 0] = 0             # all three crushed
    rgb[1, 1] = 255           # all three blown
    rgb[2, 2] = (0, 128, 128)  # red alone crushed

    canvas = paint_clipping(rgb.copy())          # over the picture, as _set_canvas does
    overlay = clip_overlay(rgb, (4, 4))          # onto black, then reduced 1:1

    assert tuple(canvas[0, 0]) == tuple(overlay[0, 0]) == (255, 255, 255)
    assert tuple(canvas[1, 1]) == tuple(overlay[1, 1]) == CLIP_HIGHLIGHT
    assert tuple(canvas[2, 2]) == tuple(overlay[2, 2]) == \
        (CLIP_MARK_ON, CLIP_MARK_OFF, CLIP_MARK_OFF)
    # ...and the one difference that is meant to exist: the canvas keeps the
    # picture where nothing clipped, the overlay replaces it with black.
    assert tuple(canvas[3, 3]) == (128, 128, 128)
    assert tuple(overlay[3, 3]) == (0, 0, 0)


def test_the_main_window_no_longer_carries_its_own_painting():
    """A shared function is only shared while both callers use it. This is the
    cheap guard against someone re-inlining the canvas painting and quietly
    restoring the two contradictory legends."""
    from pathlib import Path
    src = (Path(__file__).parents[2] / "nocturne" / "ui" / "main_window.py").read_text()
    assert "paint_clipping(rgb)" in src
    assert "_CLIP_MARK_ON" not in src and "_CLIP_HIGHLIGHT" not in src


def test_a_two_dimensional_input_is_refused_rather_than_dying_inside_np_pad():
    """It is a public core/ function, and its neighbour structural_clipping
    guards `rgb.ndim != 3`. Without this a mono array passed the identity
    branch and raised a broadcast ValueError from np.pad naming neither the
    caller nor the cause — and only when a reduction happened to be needed."""
    import pytest
    mono = np.full((16, 16), 128, np.uint8)
    with pytest.raises(ValueError, match="H x W x 3"):
        clip_overlay(mono, (4, 4))
    with pytest.raises(ValueError, match="H x W x 3"):
        clip_overlay(mono, (16, 16))       # the identity branch too
    with pytest.raises(ValueError, match="H x W x 3"):
        paint_clipping(mono)


def test_the_fast_reduce_equals_a_plain_loop(self_check=None):
    """The reduce is hand-optimised — a few full-width elementwise passes — and
    speed is worth nothing if the answer moved, so this pins it against an
    obvious loop doing the same thing.

    The SEMANTICS being pinned: reduce into ceil(src/b) groups of b = ceil(src/n)
    (the last group holding whatever is left over), then nearest-stretch that to
    n. Not "each output pixel covers its exact source range" — `reduceat` gives
    that and measured 298 ms against 12 on an 8.3 MP frame. What matters, and
    what the loop below also guarantees, is that EVERY source pixel lands in some
    group and no output pixel is made of padding.
    """
    rng = np.random.default_rng(4)
    for (H, W), (h, w) in [((64, 64), (8, 8)), ((65, 65), (8, 8)),
                           ((64, 32), (8, 4)), ((70, 33), (9, 5)),
                           ((2160, 240), (338, 60)), ((5746, 4320), (801, 602))]:
        rgb = np.full((H, W, 3), 128, np.uint8)
        rgb[rng.random((H, W)) < 0.02] = 255
        rgb[rng.random((H, W)) < 0.02] = 0
        painted = paint_clipping(rgb, np.zeros_like(rgb))

        bh, bw = -(-H // h), -(-W // w)
        mh, mw = -(-H // bh), -(-W // bw)
        blocks = np.zeros((mh, mw, 3), np.uint8)
        for i in range(mh):
            for j in range(mw):
                tile = painted[i * bh:(i + 1) * bh, j * bw:(j + 1) * bw]
                blocks[i, j] = tile.reshape(-1, 3).max(axis=0)
        want = blocks[np.arange(h) * mh // h][:, np.arange(w) * mw // w]
        assert np.array_equal(clip_overlay(rgb, (h, w)), want), f"{H}x{W} -> {h}x{w}"


# --- Photoshop polarity: `end` flips the ground with the handle being worked -
#
# Andreas: "In photoshop the clipping overlay for black point is white and for
# the highlights its black." `end=None` (never passed by the main window's
# live canvas) must stay byte-for-byte what shipped before; "lo"/"hi" are new,
# opt-in views for the Starless Levels dialog alone.

def test_paint_clipping_default_end_is_unchanged():
    """The critical constraint: `paint_clipping` with no new arguments must be
    pixel-identical to before this change, because the main window's live
    canvas calls it on every preview tick and a previous round already proved
    that bit-unchanged across 30 random frames.

    Expected values are worked out BY HAND from the documented legend, not by
    calling `paint_clipping` itself — comparing the function against its own
    output would pass even if this change had broken it. One frame carries
    both a per-pixel case (all three channels dead) and a per-channel case
    (one channel dead, the others healthy), plus the blown-wins-over-crushed
    collision, because a fix that only handled one of those could still break
    the other.
    """
    rgb = np.full((4, 4, 3), 128, np.uint8)
    rgb[0, 0] = (0, 128, 128)     # red alone crushed
    rgb[1, 1] = (0, 0, 0)         # all three crushed
    rgb[2, 2] = (255, 255, 255)   # all three blown
    rgb[3, 3] = (0, 255, 128)     # red crushed, green blown: blown must win

    out = paint_clipping(rgb.copy())

    assert tuple(out[0, 0]) == (CLIP_MARK_ON, CLIP_MARK_OFF, CLIP_MARK_OFF)
    assert tuple(out[1, 1]) == (255, 255, 255)
    assert tuple(out[2, 2]) == CLIP_HIGHLIGHT
    assert tuple(out[3, 3]) == CLIP_HIGHLIGHT
    assert tuple(out[0, 1]) == (128, 128, 128), "an unclipped pixel must keep its colour"


def test_clip_overlay_default_end_is_unchanged():
    """Same guarantee one level up, through the block-reduced overlay a caller
    actually uses on screen."""
    rgb = np.full((4, 4, 3), 128, np.uint8)
    rgb[0, 0] = (0, 128, 128)
    rgb[1, 1] = (0, 0, 0)
    rgb[2, 2] = (255, 255, 255)
    out = clip_overlay(rgb, (4, 4))
    assert tuple(out[0, 0]) == (CLIP_MARK_ON, CLIP_MARK_OFF, CLIP_MARK_OFF)
    assert tuple(out[1, 1]) == (255, 255, 255)
    assert tuple(out[2, 2]) == CLIP_HIGHLIGHT
    assert tuple(out[3, 3]) == (0, 0, 0), "an unclipped pixel must sit on the black ground"


def test_end_lo_is_a_white_ground_showing_shadows_only():
    rgb = np.full((4, 4, 3), 128, np.uint8)
    rgb[1, 1] = (255, 255, 255)   # blown — must NOT appear on the shadow-only view
    out = paint_clipping(rgb, np.full_like(rgb, 255), end="lo")
    assert tuple(out[0, 0]) == (255, 255, 255), "unclipped pixels must be the white ground"
    assert tuple(out[1, 1]) == (255, 255, 255), "highlight clipping must not be shown"


def test_end_lo_keeps_a_single_channels_own_colour():
    """The brief's explicit requirement: a pixel crushed in ONE channel keeps
    that channel's colour on the white ground — only the all-three case
    changes."""
    rgb = np.full((4, 4, 3), 128, np.uint8)
    rgb[0, 0] = (0, 128, 128)     # red alone crushed
    out = paint_clipping(rgb, np.full_like(rgb, 255), end="lo")
    assert tuple(out[0, 0]) == (CLIP_MARK_ON, CLIP_MARK_OFF, CLIP_MARK_OFF)


def test_end_lo_paints_the_all_channel_collision_black_not_white():
    """The one deviation the brief calls out: on a white ground, "all three
    dead" would normally paint white and vanish. It has to read black instead
    — legible, and what Photoshop's own threshold view shows."""
    rgb = np.full((4, 4, 3), 128, np.uint8)
    rgb[2, 2] = (0, 0, 0)
    out = paint_clipping(rgb, np.full_like(rgb, 255), end="lo")
    assert tuple(out[2, 2]) == (0, 0, 0)


def test_end_hi_is_a_black_ground_showing_highlights_only():
    rgb = np.full((4, 4, 3), 128, np.uint8)
    rgb[0, 0] = (0, 128, 128)     # crushed — must NOT appear on the highlight-only view
    rgb[1, 1] = (255, 255, 255)
    out = paint_clipping(rgb, np.zeros_like(rgb), end="hi")
    assert tuple(out[3, 3]) == (0, 0, 0), "unclipped pixels must be the black ground"
    assert tuple(out[0, 0]) == (0, 0, 0), "shadow clipping must not be shown"
    assert tuple(out[1, 1]) == CLIP_HIGHLIGHT


def test_a_white_ground_speck_survives_reduction_via_minimum():
    """The white-ground counterpart of
    `test_a_single_clipped_pixel_survives_reduction_to_a_smaller_preview`: a
    MAXIMUM reduction would let the surrounding white ground swallow an
    isolated dark mark, so "lo" must reduce with MINIMUM instead."""
    rgb = np.full((64, 64, 3), 128, np.uint8)
    rgb[10, 10] = 0                       # one crushed pixel
    out = clip_overlay(rgb, (8, 8), end="lo")
    assert tuple(out[1, 1]) == (0, 0, 0), "the crushed speck was washed out by the white ground"
    assert tuple(out[0, 0]) == (255, 255, 255), "a clean block must stay white"


def test_white_ground_padding_matches_the_ground_not_zero():
    """The trailing-block counterpart of
    `test_padding_preserves_a_pixel_in_the_trailing_partial_block`: a zero pad
    against a minimum reduction would crush every trailing block regardless of
    its real content."""
    rgb = np.full((65, 65, 3), 128, np.uint8)
    out = clip_overlay(rgb, (8, 8), end="lo")
    assert tuple(out[7, 7]) == (255, 255, 255), \
        "the zero-padded trailing block was crushed by its own padding"


def test_end_none_still_uses_maximum_not_minimum():
    """Guards the reduction choice itself: with the default black ground a
    MINIMUM reduction would erase an isolated blown speck instead of a
    MAXIMUM preserving it."""
    rgb = np.full((64, 64, 3), 128, np.uint8)
    rgb[10, 10] = 255
    out = clip_overlay(rgb, (8, 8))
    assert out[1, 1, 0] == 255


@pytest.mark.parametrize("src,dst", [
    ((5746, 4320), (801, 602)),     # Andreas' drizzle at 1900x1050 — 82/62 band
    ((5746, 4320), (951, 714)),     # 1600x1200 — the worst, 130/96
    ((5746, 4320), (1151, 865)),    # 1830x1400 — landed near a whole number, looked fine
    ((1000, 1000), (333, 333)),
    ((999, 777), (100, 80)),
])
def test_the_overlay_covers_the_whole_image_at_any_display_size(src, dst):
    """A uniform block size of ceil(src/dst) pads the source out to dst*ceil(...),
    which can exceed it by a whole block — and those trailing output rows are
    then pure GROUND, a hard-edged band down the right and bottom of the picture.

    On Andreas' 4320x5746 frame at 602x801: ceil(5746/801) = 8, so the source is
    padded to 6408 rows, and 662/8 = 82 output rows are padding alone. Measured
    in the app: exactly 82 rows and 62 columns. It was wrong for highlights too —
    invisible only because there the padding is black on a black ground.
    """
    h, w = dst
    # every source pixel clipped, so ANY correctly-covered output pixel is marked
    rgb = np.zeros((src[0], src[1], 3), np.uint8)
    out = clip_overlay(rgb, dst, end="lo")
    assert out.shape[:2] == dst
    ground = np.all(out == 255, axis=2)
    assert not ground.any(), (
        f"{int(ground.all(axis=1).sum())} trailing rows and "
        f"{int(ground.all(axis=0).sum())} columns are untouched ground — "
        "the overlay does not cover the whole image")


def test_the_same_hole_on_a_black_ground():
    """The highlight end has the identical defect; it just hides on black."""
    rgb = np.full((5746, 4320, 3), 255, np.uint8)      # everything blown
    out = clip_overlay(rgb, (801, 602), end="hi")
    dark = np.all(out == 0, axis=2)
    assert not dark.any(), (
        f"{int(dark.all(axis=1).sum())} rows of untouched ground on the black ground")
