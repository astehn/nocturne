"""A step whose option separates nothing names no splitter.

The run summary said "Saturation and Star Reduction used Nocturne (free star
split)" for a preset whose Saturation had nebula boost 0 and whose Star
Reduction was 0 — neither of which splits anything (2026-10-15 review find).
The receipt asked the settings only; it now asks the option too, by the same
rule the step itself applies.
"""
import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.core.receipt import SPLIT_STAGES, engine_for, notes_for, splits_stars
from nocturne.recipe import Recipe, deserialize_option, preflight
from nocturne.settings import Settings
from nocturne.steps.factory import make_step

# (stage, option as a recipe stores it, does the step split?)
CASES = [
    ("saturation", [0.5, 0.0], False),
    ("saturation", [1.2, 0.0], False),
    ("saturation", 0.8, False),              # legacy bare amount: nebula 0
    ("saturation", "", False),               # unset: native, no boost
    ("saturation", [0.5, 0.3], True),
    ("star_reduction", 0.0, False),
    ("star_reduction", "", False),
    ("star_reduction", 0.2, True),
    ("star_reduction", "light", True),       # legacy recipe word
    # These split whatever the option says — checked against apply(), which
    # has no shortcut for them.
    ("green_fringe", 0.0, True),
    ("green_fringe", 1.0, True),
    ("starless_levels", [0.0, 1.0], True),
    ("narrowband", {"palette": "HOO"}, True),
    ("color_balance", {"midtones": [0.0, 0.0, 0.0]}, True),
]


class _Spy:
    """A splitter that counts calls and splits trivially."""
    def __init__(self):
        self.calls = 0

    def remove_stars(self, img, runner=None):
        self.calls += 1
        return (AstroImage(img.data * 0.5, is_linear=img.is_linear, metadata={}),
                AstroImage(np.zeros_like(img.data), is_linear=img.is_linear, metadata={}))


@pytest.mark.parametrize("stage,option,splits", CASES)
def test_the_rule_is_what_the_step_does(stage, option, splits):
    """Teeth against drift: run the REAL step with a counting splitter."""
    assert splits_stars(stage, option) is splits
    step = make_step(stage, Settings())
    spy = _Spy()
    for attr in ("_rc", "_splitter"):
        if hasattr(step, attr):
            setattr(step, attr, spy)
    img = AstroImage(np.full((16, 16, 3), 0.3, np.float32), is_linear=False, metadata={})
    # "" is the live 'unset' option; a recipe never stores it for these.
    step.apply(img, option if option == "" else deserialize_option(stage, option))
    assert (spy.calls > 0) is splits, f"{stage} {option!r}: step split={spy.calls > 0}"


def test_every_split_stage_has_a_case():
    assert {c[0] for c in CASES} == set(SPLIT_STAGES)


@pytest.mark.parametrize("stage,option,splits", CASES)
def test_engine_for_names_no_splitter_when_nothing_splits(stage, option, splits):
    note = engine_for(stage, Settings(), option=option)
    if splits:
        assert note is not None and note.engine
    else:
        assert note is None, note


def test_without_an_option_the_answer_is_unchanged():
    """Callers that pass no option keep today's answer exactly."""
    for sid in SPLIT_STAGES:
        note = engine_for(sid, Settings())
        assert note is not None and note.engine and note.is_fallback, sid


def test_preflight_does_not_report_a_substitute_for_a_step_that_splits_nothing():
    r = Recipe(steps=[{"stage": "saturation", "option": [0.6, 0.0]},
                      {"stage": "star_reduction", "option": 0.0},
                      {"stage": "star_reduction", "option": 0.3}])
    plans = preflight(r, Settings())
    assert [(p.outcome, p.engine) for p in plans] == [
        ("run", ""), ("run", ""), ("substitute", "Nocturne (free star split)")]


def test_the_provenance_notes_skip_a_step_that_split_nothing():
    names = ["Saturation", "Star Reduction", "Star Reduction"]
    assert notes_for(names, Settings(), options=[[0.5, 0.0], 0.0, 0.0]) == []
    # A later Star Reduction that DID split is still named.
    notes = notes_for(names, Settings(), options=[[0.5, 0.0], 0.0, 0.25])
    assert [n.step for n in notes] == ["Star Reduction"]
    # Without options, unchanged.
    assert [n.step for n in notes_for(names, Settings())] == ["Saturation", "Star Reduction"]


def test_the_provenance_report_has_no_engine_row_for_a_saturation_without_boost():
    import datetime
    from nocturne.core.provenance import build_report
    rep = build_report([("Saturation", (0.5, 0.0))], {}, app_version="x",
                       date=datetime.date(2026, 10, 16), settings=Settings())
    assert "free star split" not in rep, rep
    rep = build_report([("Saturation", (0.5, 0.3))], {}, app_version="x",
                       date=datetime.date(2026, 10, 16), settings=Settings())
    assert "Saturation: **Nocturne (free star split)**" in rep, rep
