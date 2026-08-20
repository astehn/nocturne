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


def test_annotation_settings_default():
    from nocturne.settings import Settings
    s = Settings()
    assert s.annotation_layers == {
        "objects": True, "stars": True, "grid": False,
        "compass": True, "scale": True, "by_type": False,
    }
    assert s.annotation_density == "balanced"


def test_annotation_settings_default_dict_is_not_a_shared_mutable():
    # field(default_factory=...) is required here -- a mutable dict default
    # would be shared across every Settings() instance.
    from nocturne.settings import Settings
    a, b = Settings(), Settings()
    a.annotation_layers["grid"] = True
    assert b.annotation_layers["grid"] is False


def test_annotation_settings_round_trip(tmp_path):
    # load_settings lists every field explicitly (no **data), so a field only
    # added to the dataclass would save via asdict but silently never load
    # back -- this test fails loudly if that trap is hit.
    from nocturne.settings import Settings, save_settings, load_settings
    p = tmp_path / "s.json"
    layers = {"objects": False, "stars": False, "grid": True,
              "compass": False, "scale": True, "by_type": True}
    save_settings(Settings(annotation_layers=layers, annotation_density="all"), str(p))
    loaded = load_settings(str(p))
    assert loaded.annotation_layers == layers
    assert loaded.annotation_density == "all"


def test_annotation_settings_absent_in_old_file_defaults(tmp_path):
    import json
    from nocturne.settings import load_settings
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"base_dir": "/x"}))  # pre-feature settings.json
    loaded = load_settings(str(p))
    assert loaded.annotation_layers == {
        "objects": True, "stars": True, "grid": False,
        "compass": True, "scale": True, "by_type": False,
    }
    assert loaded.annotation_density == "balanced"


# --- tool auto-detection -------------------------------------------------
# Reached us as a real user's "setup is messy, especially configuring RC-Astro,
# GraXpert and ASTAP" (2026-08-20). The Browse buttons were also dead (b4314fa);
# this is the other half — the tools install to predictable places, so in the
# common case nobody should have to configure anything at all.

def _fake_tools(tmp_path):
    """A macOS-shaped layout: two .app bundles and one bare CLI binary."""
    gx = tmp_path / "GraXpert.app" / "Contents" / "MacOS"
    gx.mkdir(parents=True)
    (gx / "GraXpert").write_text("#!/bin/sh\n")
    astap = tmp_path / "ASTAP.app" / "Contents" / "MacOS"
    astap.mkdir(parents=True)
    (astap / "ASTAP").write_text("#!/bin/sh\n")
    rc = tmp_path / "RC-Astro" / "CLI"
    rc.mkdir(parents=True)
    (rc / "rc-astro").write_text("#!/bin/sh\n")
    return {
        "graxpert_path": [str(tmp_path / "GraXpert.app")],
        "rcastro_path": [str(tmp_path / "RC-Astro" / "CLI" / "rc-astro")],
        "astap_path": [str(tmp_path / "ASTAP.app")],
    }


def test_detects_each_tool_at_its_default_location(tmp_path):
    from nocturne.settings import Settings, detect_tool_paths
    found = detect_tool_paths(Settings(), candidates=_fake_tools(tmp_path))
    assert set(found) == {"graxpert_path", "rcastro_path", "astap_path"}
    # a .app is offered as the BUNDLE; resolve_binary already handles the rest,
    # which is why no user ever needed Show Package Contents
    assert found["graxpert_path"].endswith("GraXpert.app")


def test_detection_never_overwrites_a_configured_path(tmp_path):
    """The one thing auto-detection must not do is second-guess the user.

    Assert UNCHANGED: someone with a tool installed somewhere unusual has
    already paid the cost of finding it, and silently replacing their path with
    a default would be worse than never detecting anything.
    """
    from nocturne.settings import Settings, detect_tool_paths
    mine = "/somewhere/else/graxpert"
    found = detect_tool_paths(Settings(graxpert_path=mine),
                              candidates=_fake_tools(tmp_path))
    assert "graxpert_path" not in found
    assert Settings(graxpert_path=mine).graxpert_path == mine


def test_detects_nothing_when_nothing_is_installed(tmp_path):
    from nocturne.settings import Settings, detect_tool_paths
    absent = {k: [str(tmp_path / "nope")] for k in
              ("graxpert_path", "rcastro_path", "astap_path")}
    assert detect_tool_paths(Settings(), candidates=absent) == {}


def test_autoconfigure_writes_the_found_paths_to_disk(tmp_path):
    from nocturne.settings import Settings, autoconfigure_tools, load_settings, save_settings
    path = str(tmp_path / "settings.json")
    save_settings(Settings(), path)
    filled = autoconfigure_tools(path, candidates=_fake_tools(tmp_path))
    assert set(filled) == {"graxpert_path", "rcastro_path", "astap_path"}
    assert load_settings(path).graxpert_path.endswith("GraXpert.app")


def test_autoconfigure_is_a_no_op_when_everything_is_already_set(tmp_path):
    from nocturne.settings import Settings, autoconfigure_tools, load_settings, save_settings
    path = str(tmp_path / "settings.json")
    save_settings(Settings(graxpert_path="/a", rcastro_path="/b", astap_path="/c"), path)
    assert autoconfigure_tools(path, candidates=_fake_tools(tmp_path)) == []
    assert load_settings(path).graxpert_path == "/a"


def test_startup_actually_calls_autoconfigure():
    """Pins the WIRING, not just the helper.

    The dead Browse buttons were a fully-written handler that nothing ever
    invoked, and the freeze_support bug was the same shape. A tested function
    nobody calls is exactly as useless. Reads the source rather than running
    main(), which would need a QApplication.
    """
    import ast, inspect
    from nocturne import __main__ as entry
    tree = ast.parse(inspect.getsource(entry))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "main")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "autoconfigure_tools" in called
