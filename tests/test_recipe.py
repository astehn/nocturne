import pytest
from nocturne import __version__
from nocturne.core.crop import CropParams
from nocturne.core.color import ColorSettings
from nocturne.recipe import (
    Recipe, serialize_option, deserialize_option, recipe_from_entries,
    save_recipe, load_recipe,
)


def test_option_roundtrips():
    # Stretch serializes to {"amount": x} as of 2026-09-14, so the visual picker
    # can add a `linked` key later without changing the format again. Asserted
    # through the STEP's parser rather than against a literal, because what
    # matters is that a replay produces the same stretch — not the shape it
    # travelled in.
    from nocturne.steps.stretch_step import parse_stretch_option
    assert parse_stretch_option(
        deserialize_option("stretch", serialize_option("stretch", 0.6))) == 0.6
    assert deserialize_option("noise_sharpen",
                              serialize_option("noise_sharpen", "medium")) == "medium"
    lv = deserialize_option("levels", serialize_option("levels", (0.1, 1.2, 0.9)))
    assert tuple(lv) == (0.1, 1.2, 0.9)
    cs = deserialize_option("color", serialize_option("color", ColorSettings(remove_green=True)))
    assert isinstance(cs, ColorSettings) and cs.remove_green is True


def test_local_contrast_float_roundtrips():
    assert serialize_option("local_contrast", 0.6) == 0.6
    assert deserialize_option("local_contrast",
                              serialize_option("local_contrast", 0.6)) == 0.6


def test_local_contrast_legacy_string_roundtrips():
    # Pre-slider recipes stored light/medium/strong strings.
    assert serialize_option("local_contrast", "medium") == "medium"
    assert deserialize_option("local_contrast",
                              serialize_option("local_contrast", "medium")) == "medium"


def test_star_reduction_float_roundtrips():
    assert serialize_option("star_reduction", 0.5) == 0.5
    assert deserialize_option("star_reduction",
                              serialize_option("star_reduction", 0.5)) == 0.5


def test_star_reduction_legacy_string_roundtrips():
    # Pre-slider recipes stored light/medium/strong strings.
    assert serialize_option("star_reduction", "medium") == "medium"
    assert deserialize_option("star_reduction",
                              serialize_option("star_reduction", "medium")) == "medium"


def test_crop_serialize_drops_bounds():
    val = serialize_option("crop", CropParams(bounds=(1, 2, 3, 4), aspect="1:1", rotate=90))
    assert "bounds" not in val
    cp = deserialize_option("crop", val)
    assert cp.bounds is None and cp.aspect == "1:1" and cp.rotate == 90


def test_recipe_from_entries_maps_and_skips():
    entries = [("Crop", CropParams(bounds=(0, 5, 0, 5))), ("Stretch", 0.5),
               ("Unknown Step", "x")]
    r = recipe_from_entries(entries)
    assert [s["stage"] for s in r.steps] == ["crop", "stretch"]


def test_remove_green_entry_maps_and_serializes():
    from nocturne.recipe import recipe_from_entries
    rec = recipe_from_entries([("Color", None), ("De-green Sky", "")])
    stages = [s["stage"] for s in rec.steps]
    assert "remove_green" in stages


def test_save_load_roundtrip(tmp_path):
    r = Recipe(steps=[{"stage": "stretch", "option": 0.5}])
    p = tmp_path / "r.json"
    save_recipe(r, str(p))
    assert load_recipe(str(p)).steps == r.steps


def test_rotate_flip_entries_map_and_replay_params():
    from nocturne.recipe import recipe_from_entries
    rec = recipe_from_entries([("Rotate", ""), ("Flip H", ""), ("Flip V", "")])
    assert [s["stage"] for s in rec.steps] == ["rotate", "flip_h", "flip_v"]
    assert deserialize_option("rotate", "").rotate == 90
    assert deserialize_option("flip_h", "").flip_h is True
    assert deserialize_option("flip_v", "").flip_v is True


