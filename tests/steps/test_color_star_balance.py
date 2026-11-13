"""ColorStep: star balance, what runs when, and what is recorded as having run."""
import numpy as np
import pytest

from nocturne.core.color import ColorSettings, apply_color
from nocturne.core.image import AstroImage
from nocturne.core.spcc import SpccResult
from nocturne.core.star_balance import STAR_BALANCE_VERSION, apply_star_balance
from nocturne.steps.color import DUALBAND_MESSAGE, ColorStep
from nocturne.tools.gaia import GaiaStar

from tests.core.test_star_balance import _field
from tests.steps.test_color_step import _FakeAstap


def _stars(n=150, filt=None):
    meta = {"focal_length": 160.0, "pixel_size": 2.9}
    if filt:
        meta["filter"] = filt
    return AstroImage(_field(n_stars=n), is_linear=True, metadata=meta)


def _rec(step, settings):
    return step.recorded_option(settings)


def test_star_method_runs_star_balance():
    img, s = _stars(), ColorSettings(method="star")
    step = ColorStep()
    out = step.apply(img, s)
    np.testing.assert_array_equal(out.data, apply_star_balance(img)[0].data)
    rec = _rec(step, s)
    assert (rec.ran, rec.version, rec.method) == ("star", STAR_BALANCE_VERSION, "star")
    assert step.last_gains is not None and step.last_n_stars >= 15


def test_remove_green_still_runs_after_star_balance():
    img = _stars()
    out = ColorStep().apply(img, ColorSettings(method="star", remove_green=True))
    want = apply_color(apply_star_balance(img)[0],
                       ColorSettings(neutralize_background=False, remove_green=True))
    np.testing.assert_array_equal(out.data, want.data)
    assert not np.array_equal(out.data, apply_star_balance(img)[0].data)


def test_the_recorded_version_is_the_one_used():
    img = _stars()
    step = ColorStep()
    step.apply(img, ColorSettings(method="star", version=1))
    assert _rec(step, ColorSettings(method="star", version=1)).version == 1
    with pytest.raises(ValueError):
        step.apply(img, ColorSettings(method="star", version=99))


def test_dualband_photometric_steps_aside_to_star_balance():
    img, s = _stars(filt="LP"), ColorSettings(method="photometric")
    step = ColorStep(astap=_FakeAstap(), gaia_query=lambda *a, **k: [])
    out = step.apply(img, s)
    assert step.last_message == DUALBAND_MESSAGE
    np.testing.assert_array_equal(out.data, apply_star_balance(img)[0].data)
    rec = _rec(step, s)
    assert rec.ran == "star" and rec.stepped_aside and rec.fell_back
    assert rec.method == "photometric"


def test_photometric_failure_falls_back_to_star_balance():
    img, s = _stars(), ColorSettings(method="photometric")
    step = ColorStep(astap=None, gaia_query=None)
    out = step.apply(img, s)
    np.testing.assert_array_equal(out.data, apply_star_balance(img)[0].data)
    assert step.last_message.endswith("used star balance.")
    rec = _rec(step, s)
    assert rec.ran == "star" and rec.fell_back and not rec.stepped_aside


def test_star_balance_with_too_few_stars_falls_back_to_sky():
    img, s = _stars(n=5), ColorSettings(method="star", remove_green=True)
    step = ColorStep()
    out = step.apply(img, s)
    np.testing.assert_array_equal(
        out.data, apply_color(img, ColorSettings(remove_green=True)).data)
    assert "Too few stars to balance on" in step.last_message
    assert "used sky balance" in step.last_message
    rec = _rec(step, s)
    assert rec.ran == "sky" and rec.version == 0 and not rec.fell_back
    assert step.last_gains is None


def test_photometric_failure_then_too_few_stars_says_both():
    step = ColorStep(astap=None, gaia_query=None)
    step.apply(_stars(n=5), ColorSettings(method="photometric"))
    assert step.last_message == ("ASTAP not set \u2014 star balance couldn't run either "
                                 "(too few stars to balance on) \u2014 used sky balance.")
    assert "used star balance" not in step.last_message
    assert _rec(step, ColorSettings(method="photometric")).ran == "sky"


def test_sky_method_is_unchanged():
    img = _stars()
    step = ColorStep()
    out = step.apply(img, ColorSettings(method="sky"))
    assert out.data.tobytes() == apply_color(img, ColorSettings(method="sky")).data.tobytes()
    rec = _rec(step, ColorSettings(method="sky"))
    assert rec.ran == "sky" and rec.version == 0


def test_photometric_success_records_photometric(monkeypatch):
    monkeypatch.setattr("nocturne.core.spcc.photometric_gains",
                        lambda img, wcs, gaia, **k: SpccResult((2.0, 1.0, 0.5), 40))
    step = ColorStep(astap=_FakeAstap(),
                     gaia_query=lambda *a, **k: [GaiaStar(100.0, 0.0, 0.8, 10.0)])
    step.apply(_stars(), ColorSettings(method="photometric"))
    rec = _rec(step, ColorSettings(method="photometric"))
    assert rec.ran == "photometric" and rec.version == 0 and not rec.fell_back


def test_ran_does_not_stick_between_applies():
    step = ColorStep()
    step.apply(_stars(), ColorSettings(method="star"))
    step.apply(_stars(), ColorSettings(method="sky"))
    rec = _rec(step, ColorSettings(method="sky"))
    assert (rec.ran, rec.version) == ("sky", 0)
    assert step.last_gains is None


def test_tls_failure_falls_back_to_star_balance_and_says_so():
    from nocturne.tools.gaia import GaiaTlsError

    def boom(*a, **k):
        raise GaiaTlsError("bad cert")
    img, s = _stars(), ColorSettings(method="photometric")
    step = ColorStep(astap=_FakeAstap(), gaia_query=boom)
    step.apply(img, s)
    assert "Used star balance." in step.last_message
    assert "sky balance" not in step.last_message
    assert _rec(step, s).ran == "star"


def test_implausible_correction_is_reported_as_such():
    img = AstroImage(_field(cast=np.array([4.0, 1.0, 0.86], np.float32)),
                     is_linear=True, metadata={})
    s = ColorSettings(method="star")
    step = ColorStep()
    step.apply(img, s)
    assert step.last_message == ("The star colours gave an implausible correction "
                                 "\u2014 used sky balance.")
    rec = _rec(step, s)
    assert rec.ran == "sky" and rec.star_fallback == "implausible"


def test_too_few_stars_records_its_reason():
    step = ColorStep()
    s = ColorSettings(method="star")
    step.apply(_stars(n=5), s)
    assert _rec(step, s).star_fallback == "too_few_stars"
    step.apply(_stars(), s)               # a later success clears it
    assert _rec(step, s).star_fallback == ""


def test_sky_fallback_on_a_bordered_master_is_not_black():
    d = _field(n_stars=5)
    d[:, :200] = 0                        # 33% untrimmed border
    step = ColorStep()
    out = step.apply(AstroImage(d, is_linear=True, metadata={}), ColorSettings(method="star"))
    assert step.ran == "sky"
    assert (out.data[:, :200] == 0).all() and np.median(out.data[:, 200:]) > 0.01


def test_a_bordered_master_runs_star_balance():
    d = _field()
    d[:, :200] = 0
    step = ColorStep()
    out = step.apply(AstroImage(d, is_linear=True, metadata={}), ColorSettings(method="star"))
    assert step.ran == "star" and np.median(out.data[:, 200:]) > 0.01
