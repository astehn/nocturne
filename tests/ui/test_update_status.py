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


def test_check_now_reports_to_settings(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    got = []
    win._check_for_update_now(got.append, fetch=lambda: "v99.0.0")
    qtbot.waitUntil(lambda: bool(got), timeout=3000)
    assert got == [("v99.0.0", "now")]
    assert win._update_result == ("v99.0.0", "now")


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


def test_a_dialog_opened_while_checking_gets_the_answer(qtbot, tmp_path):
    """Opened before the startup check landed, it said 'Checking…' for ever."""
    from nocturne.settings import Settings
    from nocturne.ui.settings_dialog import SettingsDialog
    win = _window(qtbot, tmp_path)
    win._update_result = ("pending", None)
    dlg = SettingsDialog(Settings(), win, update_result=win._update_result)
    win._settings_dlg = dlg
    assert "checking" in dlg.version_status.text().lower()
    win._on_update_check("v0.0.1")
    assert "latest version" in dlg.version_status.text()


def test_a_late_startup_failure_does_not_overwrite_check_now(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    got = []
    win._check_for_update_now(got.append, fetch=lambda: "v0.0.1")
    qtbot.waitUntil(lambda: bool(got), timeout=3000)
    win._on_update_check(None)                      # the slow startup request times out
    assert win._update_result == ("v0.0.1", "now")


# --- A new version is announced ONCE, quietly (Andreas, 2026-09-26 14:33):
# an amber activity line, and a line on the welcome screen — no pop-up.

def _notices(win):
    return [t for t in win.activity.entries("notice")]


def test_a_new_version_is_announced_once(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._on_update_check("v99.0.0")
    assert any("99.0.0 is available" in t for t in _notices(win))
    assert "99.0.0" in win._welcome.update_note.text()
    assert win.settings.update_notified_version == "v99.0.0"
    n = len(_notices(win))
    win._on_update_check("v99.0.0")                 # the next launch finds it again
    assert len(_notices(win)) == n, "told twice about the same version"


def test_a_version_already_announced_is_not_repeated_on_a_new_launch(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.settings.update_notified_version = "v99.0.0"
    win._on_update_check("v99.0.0")
    assert not any("is available" in t for t in _notices(win))
    assert win._welcome.update_note.text() == ""
    win._on_update_check("v99.1.0")                 # the next release gets its own mention
    assert any("99.1.0 is available" in t for t in _notices(win))


def test_current_or_failed_announces_nothing(qtbot, tmp_path):
    from nocturne import __version__
    win = _window(qtbot, tmp_path)
    win._on_update_check(__version__)
    win._on_update_check(None)
    win._on_update_check("garbled")
    assert not any("is available" in t for t in _notices(win))
    assert win.settings.update_notified_version == ""


def test_the_welcome_note_never_moves_the_welcome_screen(qtbot, tmp_path):
    """It lands seconds after launch; its room is reserved so the buttons stay put."""
    from PySide6.QtCore import QPoint
    win = _window(qtbot, tmp_path)
    win.resize(1400, 900); win.show(); qtbot.waitExposed(win)
    before = win._welcome.open_btn.mapTo(win, QPoint(0, 0))
    win._on_update_check("v99.0.0"); qtbot.wait(20)
    assert win._welcome.open_btn.mapTo(win, QPoint(0, 0)) == before


def test_the_same_release_with_or_without_v_is_announced_once(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._on_update_check("v99.0.0")
    n = len(_notices(win))
    win._on_update_check("99.0.0")
    assert len(_notices(win)) == n


def test_the_welcome_note_wraps_on_a_narrow_window(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert win._welcome.update_note.wordWrap()