def test_mixed_geometry_recipe_keeps_order():
    from nocturne.recipe import recipe_from_entries
    rec = recipe_from_entries([("Rotate", ""), ("Crop", ""), ("Stretch", 0.5)])
    assert [s["stage"] for s in rec.steps] == ["rotate", "crop", "stretch"]


def test_uncaptured_step_names():
    from nocturne.recipe import uncaptured_step_names
    entries = [("Stretch", 0.5), ("Unknown Step", ""), ("Other Step", ""), ("Unknown Step", "")]
    assert uncaptured_step_names(entries) == ["Unknown Step", "Other Step"]
    assert uncaptured_step_names([("Stretch", 0.5), ("Levels", (0, 1, 1))]) == []


def test_curves_option_round_trip():
    from nocturne.recipe import serialize_option, deserialize_option
    pts = [(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)]
    ser = serialize_option("curves", pts)
    assert ser == [[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]]   # JSON-friendly
    assert deserialize_option("curves", ser) == pts


def test_green_fringe_option_round_trip():
    from nocturne.recipe import serialize_option, deserialize_option
    assert serialize_option("green_fringe", 0.4) == 0.4
    assert deserialize_option("green_fringe", 0.4) == 0.4


def test_saturation_option_round_trip():
    from nocturne.recipe import serialize_option, deserialize_option
    assert serialize_option("saturation", (0.7, 0.4)) == [0.7, 0.4]
    assert deserialize_option("saturation", [0.7, 0.4]) == (0.7, 0.4)
    assert deserialize_option("saturation", 0.7) == (0.7, 0.0)   # legacy bare float


def test_color_option_round_trips_method():
    from nocturne.core.color import ColorSettings
    from nocturne.recipe import serialize_option, deserialize_option
    s = serialize_option("color", ColorSettings(method="photometric"))
    assert s["method"] == "photometric"
    back = deserialize_option("color", s)
    assert back.method == "photometric"
    # default/legacy (no method key) -> "sky"
    assert deserialize_option("color", {"neutralize_background": True,
                                        "remove_green": False}).method == "sky"


def test_enhance_taps_are_captured():
    entries = [("Stretch", 0.5), ("Boost Red", None), ("Star Colour", None)]
    steps = recipe_from_entries(entries).steps
    enh = [s for s in steps if s["stage"] == "enhance"]
    assert {s["option"] for s in enh} == {"Boost Red", "Star Colour"}
    assert deserialize_option("enhance", "Boost Red") == "Boost Red"


def test_uncaptured_excludes_enhance_taps():
    from nocturne.recipe import uncaptured_step_names
    entries = [("Boost Red", None), ("Soft Glow", None)]
    assert uncaptured_step_names(entries) == []


def test_colour_balance_is_registered_as_a_recipe_step():
    """The round-trip test below passes VACUOUSLY without this: an unregistered
    stage id falls through serialize_option unchanged, so any dict round-trips
    whether or not the tool is wired in at all."""
    from nocturne.recipe import _NAME_TO_STAGE
    assert _NAME_TO_STAGE.get("Colour Balance") == "color_balance"


def test_a_colour_balance_survives_a_recipe_round_trip():
    """Otherwise it is the one finishing move a recipe cannot reproduce — which
    re-opens the export-to-Photoshop leak this feature exists to close."""
    from nocturne.recipe import deserialize_option, serialize_option
    opts = {"shadows": [0.0, 0.0, 0.0], "midtones": [-0.18, 0.0, 0.2],
            "highlights": [0.0, 0.0, 0.5],
            "preserve_lum": True, "strength": 0.8,
            "lo": 0.379, "hi": 0.748, "feather": 0.08, "invert": False}
    out = deserialize_option("color_balance", serialize_option("color_balance", opts))
    assert out == opts
    # and the types are normalised, not merely passed through
    assert isinstance(out["strength"], float) and isinstance(out["preserve_lum"], bool)


