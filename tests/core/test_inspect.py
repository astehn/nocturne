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
    assert hi.tolist() == [[True, False, False, False]]
    assert sh.tolist() == [[False, True, False, False]]


def test_clip_masks_return_2d_boolean_arrays():
    sh, hi = clip_masks(np.zeros((3, 5, 3), np.uint8))
    assert sh.shape == (3, 5) and sh.dtype == bool
    assert hi.shape == (3, 5) and hi.dtype == bool
