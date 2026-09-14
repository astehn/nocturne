"""The Stretch step's option gains a dict form, so the visual stretch picker can
add a `linked` key later without changing the format a second time.

Copies parse_noise_option's shape (steps/noise_sharpen.py), which already
accepts {"engine","level"} or a legacy bare string — an established pattern in
this codebase rather than a new one.
"""
import pytest

from nocturne.steps.stretch_step import parse_stretch_option


@pytest.mark.parametrize("option,expected", [
    ({"amount": 0.30}, 0.30),
    ({"amount": 0.0}, 0.0),
    (0.30, 0.30),          # legacy bare float, what every saved recipe holds
    ("0.30", 0.30),        # legacy string
    (None, 0.30),          # never applied -> the step default
    ("", 0.30),
    ({}, 0.30),            # a dict with no amount is not a crash
])
def test_both_option_shapes(option, expected):
    assert parse_stretch_option(option) == pytest.approx(expected)


def test_the_default_is_the_panel_default_not_a_second_number():
    """A step default of 0.5 while the panel defaults to 0.30 would mean Apply
    without touching anything produced something the slider never showed. Two
    numbers for one fact is how they drift apart."""
    from nocturne.ui.step_panels import STRETCH_DEFAULT
    assert parse_stretch_option(None) == pytest.approx(STRETCH_DEFAULT / 100.0)
