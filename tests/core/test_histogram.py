import warnings

import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.histogram import histogram


def test_color_histogram_channels_and_counts():
    h = histogram(AstroImage(np.full((10, 10, 3), 0.5, np.float32)), bins=256)
    assert set(h) == {"r", "g", "b"}
    assert all(len(v) == 256 for v in h.values())
    assert int(h["r"].sum()) == 100


def test_mono_histogram():
    h = histogram(AstroImage(np.zeros((4, 4), np.float32)), bins=64)
    assert set(h) == {"l"} and len(h["l"]) == 64


def test_histogram_top_bin_matches_the_uint8_display_value():
    # The clipping overlay paints where uint8 == 255. The histogram's top bin
    # must mean the same thing, or the warning and the picture disagree.
    data = np.array([[[0.9990, 0.5, 0.5]]], np.float32)   # -> uint8 255
    assert int(histogram(AstroImage(data))["r"][-1]) == 1
    data = np.array([[[0.9970, 0.5, 0.5]]], np.float32)   # -> uint8 254
    assert int(histogram(AstroImage(data))["r"][-1]) == 0


def test_histogram_bottom_bin_matches_the_uint8_display_value():
    data = np.array([[[0.0010, 0.5, 0.5]]], np.float32)   # -> uint8 0
    assert int(histogram(AstroImage(data))["r"][0]) == 1
    data = np.array([[[0.0050, 0.5, 0.5]]], np.float32)   # -> uint8 1
    assert int(histogram(AstroImage(data))["r"][0]) == 0


def test_histogram_clamps_out_of_range_values_into_the_end_bins():
    data = np.array([[[2.0, -1.0, 0.5]]], np.float32)
    h = histogram(AstroImage(data))
    assert int(h["r"][-1]) == 1 and int(h["g"][0]) == 1


def test_histogram_non_default_bin_count_still_works():
    h = histogram(AstroImage(np.zeros((4, 4), np.float32)), bins=64)
    assert set(h) == {"l"} and len(h["l"]) == 64 and int(h["l"][0]) == 16


def test_histogram_nan_pixels_land_in_bottom_bin_without_warning():
    # NaN is reachable here: fits_io._normalize() returns the array untouched
    # when arr.max() is NaN, and AstroImage enforces no finiteness invariant.
    # nocturne.ui.preview.to_qimage's uint8 cast already implicitly turns NaN
    # into displayed black, so counting NaN pixels in the bottom bin keeps the
    # histogram's shadow count in agreement with what the clipping overlay
    # actually paints on screen, rather than silently dropping them the way
    # the old np.histogram path did.
    data = np.full((2, 2, 3), 0.5, np.float32)
    data[0, 0, 0] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        h = histogram(AstroImage(data))
    assert int(h["r"][0]) == 1
    assert int(h["r"].sum()) == 4  # NaN pixel is counted, not dropped
