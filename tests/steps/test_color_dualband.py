"""Photometric colour steps aside on dual-band (Seestar LP filter) data.

Through two narrow passbands a star's colour no longer tracks its Gaia BP-RP,
so the calibration would be fitting noise. Approved 2026-10-10: use sky balance
and say so, in exactly these words.
"""
import numpy as np

from nocturne.core.color import ColorSettings, apply_color
from nocturne.core.image import AstroImage
from nocturne.core.spcc import SpccResult
from nocturne.steps.color import DUALBAND_MESSAGE, ColorStep
from nocturne.tools.gaia import GaiaStar

from tests.steps.test_color_step import _FakeAstap

_EXACT = ("Photometric colour isn't meaningful through a dual-band filter; "
          "balanced on the sky instead.")


def _img(filt):
    rng = np.random.default_rng(0)
    meta = {"focal_length": 160.0, "pixel_size": 2.9}
    if filt is not None:
        meta["filter"] = filt
    return AstroImage(rng.random((40, 40, 3)).astype(np.float32), is_linear=True,
                      metadata=meta)


def _spy(monkeypatch):
    calls = []

    def gains(img, wcs, gaia, **k):
        calls.append(1)
        return SpccResult((2.0, 1.0, 0.5), 40)
    monkeypatch.setattr("nocturne.core.spcc.photometric_gains", gains)
    solves = []
    astap = _FakeAstap()
    real = astap.solve

    def solve(img, **kw):
        solves.append(1)
        return real(img, **kw)
    astap.solve = solve
    step = ColorStep(astap=astap,
                     gaia_query=lambda *a, **k: [GaiaStar(100.0, 0.0, 0.8, 10.0)])
    return step, calls, solves


def test_the_message_is_word_for_word():
    assert DUALBAND_MESSAGE == _EXACT


def test_lp_filter_steps_aside_to_sky_balance(monkeypatch):
    step, calls, solves = _spy(monkeypatch)
    img = _img("LP")
    chosen = ColorSettings(method="photometric", remove_green=True)
    out = step.apply(img, chosen)
    assert calls == [] and solves == [], "photometric must not run on dual-band data"
    assert step.fell_back is True
    assert step.last_message == _EXACT
    # Exactly the sky balance the fallback path gives, nothing else.
    want = apply_color(img, ColorSettings(remove_green=True))
    np.testing.assert_array_equal(out.data, want.data)
    rec = step.recorded_option(chosen)
    assert rec.method == "photometric" and rec.fell_back is True


def test_ircut_and_unknown_filters_run_photometric(monkeypatch):
    for filt in ("IRCUT", None, ""):
        step, calls, solves = _spy(monkeypatch)
        step.apply(_img(filt), ColorSettings(method="photometric"))
        assert calls == [1], filt
        assert step.fell_back is False, filt
        assert "stars matched" in step.last_message, filt


def test_sky_method_on_lp_data_says_nothing(monkeypatch):
    step, calls, _ = _spy(monkeypatch)
    step.apply(_img("LP"), ColorSettings(method="sky"))
    assert calls == [] and step.last_message == "" and step.fell_back is False


def test_auto_enhance_on_lp_data_steps_aside_without_failing(monkeypatch):
    # A calibration that WOULD succeed, so only the step-aside can set fell_back.
    monkeypatch.setattr("nocturne.core.spcc.photometric_gains",
                        lambda img, wcs, gaia, **k: SpccResult((2.0, 1.0, 0.5), 40))
    from nocturne.core.auto_enhance import run_auto_plan
    from nocturne.settings import Settings
    from nocturne.steps import factory
    img = _img("LP")
    plan = [("color", ColorSettings(method="photometric"))]
    orig = factory.make_step

    def make(stage_id, settings, **kw):
        if stage_id == "color":
            return ColorStep(astap=_FakeAstap(),
                             gaia_query=lambda *a, **k: [GaiaStar(100.0, 0.0, 0.8, 10.0)])
        return orig(stage_id, settings, **kw)
    monkeypatch.setattr("nocturne.core.auto_enhance.make_step", make)
    results = run_auto_plan(img, plan, Settings())
    assert len(results) == 1, "the colour stage must still land"
    name, ser, _ = results[0]
    assert ser["method"] == "photometric" and ser.get("fell_back") is True
