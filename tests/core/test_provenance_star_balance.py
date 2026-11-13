"""The provenance report's Colour wording: star balance, and the records that
predate it. The "old" strings were captured from the code at 017735a9, before
star balance touched provenance."""
import pytest

from nocturne.core.provenance import _colour_headline, _colour_params, _engine_text

OLD = [
    ({"method": "sky"}, "Sky balance", ["- method: Sky balance"],
     "**Nocturne (built-in sky balance)**"),
    ({"method": "photometric"}, "Photometric (SPCC)", ["- method: Photometric (SPCC)"],
     "ASTAP + Gaia was chosen (photometric calibration); whether it ran or fell back "
     "to sky balance was not recorded for this step"),
    ({"method": "photometric", "fell_back": True},
     "Photometric (SPCC) → fell back to sky balance",
     ["- method: Photometric (SPCC)",
      "- result: sky balance — photometric calibration could not run"],
     "**Nocturne (built-in sky balance)** — photometric calibration was chosen but could not run"),
    ({"method": "photometric", "stepped_aside": True, "fell_back": True},
     "Photometric (SPCC) → stepped aside on dual-band data; sky balance",
     ["- method: Photometric (SPCC)",
      "- result: sky balance — photometric calibration is not meaningful through a "
      "dual-band filter"],
     "**Nocturne (built-in sky balance)** — photometric calibration was chosen and stepped "
     "aside: it isn't meaningful through a dual-band filter"),
]


@pytest.mark.parametrize("ser,headline,params,engine", OLD)
def test_a_record_without_ran_keeps_its_exact_text(ser, headline, params, engine):
    assert _colour_headline(ser) == headline
    assert _colour_params(ser) == params
    assert _engine_text("Color", ser) == engine


def test_a_star_record_reads_star_balance():
    ser = {"method": "star", "ran": "star", "version": 1}
    assert _colour_headline(ser) == "Star balance"
    assert _colour_params(ser) == ["- method: Star balance", "- star balance version: 1"]
    assert _engine_text("Color", ser) == "**Nocturne (built-in star balance)**"


def test_star_that_found_too_few_stars_says_so():
    ser = {"method": "star", "ran": "sky", "version": 1}
    assert _colour_headline(ser) == "Star balance → sky balance (too few stars)"
    assert _engine_text("Color", ser) == "**Nocturne (built-in sky balance)**"


def test_photometric_that_stepped_aside_to_star_balance():
    ser = {"method": "photometric", "fell_back": True, "stepped_aside": True,
           "ran": "star", "version": 1}
    assert _colour_headline(ser) == ("Photometric (SPCC) → stepped aside on dual-band "
                                     "data; star balance")
    assert "- result: star balance — photometric calibration is not meaningful through a " \
           "dual-band filter" in _colour_params(ser)
    assert _engine_text("Color", ser).startswith("**Nocturne (built-in star balance)**")


def test_photometric_that_fell_back_to_star_balance():
    ser = {"method": "photometric", "fell_back": True, "ran": "star", "version": 1}
    assert _colour_headline(ser) == "Photometric (SPCC) → fell back to star balance"
