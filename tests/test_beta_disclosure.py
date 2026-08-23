"""Every surface that names the app must say it is beta, and must say so by
deriving from ONE constant.

Until 2026-08-23 the word "beta" appeared nowhere in the package, the README or
the changelog — only on the website — so nothing on a user's own machine ever
told them. Andreas: "the main purpose is to make sure that no one misses that
this is beta software."

The drift guard at the bottom is the point of this file. Four surfaces spelling
out "beta" independently is four things to remember at the next release, and
this project's own notes record that in-app text goes stale every cycle and
nothing tests it.
"""
import pytest

pytest.importorskip("PySide6")

from pathlib import Path

import nocturne
from nocturne import BETA_NOTICE, RELEASE_STAGE, version_label


def test_version_label_carries_the_stage_and_drops_it_when_unset(monkeypatch):
    monkeypatch.setattr(nocturne, "RELEASE_STAGE", "beta")
    assert version_label() == f"{nocturne.__version__} (beta)"
    monkeypatch.setattr(nocturne, "RELEASE_STAGE", "")
    assert version_label() == nocturne.__version__


def test_the_notice_names_a_real_risk_rather_than_saying_expect_bugs():
    """A defect found the same day let Batch overwrite the master it was
    reading. Advice a user can act on beats a vague disclaimer."""
    assert "back" in BETA_NOTICE.lower()


def test_the_splash_shows_the_version_and_leaves_the_artwork_alone(qtbot):
    """The artwork already sets "Nocturne" and "Beta" in its own type, so the
    app draws only the number that changes between releases. An earlier version
    painted a second BETA heading and a notice line over the picture."""
    from nocturne.ui.splash import make_splash
    sp = make_splash(nocturne.__version__)
    qtbot.addWidget(sp)
    assert sp.caption == f"v{nocturne.__version__}"
    assert not hasattr(sp, "heading"), "the splash is drawing its own beta wording again"
    assert not hasattr(sp, "notice"), "the splash is drawing its own notice again"


def test_the_window_title_says_beta_with_and_without_a_project(qtbot, tmp_path):
    """The splash is gone in two seconds; the title bar is what actually makes
    it unmissable for the rest of the session."""
    from nocturne.ui.main_window import MainWindow
    win = MainWindow(settings_path=str(tmp_path / "settings.json"), check_updates=False)
    qtbot.addWidget(win)
    assert "beta" in win.windowTitle().lower(), win.windowTitle()
    assert nocturne.__version__ in win.windowTitle()

    win._source_label = "M42"
    win._update_title()
    assert "beta" in win.windowTitle().lower(), win.windowTitle()
    assert "M42" in win.windowTitle()


def test_the_about_dialog_says_beta():
    from nocturne.ui.about import about_html
    assert "beta" in about_html().lower()


def test_the_readme_says_beta_before_the_fold():
    """Someone arriving from GitHub decides what this is in the first screen."""
    readme = (Path(nocturne.__file__).resolve().parent.parent / "README.md").read_text()
    head = readme[:1200]
    assert "beta" in head.lower(), "README does not mention beta in its opening"


def test_no_surface_spells_out_beta_on_its_own(monkeypatch, qtbot, tmp_path):
    """THE DRIFT GUARD. Clear the single constant and every surface must stop
    claiming beta. Any surface that still says it has its own hardcoded copy,
    which is precisely what goes stale at the next release.
    """
    from nocturne.ui.about import about_html
    from nocturne.ui.main_window import MainWindow

    monkeypatch.setattr(nocturne, "RELEASE_STAGE", "")

    win = MainWindow(settings_path=str(tmp_path / "settings.json"), check_updates=False)
    qtbot.addWidget(win)
    assert "beta" not in win.windowTitle().lower(), (
        "the window title hardcodes 'beta' instead of deriving it")
    assert "beta" not in about_html().lower(), (
        "the About dialog hardcodes 'beta' instead of deriving it")
    # The splash is deliberately NOT in this guard: its beta wording is part of
    # the artwork and no code can clear it. See the note beside RELEASE_STAGE --
    # a stable release needs that image swapped by hand.
