"""The closed preview runs with RELEASE_STAGE = "preview", set by the preview
commit only. Every surface that names the version must then say "(preview)",
and the public release that follows must reach the testers.

The committed stage is NOT asserted here: it is "beta" on main and "preview" on
a preview commit, and this file must pass on both.
"""
import pytest

pytest.importorskip("PySide6")

import nocturne
from nocturne import app_title, version_label
from nocturne.core.update_check import is_newer


@pytest.fixture
def preview(monkeypatch):
    monkeypatch.setattr(nocturne, "__version__", "0.57.0")
    monkeypatch.setattr(nocturne, "RELEASE_STAGE", "preview")


def test_the_version_label_names_the_preview(preview):
    assert version_label() == "0.57.0 (preview)"
    assert app_title() == "Nocturne 0.57.0 (preview)"


def test_the_window_title_names_the_preview_with_and_without_a_project(preview, qtbot, tmp_path):
    from nocturne.ui.main_window import MainWindow
    win = MainWindow(settings_path=str(tmp_path / "settings.json"), check_updates=False,
                     telemetry=False)
    qtbot.addWidget(win)
    assert "0.57.0 (preview)" in win.windowTitle(), win.windowTitle()   # as built
    win.setWindowTitle("")
    win._source_label = None
    win._update_title()                                                  # no project
    assert "0.57.0 (preview)" in win.windowTitle(), win.windowTitle()
    win._source_label = "M42"
    win._update_title()
    assert "0.57.0 (preview)" in win.windowTitle() and "M42" in win.windowTitle()


def test_the_about_dialog_names_the_preview(preview):
    from nocturne.ui.about import about_html
    assert "0.57.0 (preview)" in about_html()


def test_the_release_after_a_preview_is_offered_to_its_testers():
    """deploy.py refuses a release at or below the last preview's version, and
    this is why: the update check offers only a strictly newer one."""
    assert is_newer("0.57.1", "0.57.0") is True
    assert is_newer("v0.58.0", "0.57.0") is True
    assert is_newer("0.57.0", "0.57.0") is False
