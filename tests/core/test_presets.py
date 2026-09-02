from nocturne.core.presets import (PRESETS, PlateStyle, preset_by_name,
                                   style_from_dict, style_to_dict)


def test_the_five_shipped_presets_are_all_there():
    names = [p.name for p in PRESETS]
    assert names == ["Scrim", "Plate", "Keyline", "Matte", "Data"]


def test_scrim_is_the_default_and_uses_the_warm_off_white():
    s = PRESETS[0]
    assert s.treatment == "scrim"
    assert s.colour == "#F0E9E2"


def test_data_reproduces_todays_look():
    """It exists so nothing regresses: an existing user's settings map onto it
    and their exports are unchanged."""
    s = preset_by_name("Data")
    assert s.treatment == "band"
    assert s.colour == "#ffffff"
    assert s.anchor == "bottom-left"
    assert s.rule is False and s.keyline is False


def test_data_carries_the_old_renderers_actual_numbers():
    """The claim above is only worth anything if the numbers are the real ones,
    not numbers that look plausible. These four are read from the code the Data
    preset promises to reproduce."""
    from nocturne.core.share import DEFAULT_CAPTION_COLOUR, DEFAULT_CAPTION_SIZE
    from nocturne.ui.share_render import FONT_FRAC, PAD_FRAC
    s = preset_by_name("Data")
    assert s.size_title == FONT_FRAC == DEFAULT_CAPTION_SIZE
    assert s.colour == DEFAULT_CAPTION_COLOUR
    assert s.margin == PAD_FRAC
    # One line at one size: the old renderer had no title/sub/credit hierarchy.
    assert s.size_sub == s.size_credit == s.size_title
    assert s.tracking_title == s.tracking_sub == 0


def test_every_preset_names_a_family_we_actually_bundle():
    from nocturne.ui.fonts import PLATE_FAMILIES
    bundled = {fam for _l, fam in PLATE_FAMILIES}
    for p in PRESETS:
        assert p.family in bundled, f"{p.name} asks for {p.family}, which we do not ship"


def test_a_style_round_trips_through_a_dict():
    for p in PRESETS:
        assert style_from_dict(style_to_dict(p)) == p


def test_an_unknown_key_in_stored_json_does_not_crash_the_load():
    """Settings written by a newer build must not brick an older one."""
    d = style_to_dict(PRESETS[0]); d["invented_later"] = 7
    assert style_from_dict(d).name == "Scrim"


def test_a_missing_key_falls_back_rather_than_raising():
    d = style_to_dict(PRESETS[0]); del d["margin"]
    assert style_from_dict(d).margin > 0


def test_an_unrecognised_preset_name_falls_back_to_the_default():
    """A settings file naming a preset this build does not have must not stop
    Share from opening."""
    assert preset_by_name("Invented By A Newer Build") is PRESETS[0]
    assert preset_by_name("") is PRESETS[0]


def test_a_dict_naming_an_unknown_preset_still_keeps_its_own_values():
    """The fallback supplies the DEFAULTS for missing keys; it must not
    overwrite the keys the file actually carried."""
    d = style_to_dict(preset_by_name("Matte")); d["name"] = "A Look He Saved"
    s = style_from_dict(d)
    assert s.name == "A Look He Saved"
    assert s.treatment == "matte" and s.margin == 0.075


def test_the_module_is_pure():
    """core/ must not import Qt. share.py broke this once, mid-file at line 57,
    which is exactly why it went unnoticed."""
    import nocturne.core.presets as m
    assert "PySide6" not in open(m.__file__).read()
