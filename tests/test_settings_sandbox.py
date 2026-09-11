"""The suite must never write the developer's own settings file.

It did: `stack_dialog._toggle_hints` wrote the whole settings object to the real
~/.nocturne/settings.json regardless of the path the app was given, so a test
using a fresh `Settings()` wiped the configured GraXpert / RC-Astro / ASTAP
paths. Verified on 2026-09-11 — the file's mtime matched a full-suite run.
"""
import os

from nocturne.settings import resolve_settings_path


def test_the_default_path_is_sandboxed_during_tests():
    p = resolve_settings_path()
    home = os.path.expanduser("~")
    assert not p.startswith(os.path.join(home, ".nocturne")), (
        f"tests resolve to the real settings file: {p}")


def test_an_explicit_home_still_works(tmp_path):
    """test_settings_migration drives this argument deliberately; the sandbox
    must not break it."""
    p = resolve_settings_path(home=str(tmp_path))
    assert p == str(tmp_path / ".nocturne" / "settings.json")


def test_the_real_file_is_not_touched_by_saving_through_the_default_path(tmp_path):
    """The exact motion that caused the damage."""
    from nocturne.settings import Settings, save_settings

    real = os.path.join(os.path.expanduser("~"), ".nocturne", "settings.json")
    before = os.path.getmtime(real) if os.path.exists(real) else None
    save_settings(Settings(), resolve_settings_path())
    after = os.path.getmtime(real) if os.path.exists(real) else None
    assert before == after, "saving through the default path reached the real file"
