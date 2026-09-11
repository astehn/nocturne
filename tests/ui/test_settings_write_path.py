"""A dialog persists through the path the app was GIVEN.

`stack_dialog._toggle_hints` wrote the whole settings object to
`resolve_settings_path()` — the real ~/.nocturne/settings.json — whatever path
the app was actually launched with. In the suite that meant a fresh, empty
`Settings()` landing on the developer's file and wiping their configured
GraXpert / RC-Astro / ASTAP paths, which happened on 2026-09-11.

It is latent in production too: any second profile, or a `--settings` option,
would silently write to the default file instead of the one in use.
"""
import json
import os

from nocturne.settings import Settings, load_settings


def test_toggling_the_stack_hints_writes_where_the_app_was_told_to(qtbot, tmp_path):
    from tests.ui.test_main_window import _window

    win = _window(qtbot, tmp_path)
    win.settings.graxpert_path = "/somewhere/GraXpert.app"
    path = win._settings_path

    from nocturne.ui.stack_dialog import StackDialog
    dlg = StackDialog(win.settings, win, on_settings_changed=win._save_settings)
    qtbot.addWidget(dlg)
    before = win.settings.help_expanded
    dlg._toggle_hints()

    assert os.path.exists(path), "the preference was not written to the app's own file"
    saved = load_settings(path)
    assert saved.help_expanded != before, "the preference did not persist"
    assert saved.graxpert_path == "/somewhere/GraXpert.app", (
        "the write clobbered the rest of the settings")


def test_no_module_saves_to_a_globally_resolved_path():
    """The guard: reaching for the default path to WRITE is the bug. Reading it
    once at startup is fine, which is why __main__ is allowed."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2] / "nocturne"
    offenders = []
    for p in root.rglob("*.py"):
        if p.name == "__main__.py" or p.name == "settings.py":
            continue
        src = p.read_text(encoding="utf-8")
        for m in re.finditer(r"save_settings\([^)]*resolve_settings_path\(\)", src):
            line = src[:m.start()].count("\n") + 1
            offenders.append(f"{p.name}:{line}")
    assert not offenders, (
        "saves to the globally-resolved settings path, ignoring the app's own: "
        + ", ".join(offenders))
