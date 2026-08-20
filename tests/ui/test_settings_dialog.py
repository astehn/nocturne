from PySide6.QtWidgets import QPushButton
import pytest

pytest.importorskip("PySide6")
from nocturne.settings import Settings  # noqa: E402
from nocturne.ui.settings_dialog import SettingsDialog  # noqa: E402


def test_graxpert_test_button_shows_version(qtbot):
    dlg = SettingsDialog(Settings(graxpert_path="/x/graxpert"))
    qtbot.addWidget(dlg)
    dlg._probe_runner = lambda argv: (0, "GraXpert 3.1.0", "")
    dlg._test_graxpert()
    assert "✓" in dlg._gx_result.text()
    assert "GraXpert" in dlg._gx_result.text()


def test_rcastro_test_button_shows_failure(qtbot):
    dlg = SettingsDialog(Settings(rcastro_path="/x/rc-astro"))
    qtbot.addWidget(dlg)
    dlg._probe_runner = lambda argv: (1, "", "license expired")
    dlg._test_rcastro()
    assert "✗" in dlg._rc_result.text()
    assert "license expired" in dlg._rc_result.text()


def test_empty_path_reports_not_set(qtbot):
    dlg = SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._test_graxpert()
    assert "✗" in dlg._gx_result.text()


def test_result_settings_roundtrip(qtbot):
    dlg = SettingsDialog(Settings(graxpert_path="/a", rcastro_path="/b"))
    qtbot.addWidget(dlg)
    s = dlg.result_settings()
    assert s.graxpert_path == "/a" and s.rcastro_path == "/b"


def test_settings_dialog_round_trips_base_dir(qtbot, tmp_path):
    d = SettingsDialog(Settings(base_dir=str(tmp_path)))
    qtbot.addWidget(d)
    assert d._dir.text() == str(tmp_path)          # prefilled from settings
    d._dir.setText("/tmp/newbase")
    assert d.result_settings().base_dir == "/tmp/newbase"


def test_dialog_round_trips_denoise_engine(qtbot):
    d = SettingsDialog(Settings(denoise_engine="graxpert"))
    qtbot.addWidget(d)
    assert d.denoise_box.currentText() == "GraXpert"
    assert d.result_settings().denoise_engine == "graxpert"


def test_settings_dialog_round_trips_astap_path(qtbot):
    from nocturne.ui.settings_dialog import SettingsDialog
    from nocturne.settings import Settings
    dlg = SettingsDialog(Settings(astap_path="/opt/astap/astap"))
    qtbot.addWidget(dlg)
    assert dlg.result_settings().astap_path == "/opt/astap/astap"


def test_settings_dialog_has_tool_download_links(qtbot):
    from nocturne.ui.settings_dialog import SettingsDialog, DOWNLOAD_URLS
    from nocturne.settings import Settings
    assert set(DOWNLOAD_URLS) == {"graxpert", "rcastro", "astap"}
    assert all(u.startswith("https://") for u in DOWNLOAD_URLS.values())
    dlg = SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    labels = [w.text() for w in dlg.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)]
    assert any("astap.htm" in t for t in labels)          # ASTAP download link rendered


def test_browse_buttons_are_wired_and_do_not_raise(qtbot, monkeypatch):
    """Every Browse button in Settings was DEAD from 2026-08-15 (fd3a26b) to
    2026-08-20, shipped in v0.12.0 through v0.16.0.

    That commit gave `open_file`/`choose_folder` a required `caption`, updated
    every call site in the app, and missed the two here — which are lambdas, so
    nothing failed until a user clicked. The only way left to configure
    GraXpert, RC-Astro or ASTAP was to type an absolute path by hand, and on
    macOS that means finding the executable inside a .app bundle. It reached us
    as a real user's "setup is messy", which is the only reason we found it.

    Asserts the call SUCCEEDS with a caption, not merely that it is called:
    the defect was a TypeError raised inside a slot, where Qt prints to stderr
    and the button silently appears to do nothing.
    """
    from nocturne.ui import file_dialogs, settings_dialog
    from nocturne.settings import Settings

    seen = []
    monkeypatch.setattr(file_dialogs, "open_file",
                        lambda parent, caption, *a, **k: seen.append(("file", caption)) or "")
    monkeypatch.setattr(file_dialogs, "choose_folder",
                        lambda parent, caption, *a, **k: seen.append(("dir", caption)) or "")

    dlg = settings_dialog.SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    buttons = [b for b in dlg.findChildren(QPushButton) if b.text() == "Browse…"]
    assert len(buttons) >= 4, f"expected 3 tool paths + base folder, found {len(buttons)}"
    for b in buttons:
        b.click()                      # raised TypeError before the fix
    assert len(seen) == len(buttons)
    assert all(caption for _kind, caption in seen), "a Browse button passed an empty caption"