def test_a_colour_balance_saved_before_per_tone_amounts_still_loads():
    """The migration that matters. Adjustments saved on this branch before each
    tonal range had its own amounts carry a single `tone` plus one triple. They
    must open as that range's amounts with the other two at zero — and with
    invert defaulted off, since that did not exist either."""
    from nocturne.recipe import deserialize_option
    old = {"tone": "midtones", "red": -0.18, "green": 0.0, "blue": 0.2,
           "preserve_lum": True, "strength": 0.8,
           "lo": 0.379, "hi": 0.748, "feather": 0.08}
    out = deserialize_option("color_balance", old)
    assert out["midtones"] == [-0.18, 0.0, 0.2]
    assert out["shadows"] == [0.0, 0.0, 0.0]
    assert out["highlights"] == [0.0, 0.0, 0.0]
    assert out["invert"] is False
    assert out["lo"] == 0.379 and out["strength"] == 0.8


def test_an_old_shadows_adjustment_lands_in_shadows_not_midtones():
    """The migration must honour WHICH range was set — defaulting everything to
    midtones would silently move the adjustment to a different part of the
    picture on reopening."""
    from nocturne.recipe import deserialize_option
    out = deserialize_option("color_balance",
                             {"tone": "shadows", "red": 0.5, "green": 0.0, "blue": 0.0})
    assert out["shadows"] == [0.5, 0.0, 0.0]
    assert out["midtones"] == [0.0, 0.0, 0.0]


def test_a_colour_balance_recipe_keeps_its_band_absolute():
    """The band is stored as measured, not re-fitted on replay. A preset is a
    starting point computed once from the image in front of you; if a recipe
    re-derived it per image, the same recipe would mean different things on
    different frames and nothing would say so."""
    from nocturne.recipe import serialize_option
    opts = {"midtones": [0.0, 0.0, 0.2], "preserve_lum": True, "strength": 1.0,
            "lo": 0.379, "hi": 0.748, "feather": 0.08}
    ser = serialize_option("color_balance", opts)
    assert ser["lo"] == 0.379 and ser["hi"] == 0.748


def test_colour_tint_survives_a_recipe_round_trip():
    """Saved Projects reproduce pixel-exactly, so every parameter must persist."""
    from nocturne.recipe import deserialize_option, serialize_option
    restored = deserialize_option("tint", serialize_option("tint", (-0.4, 0.25)))
    assert restored == pytest.approx((-0.4, 0.25))


def test_a_project_without_a_tint_step_is_unaffected():
    """Projects saved before the tint existed simply have no tint entry.

    Nothing to migrate: the step is absent from their step list, so they replay
    exactly as before. This pins that an EMPTY option is a no-op rather than an
    error, which is what a defensive default would hit.
    """
    from nocturne.recipe import deserialize_option
    assert deserialize_option("tint", None) == (0.0, 0.0)
    assert deserialize_option("tint", []) == (0.0, 0.0)


def test_tint_step_with_no_option_leaves_the_image_alone():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.steps.tint_step import TintStep
    rng = np.random.default_rng(7)
    data = rng.random((8, 8, 3)).astype(np.float32)
    out = TintStep().apply(AstroImage(data.copy(), is_linear=True, metadata={}), None)
    assert np.array_equal(out.data, data)


def test_every_enhancement_the_panel_offers_can_be_saved_in_a_recipe():
    """ENHANCE_NAMES decides what a recipe serialises AND what counts as an
    enhancement in the history. A tap missing from it is dropped from recipes
    and reported as un-capturable — a shipped, supported action treated as
    unsupported. "Sharpen Nebulosity" was missing exactly that way: the panel
    offered 11, the tuple listed 10.
    """
    import re
    from pathlib import Path
    from nocturne.ui.pipeline import ENHANCE_NAMES
    src = (Path(__file__).parent.parent / "nocturne" / "ui" / "step_panels.py").read_text()
    # The triples are (attr, LABEL, OP) and it is the OP that must be
    # registered — "Boost Cyan (OIII)" is what the button says, "Boost Cyan" is
    # what the history records. Taking the label instead reported two false
    # positives the first time this test was written.
    offered = set(re.findall(r'\("[a-z_]+_btn",\s*"[^"]+",\s*"([^"]+)"', src))
    assert offered, "could not find the panel's enhancement buttons"
    missing = sorted(offered - set(ENHANCE_NAMES))
    assert not missing, f"the panel offers taps a recipe cannot save: {missing}"


