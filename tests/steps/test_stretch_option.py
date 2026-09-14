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


def test_linked_reads_from_every_option_shape():
    """A SIBLING of parse_stretch_option, not a change to its return type —
    that has three callers. Defaults True: every option written before
    2026-09-14 predates the choice and means linked."""
    from nocturne.steps.stretch_step import parse_stretch_linked
    assert parse_stretch_linked({"amount": 0.3, "linked": False}) is False
    assert parse_stretch_linked({"amount": 0.3, "linked": True}) is True
    assert parse_stretch_linked({"amount": 0.3}) is True     # written pre-today
    assert parse_stretch_linked(0.3) is True                 # legacy bare float
    assert parse_stretch_linked(None) is True
    assert parse_stretch_linked("") is True


def test_the_step_honours_the_mechanism():
    """The wiring, not just the parser: StretchStep must pass it through."""
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.stretch import apply_stretch
    from nocturne.steps.stretch_step import StretchStep

    rng = np.random.default_rng(0)
    d = np.clip(rng.normal(0.02, 0.005, (48, 32, 3)), 0, 1).astype(np.float32)
    d[..., 0] = np.clip(0.02 + (d[..., 0] - 0.02) * 2.67, 0, 1)
    img = AstroImage(d, is_linear=True)

    got = StretchStep().apply(img, {"amount": 0.3, "linked": False})
    assert np.array_equal(got.data, apply_stretch(img, 0.3, linked=False).data)
