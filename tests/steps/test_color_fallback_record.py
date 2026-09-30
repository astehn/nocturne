"""A photometric Colour that falls back to sky balance must RECORD that it did.

It recorded method="photometric" whatever ran, so the Stretch step warned about
discarding a calibration that never happened and the provenance report claimed
SPCC (found 2026-09-30). The method stays the user's choice — a recipe should
still try photometric on the next image — and `fell_back` says what ran.
"""
import numpy as np

from nocturne.core.color import ColorSettings
from nocturne.core.image import AstroImage
from nocturne.core.spcc import SpccResult
from nocturne.recipe import deserialize_option, serialize_option
from nocturne.steps.color import ColorStep
from nocturne.tools.gaia import GaiaStar

from tests.steps.test_color_step import _FakeAstap, _img


def test_a_fallback_is_recorded_and_the_choice_kept():
    step = ColorStep(astap=None, gaia_query=None)
    chosen = ColorSettings(method="photometric")
    step.apply(_img(), chosen)
    rec = step.recorded_option(chosen)
    assert rec.method == "photometric", "the user's choice stays, for recipes"
    assert rec.fell_back is True
    assert chosen.fell_back is False, "the passed option must not be mutated"


def test_a_real_calibration_is_not_marked_as_a_fallback(monkeypatch):
    monkeypatch.setattr("nocturne.core.spcc.photometric_gains",
                        lambda img, wcs, gaia, **k: SpccResult((2.0, 1.0, 0.5), 40))
    step = ColorStep(astap=_FakeAstap(),
                     gaia_query=lambda *a, **k: [GaiaStar(100.0, 0.0, 0.8, 10.0)])
    step.apply(_img(), ColorSettings(method="photometric"))
    assert step.recorded_option(ColorSettings(method="photometric")).fell_back is False


def test_a_success_after_a_failure_resets_it(monkeypatch):
    """The same step object is reused: the flag is per apply, not sticky."""
    step = ColorStep(astap=None, gaia_query=None)
    step.apply(_img(), ColorSettings(method="photometric"))
    monkeypatch.setattr("nocturne.core.spcc.photometric_gains",
                        lambda img, wcs, gaia, **k: SpccResult((2.0, 1.0, 0.5), 40))
    step._astap = _FakeAstap()
    step._gaia_query = lambda *a, **k: [GaiaStar(100.0, 0.0, 0.8, 10.0)]
    step.apply(_img(), ColorSettings(method="photometric"))
    assert step.recorded_option(ColorSettings(method="photometric")).fell_back is False


def test_mono_cannot_be_calibrated_and_says_so():
    step = ColorStep(astap=None, gaia_query=None)
    mono = AstroImage(np.random.default_rng(0).random((40, 40)).astype(np.float32),
                      is_linear=True)
    step.apply(mono, ColorSettings(method="photometric"))
    assert step.recorded_option(ColorSettings(method="photometric")).fell_back is True


def test_sky_balance_is_never_a_fallback():
    step = ColorStep()
    step.apply(_img(), ColorSettings(method="sky"))
    assert step.recorded_option(ColorSettings(method="sky")).fell_back is False


def test_the_record_survives_a_saved_project():
    ser = serialize_option("color", ColorSettings(method="photometric", fell_back=True))
    assert deserialize_option("color", ser).fell_back is True


def test_files_saved_before_the_field_read_as_no_fallback():
    old = {"neutralize_background": True, "remove_green": False, "method": "photometric"}
    assert deserialize_option("color", old).fell_back is False


def test_a_recipe_without_a_fallback_is_unchanged_on_disk():
    """No new key in the common case, so existing recipes and projects diff clean."""
    assert "fell_back" not in serialize_option("color", ColorSettings(method="photometric"))


def test_the_provenance_headline_says_what_ran():
    from nocturne.core.provenance import _headline
    ser = serialize_option("color", ColorSettings(method="photometric", fell_back=True))
    head = _headline("Color", ser)
    assert "sky" in head and "fell back" in head
    assert _headline("Color", serialize_option(
        "color", ColorSettings(method="photometric"))) == "photometric"


def test_auto_enhance_records_the_fallback_too():
    """Auto Enhance commits through its own path (serialized dicts), so it
    must ask the step what ran as well. Default Settings: no ASTAP."""
    from nocturne.core.auto_enhance import run_auto_plan
    from nocturne.settings import Settings
    out = run_auto_plan(_img(), [("color", ColorSettings(method="photometric"))], Settings())
    (name, recorded, _img_after), = out
    assert name == "Color"
    assert recorded["method"] == "photometric" and recorded.get("fell_back") is True


def _engines_color_line(option):
    import datetime
    from nocturne.core.provenance import build_report
    from nocturne.settings import Settings
    report = build_report([("Color", option)], {}, app_version="t",
                          date=datetime.date(2026, 9, 30), settings=Settings())
    return [l for l in report.splitlines() if l.startswith("- Color:")]


def test_the_engines_section_does_not_claim_spcc_after_a_fallback(monkeypatch):
    import nocturne.core.receipt as receipt
    # ASTAP configured NOW, which is all the engines section otherwise reads.
    monkeypatch.setattr(receipt, "astap_valid", lambda s: True)
    lines = _engines_color_line(ColorSettings(method="photometric", fell_back=True))
    assert lines and "ASTAP" not in lines[0] and "sky balance" in lines[0], lines
    lines = _engines_color_line(ColorSettings(method="photometric"))
    assert lines and "ASTAP" in lines[0], "a real calibration still names its tools"
