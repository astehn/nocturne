from nocturne.core.crop import CropParams
from nocturne.core.color import ColorSettings
from nocturne.recipe import (
    Recipe, serialize_option, deserialize_option, recipe_from_entries,
    save_recipe, load_recipe,
)


def test_option_roundtrips():
    assert deserialize_option("stretch", serialize_option("stretch", 0.6)) == 0.6
    assert deserialize_option("noise_sharpen",
                              serialize_option("noise_sharpen", "medium")) == "medium"
    lv = deserialize_option("levels", serialize_option("levels", (0.1, 1.2, 0.9)))
    assert tuple(lv) == (0.1, 1.2, 0.9)
    cs = deserialize_option("color", serialize_option("color", ColorSettings(remove_green=True)))
    assert isinstance(cs, ColorSettings) and cs.remove_green is True


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
    rec = recipe_from_entries([("Color", None), ("Remove Green", "")])
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
    entries = [("Stretch", 0.5), ("Colourise", ""), ("Boost Red", ""), ("Colourise", "")]
    assert uncaptured_step_names(entries) == ["Colourise", "Boost Red"]
    assert uncaptured_step_names([("Stretch", 0.5), ("Levels", (0, 1, 1))]) == []
