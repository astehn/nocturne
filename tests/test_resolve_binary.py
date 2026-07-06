import os
import stat

from nocturne.settings import Settings, resolve_binary, graxpert_valid


def _make_app(tmp_path, app_name="GraXpert", exe_name="GraXpert"):
    app = tmp_path / f"{app_name}.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    exe = macos / exe_name
    exe.write_text("#!/bin/sh\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return str(app), str(exe)


def test_resolves_app_bundle_to_inner_binary(tmp_path):
    app, exe = _make_app(tmp_path)
    assert resolve_binary(app) == exe


def test_resolves_app_with_different_exe_name(tmp_path):
    app, exe = _make_app(tmp_path, app_name="GraXpert", exe_name="graxpert-bin")
    assert resolve_binary(app) == exe


def test_plain_path_passes_through(tmp_path):
    f = tmp_path / "rc-astro"
    f.write_text("x")
    assert resolve_binary(str(f)) == str(f)


def test_graxpert_valid_accepts_app_bundle(tmp_path):
    app, _ = _make_app(tmp_path)
    assert graxpert_valid(Settings(graxpert_path=app)) is True
