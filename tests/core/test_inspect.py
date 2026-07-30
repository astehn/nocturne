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