def test_a_recipe_keeps_sharpen_nebulosity():
    from nocturne.recipe import recipe_from_entries, uncaptured_step_names
    entries = [("Stretch", 0.6), ("Sharpen Nebulosity", None)]
    steps = recipe_from_entries(entries).steps
    assert {"stage": "enhance", "option": "Sharpen Nebulosity"} in steps
    assert uncaptured_step_names(entries) == [], \
        "a supported action is still reported as un-capturable"


def test_every_saveable_enhancement_can_actually_be_replayed():
    """The half that matters. Registering a tap in ENHANCE_NAMES without a
    replay path turns "this cannot be saved" into a KeyError mid-batch — worse
    than the warning it replaces, because the batch is already running."""
    from nocturne.core.enhance import ENHANCE_OPS
    from nocturne.ui.pipeline import ENHANCE_NAMES
    from pathlib import Path
    batch_src = (Path(__file__).parent.parent / "nocturne" / "batch.py").read_text()
    for name in ENHANCE_NAMES:
        replayable = name in ENHANCE_OPS or f'"{name}":' in batch_src
        assert replayable, f"{name!r} serialises into a recipe but batch cannot apply it"


# --- preflight: what will actually happen, before anything runs -------------

def _tool(tmp_path):
    exe = tmp_path / "tool"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return str(exe)


def test_preflight_says_run_substitute_or_fail_for_every_step(tmp_path):
    """missing_tools answers "can this run at all"; this is the other half. A
    recipe that CAN run may still not do what its author did — six of the eight
    tool-backed stages silently fall back to a free implementation."""
    from nocturne.recipe import Recipe, preflight
    from nocturne.settings import Settings
    r = Recipe(steps=[{"stage": "stretch", "option": 0.6},
                      {"stage": "star_reduction", "option": 0.4},
                      {"stage": "background", "option": "strong"}])
    plans = {p.step: p for p in preflight(r, Settings())}
    assert plans["Stretch"].outcome == "run"
    assert plans["Star Reduction"].outcome == "substitute"
    assert "free star split" in plans["Star Reduction"].engine
    assert plans["Background"].outcome == "fail"
    assert plans["Background"].ok is False


def test_preflight_says_everything_runs_when_the_tools_are_there(tmp_path):
    from nocturne.recipe import Recipe, preflight, preflight_summary
    from nocturne.settings import Settings
    exe = _tool(tmp_path)
    s = Settings(rcastro_path=exe, graxpert_path=exe, astap_path=exe)
    r = Recipe(steps=[{"stage": "background", "option": "strong"},
                      {"stage": "star_reduction", "option": 0.4}])
    plans = preflight(r, s)
    assert [p.outcome for p in plans] == ["run", "run"]
    assert preflight_summary(plans) == "All 2 steps will run as saved."


def test_the_summary_leads_with_what_stops_the_run(tmp_path):
    """A failure and a substitution in the same recipe: the failure is what the
    user has to act on, so it must not be buried behind the substitution."""
    from nocturne.recipe import Recipe, preflight, preflight_summary
    from nocturne.settings import Settings
    r = Recipe(steps=[{"stage": "star_reduction", "option": 0.4},
                      {"stage": "background", "option": "strong"}])
    line = preflight_summary(preflight(r, Settings()))
    assert line.startswith("1 step cannot run")
    assert "Background" in line


