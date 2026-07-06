import pytest

pytest.importorskip("PySide6")
from nocturne.ui.about_dialog import AboutDialog  # noqa: E402


def test_about_dialog_shows_wordmark_and_body(qtbot):
    dlg = AboutDialog(html="<h1>Nocturne</h1><p>Andreas — not a developer</p>")
    qtbot.addWidget(dlg)
    assert "Nocturne" in dlg.wordmark.text()
    assert "Andreas" in dlg.body.text()


def test_about_dialog_defaults_to_real_content(qtbot):
    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    assert "Photon Donors" in dlg.body.text()   # pulled from about_html()
