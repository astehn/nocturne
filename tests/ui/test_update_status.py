"""Settings ▸ General shows what the update check found (Andreas, 2026-09-26).
The main window keeps the startup result and runs "Check now"; the suite never
goes online — the fetch is always injected."""
from tests.ui.test_main_window import _window


def test_the_startup_result_is_kept_for_settings(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)          # the suite constructs with the check off
    assert win._update_result == ("off", None)
    win._on_update_check(None)
    assert win._update_result == ("failed", "startup")
    win._on_update_check("v0.0.1")
    assert win._update_result == ("v0.0.1", "startup")
    assert not win._update_act.isVisible()


def test_check_now_updates_settings_and_the_toolbar_item(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.show(); qtbot.waitExposed(win)
    got = []
    win._check_for_update_now(got.append, fetch=lambda: "v99.0.0")
    qtbot.waitUntil(lambda: bool(got), timeout=3000)
    assert got == [("v99.0.0", "now")]
    assert win._update_act.isVisible(), "the toolbar item and Settings disagree"


def test_settings_opens_with_the_result_and_check_now_wired(qtbot, tmp_path, monkeypatch):
    from nocturne.ui import main_window as mw
    seen = {}
    real = mw.SettingsDialog

    class Spy(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            seen["dlg"] = self

        def exec(self):
            return 0

    monkeypatch.setattr(mw, "SettingsDialog", Spy)
    win = _window(qtbot, tmp_path)
    win._on_update_check("v0.0.1")
    win._open_settings()
    dlg = seen["dlg"]
    assert "latest version" in dlg.version_status.text()
    assert dlg.check_now_btn.isEnabled()
