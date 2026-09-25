import os

import numpy as np
from nocturne.core.image import AstroImage
from nocturne.tools.base import write_temp_fits
from nocturne.tools.rcastro import RCAstro
from nocturne.steps.star_reduction import StarReductionStep


def test_uses_starx_and_recombines():
    img = AstroImage(np.full((16, 16, 3), 0.2, np.float32), is_linear=False)
    calls = {}

    def fake(args):
        calls["args"] = args
        out = args[args.index("-o") + 1]
        write_temp_fits(AstroImage(img.data * 0.5), out)  # starless
        write_temp_fits(AstroImage(img.data * 0.5),
                        os.path.join(os.path.dirname(out), "s-sxt.fits"))  # stars

    step = StarReductionStep(RCAstro("/fake"))
    step._runner = fake
    out = step.apply(img, "medium")
    assert "sxt" in calls["args"]
    assert out.data.shape == (16, 16, 3)
    assert out.is_linear is False


def _fake_split(img):
    def fake(args):
        out = args[args.index("-o") + 1]
        write_temp_fits(AstroImage(img.data * 0.5), out)  # starless
        write_temp_fits(AstroImage(img.data * 0.5),
                        os.path.join(os.path.dirname(out), "s-sxt.fits"))  # stars
    return fake


def test_apply_accepts_float_amount():
    img = AstroImage(np.full((16, 16, 3), 0.2, np.float32), is_linear=False)
    step = StarReductionStep(RCAstro("/fake"))
    step._runner = _fake_split(img)
    out = step.apply(img, 0.6)
    assert out.data.shape == (16, 16, 3)
    assert out.is_linear is False


def test_apply_legacy_string_still_works():
    img = AstroImage(np.full((16, 16, 3), 0.2, np.float32), is_linear=False)
    step = StarReductionStep(RCAstro("/fake"))
    step._runner = _fake_split(img)
    out = step.apply(img, "medium")
    assert out.data.shape == (16, 16, 3)


def test_options_empty_and_default_blank():
    step = StarReductionStep(RCAstro("/fake"))
    assert step.options() == []
    assert step.default_option() == ""


def test_zero_amount_returns_the_input_without_splitting():
    """0 is "no change" (the slider's default). Recombining a split is not an
    identity (2.98e-8 off on a real frame), and splitting at all may launch
    StarXTerminator — so 0 must return the input before any separator runs."""
    rng = np.random.default_rng(5)
    data = rng.random((16, 16, 3), dtype=np.float32)
    img = AstroImage(data.copy(), is_linear=False)

    def boom(args):
        raise AssertionError("a star separator ran for a no-op Star Reduction")

    step = StarReductionStep(RCAstro("/fake"))
    step._runner = boom
    for option in (0.0, "", None):
        assert np.array_equal(step.apply(img, option).data, data), option


def test_nonzero_amount_still_reduces():
    img = AstroImage(np.full((16, 16, 3), 0.2, np.float32), is_linear=False)
    step = StarReductionStep(RCAstro("/fake"))
    step._runner = _fake_split(img)
    assert not np.array_equal(step.apply(img, 0.5).data, img.data)
