from seestar_processor.settings import (
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
