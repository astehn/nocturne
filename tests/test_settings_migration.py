import json
import os
from nocturne.settings import resolve_settings_path


def test_resolve_creates_nocturne_dir(tmp_path):
    p = resolve_settings_path(home=str(tmp_path))
    assert p == os.path.join(str(tmp_path), ".nocturne", "settings.json")
    assert os.path.isdir(os.path.join(str(tmp_path), ".nocturne"))


def test_migrates_legacy_settings(tmp_path):
    legacy_dir = tmp_path / ".seestar_processor"
    legacy_dir.mkdir()
    (legacy_dir / "settings.json").write_text(json.dumps({"graxpert_path": "/gx"}))
    p = resolve_settings_path(home=str(tmp_path))
    assert json.loads(open(p).read())["graxpert_path"] == "/gx"


def test_does_not_overwrite_existing(tmp_path):
    (tmp_path / ".nocturne").mkdir()
    (tmp_path / ".nocturne" / "settings.json").write_text('{"graxpert_path": "/new"}')
    legacy_dir = tmp_path / ".seestar_processor"
    legacy_dir.mkdir()
    (legacy_dir / "settings.json").write_text('{"graxpert_path": "/old"}')
    p = resolve_settings_path(home=str(tmp_path))
    assert json.loads(open(p).read())["graxpert_path"] == "/new"
