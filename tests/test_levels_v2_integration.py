"""Every place "auto" Levels runs now runs the CURRENT Auto (spec 2026-10-14 A,
last bullet): Auto Enhance, a recipe in Batch, a user preset. Each on the fixture
where version 2 stops below the candidate, so a path still running version 1
gives a different picture and fails."""
import numpy as np
import pytest

from nocturne.batch import apply_recipe
from nocturne.core.auto_enhance import AUTO_LEVELS, run_auto_plan
from nocturne.core.levels import AUTO, apply_levels, auto_black, new_levels_option
from nocturne.recipe import Recipe, load_recipe, save_recipe
from nocturne.settings import Settings
from nocturne.user_presets import Preset, preset_plan
from tests.core.test_levels_clip_aware import _stop_image


@pytest.fixture(scope="module")
def stop():
    img = _stop_image()
    decided = auto_black(img)
    assert decided.stopped and decided.black < decided.candidate, "fixture must stop"
    v2 = apply_levels(img, decided.black, 1.0, 1.0)
    v1 = apply_levels(img, decided.candidate, 1.0, 1.0)
    assert not np.array_equal(v1.data, v2.data), "fixture cannot tell v1 from v2"
    return img, decided, v2


def test_auto_enhance_runs_and_records_version_2(stop):
    img, decided, v2 = stop
    run = run_auto_plan(img, [("levels", AUTO_LEVELS)], Settings())
    (name, option, out), = run.results
    assert name == "Levels" and option == new_levels_option(auto=True)
    np.testing.assert_array_equal(out.data, v2.data)
    # The numbers the log line reads: where it stopped, and the unlimited black.
    (res,) = run.resolved
    assert res.auto == decided


def test_a_recipe_saying_auto_runs_version_2_in_batch(stop, tmp_path):
    """A recipe written before this change stores the bare "auto": it means
    "re-derive on this image", so it gets what a fresh Auto press gives."""
    img, _decided, v2 = stop
    for option in (AUTO, new_levels_option(auto=True)):
        path = str(tmp_path / "r.json")
        save_recipe(Recipe(steps=[{"stage": "levels", "option": option}]), path)
        out = apply_recipe(img, load_recipe(path), Settings())
        np.testing.assert_array_equal(out.data, v2.data)


def test_a_preset_saying_auto_runs_version_2(stop):
    img, decided, v2 = stop
    p = Preset(id="x", name="x", steps=({"stage": "levels", "option": AUTO},),
               data_type="broadband")
    plan = preset_plan(p, Settings())
    assert plan.plan == [("levels", new_levels_option(auto=True))]
    run = run_auto_plan(img, plan.plan, Settings(), levels_auto=False)
    (name, option, out), = run.results
    assert option == new_levels_option(auto=True)
    np.testing.assert_array_equal(out.data, v2.data)
    assert run.resolved[0].auto == decided


def test_resolved_is_aligned_with_results_and_none_off_levels(stop):
    img, _decided, _v2 = stop
    run = run_auto_plan(img, [("enhance", "Vibrance"), ("levels", AUTO_LEVELS)], Settings())
    assert len(run.resolved) == len(run.results) == 2
    assert run.resolved[0] is None and run.resolved[1].auto.stopped
