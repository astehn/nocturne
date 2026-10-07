"""What the app says about the external tools matches what the code does
(checked 2026-10-07 while building the website's tools table)."""
from __future__ import annotations

from nocturne.ui import main_window
from nocturne.ui.help_content import TOPICS


def test_a_starnet2_split_is_named_not_called_free(qtbot, tmp_path):
    from tests.ui.test_main_window import _window, _make_fits
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    note = win._split_note("StarNet2")
    assert note == "Separated with StarNet2."
    assert note != win._split_note("free")


def test_the_free_note_names_the_free_tool_too(qtbot):
    assert "StarNet2" in main_window._FREE_STAR_NOTE


def test_saturation_does_not_say_free_when_starnet2_is_set(qtbot, tmp_path, monkeypatch):
    """The note before the split keyed on RC-Astro alone, so a StarNet2 user
    was told "Using free star detection" for a split StarNet2 then did."""
    from tests.ui.test_main_window import _window, _make_fits
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    monkeypatch.setattr(main_window, "rcastro_valid", lambda s: False)
    monkeypatch.setattr(main_window, "preferred_splitter", lambda s: object())
    monkeypatch.setattr(win, "_prepare_saturation", lambda base: None)
    win._go_to_id("saturation")
    assert win._panel.neb_status.text() != main_window._FREE_STAR_NOTE


def test_a_broken_starnet2_path_is_reported(qtbot, tmp_path):
    from tests.ui.test_main_window import _window
    win = _window(qtbot, tmp_path)
    win.settings.starnet_path = str(tmp_path / "gone" / "starnet2")
    assert "StarNet2" in win._broken_tools()


def test_the_tools_help_lists_starnet2_on_its_own_and_the_export_as_starx_only():
    topic = TOPICS["tools"]
    body = topic.body
    rc = body.split("<h4>RC-Astro", 1)[1].split("<h4>", 1)[0]
    assert "StarNet2" in topic.title
    assert "<h4>StarNet2 (free, optional)</h4>" in body
    assert "<b>StarNet2</b>" not in rc, "StarNet2 is not an RC-Astro product"
    assert "starless+stars export" in rc


def test_settings_says_free_or_paid_and_what_graxpert_is_needed_for(qtbot):
    from PySide6.QtWidgets import QLabel
    from nocturne.settings import Settings
    from nocturne.ui.settings_dialog import SettingsDialog
    d = SettingsDialog(Settings())
    qtbot.addWidget(d)
    labels = {w.text() for w in d.findChildren(QLabel)}
    for text in ("GraXpert (free, needed for Background)", "RC-Astro (paid, optional)",
                 "StarNet2 (free, optional)", "ASTAP (free, optional)"):
        assert text in labels, text
