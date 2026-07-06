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