def test_the_preflight_agrees_with_missing_tools(tmp_path):
    """Two independently computed answers about the same recipe must not
    disagree — the stricter one wins, or the preflight promises a run the batch
    then aborts."""
    from nocturne.recipe import Recipe, missing_tools, preflight
    from nocturne.settings import Settings
    r = Recipe(steps=[{"stage": "background", "option": "strong"}])
    blocked = missing_tools(r, Settings())
    plans = preflight(r, Settings())
    assert bool(blocked) == any(not p.ok for p in plans)


def test_an_off_background_needs_nothing(tmp_path):
    """"off" is a real option that does not call GraXpert, and missing_tools
    already excludes it. The preflight must agree."""
    from nocturne.recipe import Recipe, missing_tools, preflight
    from nocturne.settings import Settings
    r = Recipe(steps=[{"stage": "background", "option": "off"}])
    assert missing_tools(r, Settings()) == []
    # ...and so must the preflight. "off" returns the image untouched and never
    # reaches GraXpert, so reporting a failure here would be a warning about
    # something that cannot happen — and would contradict missing_tools about
    # the same recipe. The first version of this test asserted "fail" and
    # called it honest; it was not.
    assert preflight(r, Settings())[0].outcome == "run"


def test_an_enhancement_is_named_by_its_tap(tmp_path):
    from nocturne.recipe import Recipe, preflight
    from nocturne.settings import Settings
    r = Recipe(steps=[{"stage": "enhance", "option": "Boost Gold"}])
    assert preflight(r, Settings())[0].step == "Boost Gold"


def test_starless_levels_is_reported_as_uncaptured_not_silently_saved():
    """Recipe-capturing it destroys a whole batch.

    The name USED to be in `_NAME_TO_STAGE`, which both serialised the step
    into the recipe and removed it from `uncaptured_step_names` — so Save
    Recipe stopped warning. There is no `starless_levels` case in `make_step`,
    so preflight said "This step will run as saved" and `apply_recipe` then
    raised `ValueError('starless_levels')`, which run_batch's per-file
    `except Exception` turns into a failure for EVERY file in the folder,
    under a raw stage id.

    It is not implemented as a replayable step because it should not be one:
    the two values come from a person looking at one picture, so they do not
    transfer to the next target. The honest answer is the warning.
    """
    from nocturne.recipe import (_NAME_TO_STAGE, recipe_from_entries,
                                 uncaptured_step_names)
    entries = [("Stretch", 0.5), ("Starless Levels", (0.1, 0.8))]
    assert "Starless Levels" not in _NAME_TO_STAGE
    assert uncaptured_step_names(entries) == ["Starless Levels"]
    # ...and it is left out of the recipe rather than written as a stage no
    # loader can build.
    assert [s["stage"] for s in recipe_from_entries(entries).steps] == ["stretch"]



def test_preflight_refuses_a_stage_the_factory_cannot_build():
    """A recipe naming a stage `make_step` cannot construct used to report
    "this step will run as saved", and `apply_recipe` then raised — which
    `run_batch`'s per-file `except Exception` turned into a failure for EVERY
    file in the folder, with a raw stage id as the message.

    That happened for real: Colour Balance was registered as capturable and
    fully serialised while `make_step` had no case for it. Preflight must answer
    the question it claims to answer — can this actually run — rather than
    assuming any named stage can.
    """
    from nocturne.recipe import Recipe, preflight
    from nocturne.settings import Settings

    r = Recipe(steps=[{"stage": "not_a_real_stage", "option": ""}])
    plans = preflight(r, Settings())
    assert [p.outcome for p in plans] == ["fail"], (
        f"preflight promised an unbuildable stage would run: {plans}")
    assert plans[0].reason, "a failure with no reason tells the user nothing"
    assert "not_a_real_stage" not in plans[0].reason.replace(
        plans[0].step, ""), "the reason should not show a raw stage id"


