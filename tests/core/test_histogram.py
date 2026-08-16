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


def test_one_nan_pixel_no_longer_blanks_a_displayed_channel():
    """End-to-end reproduction of the reported symptom: a single non-finite
    pixel in a LINEAR image (the autostretched display path) turned an entire
    channel black on the canvas. 400 of 400 pixels, verified before the fix.

    Asserts the good pixels are UNCHANGED against the clean render, not merely
    'not black' — a fix that dimmed the channel would pass the weaker check."""
    from nocturne.core.image import AstroImage
    from nocturne.ui.preview import to_rgb8
    rng = np.random.default_rng(7)
    clean = (rng.random((20, 20, 3)) * 0.1).astype(np.float32)
    dirty = clean.copy()
    dirty[5, 5, 1] = np.nan

    ref = to_rgb8(AstroImage(clean, is_linear=True))
    out = to_rgb8(AstroImage(dirty, is_linear=True))
    good = np.ones((20, 20), bool)
    good[5, 5] = False

    assert out[..., 1][good].max() > 0, "the channel must not be uniformly black"
    assert np.abs(out[..., 1][good].astype(int)
                  - ref[..., 1][good].astype(int)).max() <= 1, \
        "the 399 good pixels must render as they do without the bad one"
    assert out[5, 5, 1] == 0, "the bad pixel itself reads as no-data black"


def test_a_large_histogram_is_a_sample_with_the_same_shape():
    """0.29 s of every live-preview tick on a 39.5 Mpx master, to draw a widget a
    few hundred pixels wide. A histogram is a SHAPE, and a few hundred thousand
    pixels have the same shape as forty million.

    The first version of this test passed against the unsampled code, because
    "it peaks in the right bin" is true either way. This one checks the total,
    which is the observable difference."""
    import numpy as np
    from nocturne.core.histogram import histogram
    from nocturne.core.image import AstroImage

    rng = np.random.default_rng(3)
    big = np.clip(rng.normal(0.3, 0.08, (2400, 3200, 3)), 0, 1).astype(np.float32)
    h = histogram(AstroImage(big, is_linear=False))

    total = sum(h["r"])
    assert total < 2400 * 3200, "a large histogram must be sampled, not exhaustive"
    assert total > 100_000, f"sampled too hard to be a good shape ({total})"
    peak = int(np.argmax(np.asarray(h["r"], float)))
    assert 70 <= peak <= 84, f"peaks at bin {peak}, expected ~0.3*255=77"


def test_sampling_preserves_the_clipped_fraction():
    """The clipping readout reports percentages off these counts, so what has to
    survive sampling is the RATIO, not the absolute number."""
    import numpy as np
    from nocturne.core.histogram import histogram
    from nocturne.core.inspect import clipping_from_histogram
    from nocturne.core.image import AstroImage

    rng = np.random.default_rng(7)
    data = np.clip(rng.normal(0.5, 0.2, (2000, 2600, 3)), 0, 1).astype(np.float32)
    data[:40] = 1.0                     # 2% of rows blown out
    img = AstroImage(data, is_linear=False)

    # sampled against the SAME function on the full data — the only comparison
    # that isolates sampling error. Comparing against a hand-computed "truth"
    # measures the difference between two definitions instead, which is how the
    # first version of this test managed to fail for the wrong reason.
    import nocturne.core.histogram as H
    sampled = clipping_from_histogram(histogram(img))
    real = H._sample
    H._sample = lambda a: a
    try:
        full = clipping_from_histogram(histogram(img))
    finally:
        H._sample = real

    assert abs(sampled.hi_frac - full.hi_frac) < 0.002, (sampled.hi_frac, full.hi_frac)
    assert abs(sampled.lo_frac - full.lo_frac) < 0.002, (sampled.lo_frac, full.lo_frac)


def test_small_histograms_still_count_every_pixel():
    """Below the sample threshold nothing is skipped, so the counts remain an
    exact census — several tests and the clipping readout rely on that."""
    import numpy as np
    from nocturne.core.histogram import histogram
    from nocturne.core.image import AstroImage

    data = np.full((40, 40, 3), 0.5, np.float32)
    h = histogram(AstroImage(data, is_linear=False))
    assert sum(h["r"]) == 1600
