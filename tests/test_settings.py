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


def test_astap_path_round_trips(tmp_path):
    from nocturne.settings import Settings, save_settings, load_settings, astap_valid
    p = str(tmp_path / "settings.json")
    save_settings(Settings(astap_path="/opt/astap/astap"), p)
    assert load_settings(p).astap_path == "/opt/astap/astap"   # survives save+load


def test_astap_valid_checks_file(tmp_path):
    from nocturne.settings import Settings, astap_valid
    assert astap_valid(Settings(astap_path="")) is False
    real = tmp_path / "astap"; real.write_text("x")
    assert astap_valid(Settings(astap_path=str(real))) is True
    assert astap_valid(Settings(astap_path=str(tmp_path / "nope"))) is False


def test_help_expanded_defaults_true_and_round_trips(tmp_path):
    from nocturne.settings import Settings, save_settings, load_settings
    assert Settings().help_expanded is True                 # novice-first default
    p = tmp_path / "s.json"
    save_settings(Settings(help_expanded=False), str(p))
    assert load_settings(str(p)).help_expanded is False       # survives round-trip


def test_help_expanded_absent_in_old_file_defaults_true(tmp_path):
    import json
    from nocturne.settings import load_settings
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"base_dir": "/x"}))              # pre-feature settings.json
    assert load_settings(str(p)).help_expanded is True


def test_handle_field_roundtrips(tmp_path):
    from nocturne.settings import Settings, load_settings, save_settings
    p = tmp_path / "s.json"
    s = Settings(handle="andreas")
    save_settings(s, str(p))
    assert load_settings(str(p)).handle == "andreas"


def test_handle_defaults_blank(tmp_path):
    from nocturne.settings import load_settings
    assert load_settings(str(tmp_path / "missing.json")).handle == ""


def test_recent_projects_and_last_project_dir_round_trip(tmp_path):
    from nocturne.settings import Settings, save_settings, load_settings
    p = tmp_path / "s.json"
    s = Settings(recent_projects=["/a/one", "/a/two"], last_project_dir="/a")
    save_settings(s, str(p))
    loaded = load_settings(str(p))
    assert loaded.recent_projects == ["/a/one", "/a/two"]
    assert loaded.last_project_dir == "/a"


def test_recent_projects_and_last_project_dir_default_blank():
    from nocturne.settings import Settings
    s = Settings()
    assert s.recent_projects == []
    assert s.last_project_dir == ""


def test_recent_projects_absent_in_old_file_defaults_blank(tmp_path):
    import json
    from nocturne.settings import load_settings
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"base_dir": "/x"}))  # pre-feature settings.json
    loaded = load_settings(str(p))
    assert loaded.recent_projects == []
    assert loaded.last_project_dir == ""


def test_add_recent_project_dedups_prepends_and_caps():
    from nocturne.settings import Settings, add_recent_project
    s = Settings()
    for i in range(10):
        add_recent_project(s, f"/proj/{i}")
    assert len(s.recent_projects) == 8
    # most-recent-first: last added is at front
    assert s.recent_projects == [
        "/proj/9", "/proj/8", "/proj/7", "/proj/6",
        "/proj/5", "/proj/4", "/proj/3", "/proj/2",
    ]

    # re-adding an existing path moves it to front without duplicating
    add_recent_project(s, "/proj/5")
    assert s.recent_projects[0] == "/proj/5"
    assert s.recent_projects.count("/proj/5") == 1
    assert len(s.recent_projects) == 8
