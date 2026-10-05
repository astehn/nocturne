"""A Curves step survives a save and a reopen.

Since the large Curves editor (2026-09-05) the option is a MATRIX — a dict of
channel/target slots — but serialize_option/deserialize_option still treated
it as a bare list of points. A project with Curves saved without complaint
(the dict passed through untouched) and then could not be reopened: "too many
values to unpack". Save Recipe raised on the same conversion. Found
2026-10-05 while removing Linear Denoise. The data on disk was always intact,
so the fix also opens every project already saved this way.
"""
import json

import numpy as np

from nocturne.core.curves import curve_key, normalize_curves
from nocturne.recipe import (deserialize_option, load_recipe, recipe_from_entries,
                             save_recipe, serialize_option)

MATRIX = {curve_key("rgb", "all"): [(0.0, 0.0), (0.25, 0.2), (0.75, 0.8), (1.0, 1.0)],
          curve_key("r", "all"): [(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)]}


def test_a_matrix_survives_json_both_ways():
    ser = serialize_option("curves", MATRIX)
    back = deserialize_option("curves", json.loads(json.dumps(ser)))
    assert back == normalize_curves(MATRIX)
    assert set(back) == {"rgb/all", "r/all"}, "the second channel must not be lost"


def test_a_bare_list_still_means_the_rgb_curve():
    """Projects and recipes from before 2026-09-05 stored a bare list."""
    legacy = [[0.0, 0.0], [0.5, 0.6], [1.0, 1.0]]
    assert deserialize_option("curves", legacy) == {"rgb/all": [(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)]}


def test_a_project_with_curves_reopens_with_the_same_picture(qtbot, tmp_path):
    from nocturne.history.project_store import load_project, save_project
    from tests.ui.test_main_window import _make_fits, _window
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.3, "linked": True})
    win._go_to_id("curves")
    win._curve_matrix = {curve_key("r", "all"): MATRIX[curve_key("r", "all")]}
    win.apply_current(MATRIX[curve_key("rgb", "all")])
    assert [n for n, _ in win.project.entries()][-1] == "Curves", "fixture"
    saved = win.project.current().data.copy()
    path = str(tmp_path / "with-curves.nocturne")
    save_project(win.project, path, source_label="stack.fits")

    loaded = load_project(path, str(tmp_path / "cache"))

    assert [n for n, _ in loaded.project.entries()] == [n for n, _ in win.project.entries()]
    assert np.array_equal(loaded.project.current().data, saved), "the picture must come back unchanged"
    assert set(normalize_curves(loaded.project.entries()[-1][1])) == {"rgb/all", "r/all"}


def test_a_recipe_with_curves_saves_and_loads(tmp_path):
    entries = [("Curves", normalize_curves(MATRIX))]
    path = str(tmp_path / "r.json")
    save_recipe(recipe_from_entries(entries), path)
    step = load_recipe(path).steps[0]
    assert step["stage"] == "curves"
    assert normalize_curves(deserialize_option("curves", step["option"])) == normalize_curves(MATRIX)
