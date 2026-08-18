import pytest
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
    """Saved Projects reproduce pixel-exactly, so every parameter must persist.

    `serialize_option` writes an explicit dict for the colour step rather than
    dumping the dataclass, so a new field is silently dropped unless it is added
    here — the tint would have been lost on save and the project would have
    reproduced with different colour. The deserialiser is generic (it filters by
    dataclass field names) so it needed no change; only the writer did.
    """
    from nocturne.core.color import ColorSettings
    from nocturne.recipe import deserialize_option, serialize_option

    original = ColorSettings(method="sky", tint=-0.4, temperature=0.25,
                             remove_green=True, neutralize_background=False)
    restored = deserialize_option("color", serialize_option("color", original))

    assert restored.tint == pytest.approx(-0.4)
    assert restored.temperature == pytest.approx(0.25)
    assert restored.method == "sky"
    assert restored.remove_green is True
    assert restored.neutralize_background is False


def test_a_recipe_written_before_tint_existed_still_loads():
    """Old recipes have no tint key. They must load as 'no change', not crash."""
    from nocturne.recipe import deserialize_option
    old = {"neutralize_background": True, "remove_green": False, "method": "sky"}
    restored = deserialize_option("color", old)
    assert restored.tint == 0.0 and restored.temperature == 0.0
