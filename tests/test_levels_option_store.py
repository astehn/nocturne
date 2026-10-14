"""The versioned Levels option through recipes, presets, batch, saved
projects and the provenance report (spec 2026-10-14-levels-clip-aware, C)."""
import datetime
import json

import numpy as np

from nocturne.core.image import AstroImage
from nocturne.core.levels import (AUTO, apply_levels, auto_black, auto_levels,
                                  new_levels_option)
from nocturne.history.project import Project
from nocturne.history.project_store import load_project, save_project
from nocturne.recipe import (Recipe, deserialize_option, recipe_from_entries,
                             serialize_option, uncaptured_step_names)
from nocturne.settings import Settings
from nocturne.steps.factory import make_step
from tests.core.test_levels_clip_aware import _stop_image

V2 = new_levels_option(auto=True)
V2_BLUE = new_levels_option(auto=True, offsets=(0.0, 0.0, -0.015))
MANUAL = new_levels_option(0.07, 1.1, 0.97, offsets=(0.012, 0.0, 0.0))


def _v1(img):
    return apply_levels(img, *auto_levels(img.data)).data


def _v2(img):
    return apply_levels(img, auto_black(img).black, 1.0, 1.0).data


def test_fixture_tells_v1_from_v2():
    img = _stop_image()
    assert not np.array_equal(_v1(img), _v2(img))


# --- recipe / preset semantics --------------------------------------------

def test_recipe_auto_means_the_current_auto():
    assert deserialize_option("levels", AUTO) == V2


def test_project_auto_stays_version_1():
    assert deserialize_option("levels", AUTO, project=True) == AUTO


def test_dicts_round_trip_through_json_keeping_their_version():
    for opt in (V2, V2_BLUE, MANUAL, {"auto": True, "version": 1, "offsets": [0, 0, 0]}):
        ser = json.loads(json.dumps(serialize_option("levels", opt)))
        assert deserialize_option("levels", ser) == serialize_option("levels", opt)
        assert deserialize_option("levels", ser, project=True) == serialize_option("levels", opt)
    assert serialize_option("levels", {"auto": True, "version": 1})["version"] == 1


def test_legacy_shapes_serialize_as_before():
    assert serialize_option("levels", AUTO) == AUTO
    assert serialize_option("levels", (0.1, 1.0, 0.9)) == [0.1, 1.0, 0.9]
    assert deserialize_option("levels", [0.1, 1.0, 0.9]) == (0.1, 1.0, 0.9)


def test_levels_stays_capturable():
    entries = [("Levels", V2_BLUE), ("Levels", MANUAL), ("Levels", AUTO)]
    for scope in ("recipe", "preset"):
        assert uncaptured_step_names(entries, scope=scope) == []
        steps = recipe_from_entries(entries, scope=scope).steps
        assert [s["option"] for s in steps] == [V2_BLUE, MANUAL, AUTO]


def test_a_batch_recipe_saying_auto_runs_version_2():
    from nocturne.batch import apply_recipe
    img = _stop_image()
    out = apply_recipe(img, Recipe([{"stage": "levels", "option": AUTO}]), Settings())
    np.testing.assert_array_equal(out.data, _v2(img))


def test_a_preset_saying_auto_plans_version_2():
    import nocturne.user_presets as up
    p = up.Preset(id="a", name="a", steps=({"stage": "levels", "option": AUTO},))
    assert up.preset_plan(p, Settings()).plan == [("levels", V2)]


# --- saved projects -------------------------------------------------------

def test_project_replays_every_levels_shape_pixel_exact(tmp_path):
    """Old "auto" replays version 1, new options replay as made — on a frame
    where the two versions differ, so a load that upgraded "auto" would show."""
    base = _stop_image()
    p = Project(base, str(tmp_path / "cache"))
    step = make_step("levels", Settings())
    options = [AUTO, V2_BLUE, MANUAL, (0.05, 1.0, 1.0)]
    for k, opt in enumerate(options):
        p.jump_back(0) if p.position else None
        p.run_step(step, opt)
        before = p.current().data.copy()
        save_project(p, str(tmp_path / "p.nocturne"))
        loaded = load_project(str(tmp_path / "p.nocturne"), str(tmp_path / f"re{k}"))
        np.testing.assert_array_equal(loaded.project.current().data, before)
        (name, got), = loaded.project.entries()
        assert name == "Levels"
        assert got == opt


def test_old_bundle_auto_is_version_1(tmp_path):
    base = _stop_image()
    p = Project(base, str(tmp_path / "cache"))
    p.run_step(make_step("levels", Settings()), AUTO)
    save_project(p, str(tmp_path / "old.nocturne"))
    loaded = load_project(str(tmp_path / "old.nocturne"), str(tmp_path / "re"))
    np.testing.assert_array_equal(loaded.project.current().data, _v1(base))


# --- provenance -----------------------------------------------------------

def _report(entries):
    from nocturne.core.provenance import build_report
    return build_report(entries, {}, app_version="t", date=datetime.date(2026, 10, 14))


def test_report_names_the_auto_stop_and_the_colours():
    r = _report([("Levels", V2_BLUE)])
    assert "Levels — auto (stops at the clipping limit), blue −0.015" in r
    assert "- one colour's black point: blue −0.015" in r
    assert "0.05% clipping warning" in r


def test_report_manual_levels_and_legacy_shapes():
    r = _report([("Levels", MANUAL)])
    assert "- black point: 0.07" in r and "red +0.012" in r
    r = _report([("Levels", new_levels_option(0.07, 1.0, 1.0))])
    assert "one colour" not in r                       # nothing moved: not mentioned
    r = _report([("Levels", (0.1, 1.0, 0.9))])
    assert "- black point: 0.1" in r and "- white point: 0.9" in r
    assert "Levels — auto\n" in _report([("Levels", AUTO)])


# --- one definition --------------------------------------------------------

def test_the_limit_and_the_slider_step_are_defined_once():
    from nocturne.core import inspect, levels
    from nocturne.ui import main_window, step_panels
    assert main_window._CLIP_AMBER_LO is inspect.CRUSHED_LIMIT
    assert step_panels.BLACK_STEPS is levels.BLACK_STEPS


def test_canvas_rgb8_is_the_core_cast():
    from nocturne.core.export import display_rgb8
    from nocturne.ui.preview import to_rgb8
    d = _stop_image().data.copy()
    d[0, 0] = np.nan
    for img in (AstroImage(d, is_linear=False), AstroImage(d[..., 1].copy(), is_linear=False)):
        np.testing.assert_array_equal(to_rgb8(img), display_rgb8(img))


def test_report_prints_levels_numbers_to_three_decimals():
    """Auto's continuous black reaches a manual dict when a midtone moves; it
    printed every digit of the float."""
    r = _report([("Levels", new_levels_option(0.071234567, 1.23456, 0.98765,
                                              (0.0, 0.0, -0.0151)))])
    for line in ("- black point: 0.071\n", "- midtones: 1.235\n", "- white point: 0.988\n",
                 "blue −0.015"):
        assert line in r, line
    r = _report([("Levels", new_levels_option(auto=True))])
    assert "- midtones: 1.000\n" in r and "- white point: 1.000\n" in r
