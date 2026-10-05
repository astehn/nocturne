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


# --- the editor shows what was applied (found 2026-10-05) ---------------------
# The panel was built at the identity curve every time, and the per-channel
# slots lived in a window field only Open Image cleared. So a revisit showed a
# straight line and a nudge replaced the applied RGB curve; a reopened project
# lost every slot on the next Apply; and opening a project kept the previous
# picture's R/G/B curves, applied unseen on the next Apply.

RGB = [(0.0, 0.0), (0.25, 0.2), (0.75, 0.8), (1.0, 1.0)]
R = [(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)]


def _with_curves(qtbot, tmp_path):
    from tests.ui.test_main_window import _make_fits, _window
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.3, "linked": True})
    win._go_to_id("curves")
    win._on_curves_dialog_apply({"rgb/all": RGB, "r/all": R})
    win.apply_current(win._panel.commit_option())
    assert set(win._committed_option("curves")) == {"rgb/all", "r/all"}, "fixture"
    return win


def test_a_revisit_shows_the_applied_curve_and_reads_unchanged(qtbot, tmp_path):
    win = _with_curves(qtbot, tmp_path)
    win._go_to_id("stretch")
    win._go_to_id("curves")
    assert win._panel.curve_editor.points() == RGB
    assert win._curve_matrix == {"r/all": R}
    assert not win._has_pending(), "showing what was applied is not an edit"


def test_a_reopened_project_keeps_every_slot_through_a_nudge(qtbot, tmp_path):
    from nocturne.history.project_store import save_project
    from tests.ui.test_main_window import _window
    win = _with_curves(qtbot, tmp_path)
    path = str(tmp_path / "p.nocturne")
    save_project(win.project, path, source_label="stack.fits")
    (tmp_path / "w2").mkdir()
    win2 = _window(qtbot, tmp_path / "w2")
    win2._open_project(path)
    win2._go_to_id("curves")
    assert win2._panel.curve_editor.points() == RGB
    assert not win2._has_pending()
    nudged = [(0.0, 0.0), (0.25, 0.22), (0.75, 0.8), (1.0, 1.0)]
    win2._panel.curve_editor.set_points(nudged)
    win2.apply_current(win2._panel.commit_option())
    assert win2._committed_option("curves") == {"rgb/all": nudged, "r/all": R}


def test_opening_a_project_does_not_carry_another_pictures_curves(qtbot, tmp_path, monkeypatch):
    from nocturne.history.project_store import save_project
    from tests.ui.test_main_window import _make_fits
    win = _with_curves(qtbot, tmp_path)
    (tmp_path / "b").mkdir()
    win.open_fits(_make_fits(tmp_path / "b"))
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.3, "linked": True})
    plain = str(tmp_path / "plain.nocturne")
    save_project(win.project, plain, source_label="b.fits")
    (tmp_path / "c").mkdir()
    win.open_fits(_make_fits(tmp_path / "c"))    # back to a picture...
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.3, "linked": True})
    win._go_to_id("curves")
    win._on_curves_dialog_apply({"rgb/all": RGB, "r/all": R})   # ...with R set
    monkeypatch.setattr(win, "_ask_pending", lambda *a, **k: "discard")
    win._open_project(plain)
    assert [n for n, _ in win.project.entries()] == ["Stretch"], "the plain project"
    win._go_to_id("curves")
    assert win._curve_matrix == {}
    assert win._panel.curve_editor.points() == [(0.0, 0.0), (1.0, 1.0)]
