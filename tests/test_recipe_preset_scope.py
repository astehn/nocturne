import pytest
from nocturne.recipe import (PRESET_EXCLUDED_NAMES, PRESET_ONLY_STAGES, deserialize_option,
                             recipe_from_entries, serialize_option, step_display_name,
                             uncaptured_step_names)

SPIKES = {"length": 0.35, "count": 6, "angle": 45.0, "intensity": 0.8,
          "variation": 0.1, "colour": 0.5}
ENTRIES = [("Crop", None), ("Rotate", ""), ("Background", "strong"),
           ("Stretch", {"amount": 0.3, "linked": True}), ("Trim", {"aspect": "4:5"}),
           ("Starless Levels", (0.1, 0.8)), ("Star Spikes", SPIKES), ("Vibrance", ""),
           ("Flip H", ""), ("Trim", {"aspect": "1:1"})]


def test_recipe_scope_is_unchanged():
    """Save Recipe and Batch stay exactly as they are (spec)."""
    assert [s["stage"] for s in recipe_from_entries(ENTRIES).steps] == \
        ["crop", "rotate", "background", "stretch", "enhance", "flip_h"]
    assert uncaptured_step_names(ENTRIES) == ["Trim", "Starless Levels", "Star Spikes"]


def test_preset_scope_strips_geometry_and_trim_and_keeps_the_tools():
    steps = recipe_from_entries(ENTRIES, scope="preset").steps
    assert [s["stage"] for s in steps] == \
        ["background", "stretch", "starless_levels", "star_spikes", "enhance"]
    assert not {s["stage"] for s in steps} & {"crop", "rotate", "flip_h", "flip_v"}
    assert uncaptured_step_names(ENTRIES, scope="preset") == []   # excluded is not "left out"


def test_a_spikes_entry_without_its_sliders_is_left_out_and_named():
    e = [("Stretch", 0.3), ("Star Spikes", "")]        # recorded before 2026-09-17
    assert [s["stage"] for s in recipe_from_entries(e, scope="preset").steps] == ["stretch"]
    assert uncaptured_step_names(e, scope="preset") == ["Star Spikes"]


def test_retired_and_unknown_steps_are_left_out_in_both_scopes():
    e = [("Linear Denoise", "x"), ("Mystery", 1), ("Stretch", 0.3)]
    for scope in ("recipe", "preset"):
        assert uncaptured_step_names(e, scope=scope) == ["Linear Denoise", "Mystery"]


@pytest.mark.parametrize("scope", ["recipe", "preset"])
def test_every_entry_is_either_stored_or_named(scope):
    """One rule decides both answers, so they cannot disagree."""
    stored = len(recipe_from_entries(ENTRIES, scope=scope).steps)
    named = {n for n in uncaptured_step_names(ENTRIES, scope=scope)}
    excluded = sum(1 for n, _ in ENTRIES if scope == "preset" and n in PRESET_EXCLUDED_NAMES)
    unnamed_left = sum(1 for n, _ in ENTRIES if n in named)
    assert stored + unnamed_left + excluded == len(ENTRIES)
    stored_names = {step_display_name(st["stage"], st["option"])
                    for st in recipe_from_entries(ENTRIES, scope=scope).steps}
    assert not stored_names & named


def test_new_stage_options_round_trip_through_json():
    import json
    for sid, native in (("star_spikes", SPIKES), ("starless_levels", (0.1, 0.8))):
        ser = json.loads(json.dumps(serialize_option(sid, native)))
        assert deserialize_option(sid, ser) == (native if sid == "star_spikes" else (0.1, 0.8))


def test_display_names_for_preset_steps():
    assert step_display_name("star_spikes") == "Star Spikes"
    assert step_display_name("starless_levels") == "Starless Levels"
    assert step_display_name("enhance", "Boost Gold") == "Boost Gold"
    assert step_display_name("noise_sharpen") == "Noise Reduction"


def test_preflight_builds_the_new_stages_for_a_preset_and_refuses_them_in_a_recipe():
    """make_step can build them (the preset runner needs it), but a recipe must
    not replay Starless Levels' hand-picked values across a batch."""
    from nocturne.recipe import CANNOT_BUILD_REASON, Recipe, preflight
    from nocturne.settings import Settings
    r = Recipe(steps=[{"stage": "star_spikes", "option": SPIKES},
                      {"stage": "starless_levels", "option": [0.1, 0.8]}])
    # Starless Levels takes a star splitter; with none installed it runs on the
    # built-in split, which the receipt names as a substitute (2026-10-15).
    assert [(p.outcome, p.engine) for p in preflight(r, Settings(), scope="preset")] == [
        ("run", ""), ("substitute", "Nocturne (free star split)")]
    refused = preflight(r, Settings())
    assert [(p.step, p.outcome, p.reason) for p in refused] == [
        ("Star Spikes", "fail", CANNOT_BUILD_REASON),
        ("Starless Levels", "fail", CANNOT_BUILD_REASON)]


@pytest.mark.parametrize("stage, option", [("star_spikes", SPIKES),
                                           ("starless_levels", [0.1, 0.8])])
def test_apply_recipe_refuses_a_preset_only_stage(stage, option):
    import numpy as np
    from nocturne.batch import apply_recipe
    from nocturne.core.image import AstroImage
    from nocturne.recipe import Recipe
    from nocturne.settings import Settings
    img = AstroImage(np.full((8, 8, 3), 0.2, np.float32), is_linear=False)
    with pytest.raises(ValueError, match=stage):
        apply_recipe(img, Recipe(steps=[{"stage": stage, "option": option}]), Settings())


def test_preset_only_stages_are_not_in_the_recipe_map():
    from nocturne.recipe import _NAME_TO_STAGE
    assert not set(PRESET_ONLY_STAGES) & set(_NAME_TO_STAGE)
