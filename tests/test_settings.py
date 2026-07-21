from nocturne.settings import (
    Settings, load_settings, save_settings, graxpert_valid,
)


def test_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    save_settings(Settings(graxpert_path="/x/graxpert"), str(p))
    loaded = load_settings(str(p))
    assert loaded.graxpert_path == "/x/graxpert"


def test_missing_file_returns_defaults(tmp_path):
    s = load_settings(str(tmp_path / "nope.json"))
    assert s.graxpert_path == ""


def test_graxpert_valid(tmp_path):
    f = tmp_path / "graxpert"
    f.write_text("#!/bin/sh\n")
    assert graxpert_valid(Settings(graxpert_path=str(f))) is True
    assert graxpert_valid(Settings(graxpert_path="/nope")) is False


def test_start_dir_returns_existing_dir(tmp_path):
    from nocturne.settings import start_dir
    assert start_dir(str(tmp_path)) == str(tmp_path)


def test_start_dir_empty_or_missing_returns_blank():
    from nocturne.settings import start_dir
    assert start_dir("") == ""
    assert start_dir("   ") == ""
    assert start_dir("/no/such/path/nocturne") == ""


def test_settings_round_trips_base_dir(tmp_path):
    from nocturne.settings import Settings, save_settings, load_settings
    p = str(tmp_path / "settings.json")
    save_settings(Settings(base_dir=str(tmp_path)), p)
    assert load_settings(p).base_dir == str(tmp_path)


def test_load_settings_defaults_base_dir_blank(tmp_path):
    import json
    from nocturne.settings import load_settings
    p = str(tmp_path / "s.json")
    with open(p, "w") as f:
        json.dump({"graxpert_path": "", "rcastro_path": ""}, f)   # no base_dir key
    assert load_settings(p).base_dir == ""


def test_denoise_engine_persists(tmp_path):
    from nocturne.settings import Settings, save_settings, load_settings
    p = str(tmp_path / "s.json")
    save_settings(Settings(graxpert_path="g", rcastro_path="r", base_dir="d",
                           denoise_engine="graxpert"), p)
    assert load_settings(p).denoise_engine == "graxpert"


def test_denoise_engine_defaults_to_rcastro(tmp_path):
    from nocturne.settings import Settings, save_settings, load_settings
    p = str(tmp_path / "s.json")
    save_settings(Settings(), p)                 # no engine set
    assert load_settings(p).denoise_engine == "rcastro"