def test_preflight_still_passes_every_real_stage():
    """The guard must not start refusing stages that genuinely work."""
    from nocturne.recipe import Recipe, preflight, serialize_option
    from nocturne.settings import Settings

    for sid, opt in (("stretch", 0.5), ("levels", (0.0, 1.0, 1.0)),
                     ("curves", None), ("crop", None), ("flip_h", None)):
        r = Recipe(steps=[{"stage": sid, "option": serialize_option(sid, opt)}])
        plans = preflight(r, Settings())
        assert plans[0].outcome != "fail" or plans[0].reason, (
            f"{sid} was refused: {plans[0]}")


def test_a_recipe_from_another_pre_1_0_build_is_refused(tmp_path):
    """Andreas, 2026-09-14, on replay compatibility costing something on nearly
    every change: *"i could probably argue for that we should remove that
    functionality entirely"* until 1.0.

    The cheap cure for the same goal: stop PROTECTING compatibility instead of
    removing the feature. A step's meaning can then change freely while the
    pipeline is still being settled, and an older recipe says so out loud
    instead of quietly producing a different picture.
    """
    import json
    from nocturne.recipe import RecipeVersionError, load_recipe

    p = tmp_path / "old.json"
    p.write_text(json.dumps({"version": 1, "app": "0.29.0",
                             "steps": [{"stage": "stretch", "option": 0.5}]}))
    with pytest.raises(RecipeVersionError) as exc:
        load_recipe(str(p))
    msg = str(exc.value)
    assert "0.29.0" in msg and __version__ in msg, \
        "the message must name BOTH versions, or it cannot be acted on"
    assert "save the recipe again" in msg, "and say what to do about it"


def test_a_recipe_with_no_app_field_is_refused_too(tmp_path):
    """Recipes written before this existed carry no `app`. They were produced by
    an unknown older build, which is the case being guarded against."""
    import json
    from nocturne.recipe import RecipeVersionError, load_recipe

    p = tmp_path / "ancient.json"
    p.write_text(json.dumps({"version": 1, "steps": []}))
    with pytest.raises(RecipeVersionError):
        load_recipe(str(p))


def test_a_recipe_this_build_wrote_still_loads(tmp_path):
    """The half that matters: the guard must not break the feature. Round-trips
    through save_recipe rather than a hand-written file, so the two stay in
    step — a `save_recipe` that stopped writing `app` would make every recipe
    it produced unreadable, and only this catches that."""
    from nocturne.recipe import Recipe, load_recipe, save_recipe

    p = tmp_path / "fresh.json"
    save_recipe(Recipe(steps=[{"stage": "stretch", "option": 0.5}]), str(p))
    assert load_recipe(str(p)).steps == [{"stage": "stretch", "option": 0.5}]


def test_the_strictness_lifts_itself_at_1_0(tmp_path, monkeypatch):
    """Gated on RELEASE_STAGE so nobody has to remember to remove it. Once
    Nocturne ships stable, an older recipe loads again."""
    import json
    import nocturne.recipe as r

    p = tmp_path / "old.json"
    p.write_text(json.dumps({"version": 1, "app": "0.29.0", "steps": []}))
    monkeypatch.setattr(r, "RELEASE_STAGE", "")
    assert r.load_recipe(str(p)).steps == []


def test_recipe_roundtrips_the_stretch_mechanism():
    """The dict shape landed on 2026-09-14 precisely so `linked` could be added
    without changing the stored format a second time. Asserted through the
    STEP's parsers: what matters is that a replay produces the same stretch."""
    from nocturne.steps.stretch_step import parse_stretch_linked, parse_stretch_option
    o = deserialize_option("stretch", serialize_option("stretch",
                                                       {"amount": 0.6, "linked": False}))
    assert parse_stretch_option(o) == 0.6
    assert parse_stretch_linked(o) is False


def test_a_recipe_without_the_flag_replays_as_linked():
    """Everything written before today predates the choice."""
    from nocturne.steps.stretch_step import parse_stretch_linked
    assert parse_stretch_linked(deserialize_option(
        "stretch", serialize_option("stretch", 0.6))) is True
