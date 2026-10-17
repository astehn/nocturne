"""Star Colour and Sharpen Nebulosity record which splitter separated the stars
(2026-10-17), and the report's Engines section says it instead of "not
recorded". The tap's name stays all a replay needs."""
import datetime

import numpy as np
import pytest

from nocturne.core.auto_enhance import run_auto_plan
from nocturne.core.image import AstroImage
from nocturne.core.provenance import build_report
from nocturne.recipe import recipe_from_entries
from nocturne.settings import Settings
from nocturne.steps.enhance_step import EnhanceTapStep, tap_record


def _report(entries):
    return build_report(entries, {}, app_version="x", date=datetime.date(2026, 10, 17))


def _engines(r: str) -> list[str]:
    return r.split("## Engines\n\n")[1].split("\n\n---")[0].splitlines()[2:]


def test_only_a_split_tap_records_and_only_what_ran():
    assert tap_record("Star Colour", "StarNet2") == {"ran": "StarNet2"}
    assert tap_record("Sharpen Nebulosity", "free") == {"ran": "free"}
    assert tap_record("Vibrance", "free") == ""
    assert tap_record("Star Colour", None) == ""


@pytest.mark.parametrize("ran, words", [("StarX", "StarXTerminator"), ("StarNet2", "StarNet2"),
                                         ("free", "Nocturne (built-in star split)")])
def test_the_report_names_the_splitter_that_ran(ran, words):
    r = _report([("Star Colour", {"ran": ran}), ("Sharpen Nebulosity", {"ran": ran})])
    assert _engines(r) == [f"- Star Colour: **{words}**", f"- Sharpen Nebulosity: **{words}**"]
    assert "## Parameters" not in r, "a tap has no settings to list"
    assert "1. Star Colour\n2. Sharpen Nebulosity\n" in r


def test_an_older_tap_still_says_not_recorded():
    r = _report([("Star Colour", ""), ("Sharpen Nebulosity", "")])
    assert _engines(r) == [
        "- Star Colour, Sharpen Nebulosity: not recorded — the stars were separated by "
        "StarXTerminator, StarNet2 or Nocturne's own split, whichever was set up"]


def test_two_taps_with_different_splitters_are_named_by_step():
    r = _report([("Star Colour", {"ran": "free"}), ("Star Colour", {"ran": "StarNet2"})])
    assert _engines(r) == ["- Star Colour (step 1): **Nocturne (built-in star split)**",
                           "- Star Colour (step 2): **StarNet2**"]


def test_a_recipe_replays_the_tap_by_name_alone():
    steps = recipe_from_entries([("Star Colour", {"ran": "StarX"}),
                                 ("Sharpen Nebulosity", "")]).steps
    assert steps == [{"stage": "enhance", "option": "Star Colour"},
                     {"stage": "enhance", "option": "Sharpen Nebulosity"}]


def _picture():
    rng = np.random.default_rng(9)
    data = rng.random((48, 48, 3)).astype(np.float32) * 0.2 + 0.1
    data[20:23, 20:23] = 0.95
    return AstroImage(data, is_linear=False, metadata={})


def test_a_preset_or_auto_enhance_run_records_it_too():
    step = EnhanceTapStep(splitter=None)
    step.apply(_picture(), "Star Colour")
    assert step.recorded_option("Star Colour") == {"ran": "free"}
    run = run_auto_plan(_picture(), [("enhance", "Sharpen Nebulosity"), ("enhance", "Vibrance")],
                        Settings())
    assert [(n, o) for n, o, _img in run.results] == [
        ("Sharpen Nebulosity", {"ran": "free"}), ("Vibrance", "")]
