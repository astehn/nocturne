import pytest

pytest.importorskip("PySide6")
from nocturne.ui.welcome import WelcomeScreen  # noqa: E402


def test_welcome_buttons_invoke_callbacks(qtbot):
    calls = []
    w = WelcomeScreen(lambda: calls.append("open"), lambda: calls.append("stack"))
    qtbot.addWidget(w)
    w.open_btn.click()
    w.stack_btn.click()
    assert calls == ["open", "stack"]


def test_every_way_in_is_on_the_start_page(qtbot):
    """Andreas, 2026-10-05: it offered two ways in where there are four."""
    calls = []
    w = WelcomeScreen(lambda: calls.append("open"), lambda: calls.append("stack"),
                      on_open_project=lambda: calls.append("project"),
                      on_haoiii=lambda: calls.append("haoiii"))
    qtbot.addWidget(w)
    for b in (w.open_btn, w.open_project_btn, w.haoiii_btn, w.stack_btn):
        b.click()
    assert calls == ["open", "project", "haoiii", "stack"]
    assert w.stack_btn.objectName() == "primary", "Stack stays the one green button"
    assert [b.objectName() for b in (w.open_btn, w.open_project_btn, w.haoiii_btn)] == ["", "", ""]


def test_recent_projects_are_listed_and_open(qtbot, tmp_path):
    paths = []
    for name in ("M 31.nocturne", "NGC 7000.nocturne"):
        p = tmp_path / name
        p.write_text("x")
        paths.append(str(p))
    gone = str(tmp_path / "moved away.nocturne")
    opened = []
    w = WelcomeScreen(lambda: None, lambda: None, on_recent=opened.append,
                      recent=lambda: [paths[0], gone, paths[1]])
    qtbot.addWidget(w)
    assert [b.text() for b in w.recent_buttons] == ["M 31", "NGC 7000"], "a missing file is not offered"
    assert w.recent_title.isVisibleTo(w)
    w.recent_buttons[1].click()
    assert opened == [paths[1]]


def test_no_projects_shows_the_get_started_panel(qtbot):
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: [])
    qtbot.addWidget(w)
    assert w.recent_buttons == []
    assert w.recent_title.text() == "GET STARTED"
    assert w.empty_panel.isVisibleTo(w) and not w._grid_box.isVisibleTo(w)


def test_at_most_six_are_shown_and_the_list_follows_the_settings(qtbot, tmp_path):
    from nocturne.ui.welcome import RECENT_SHOWN
    files = []
    for i in range(8):
        p = tmp_path / f"p{i}.nocturne"
        p.write_text("x")
        files.append(str(p))
    source = {"list": files[:2]}
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: source["list"])
    qtbot.addWidget(w)
    assert len(w.recent_buttons) == 2
    source["list"] = files
    w.refresh_recent()
    assert len(w.recent_buttons) == RECENT_SHOWN == 6


def test_the_buttons_stay_put_whatever_the_list_holds(qtbot, tmp_path):
    files = []
    for i in range(4):
        p = tmp_path / f"p{i}.nocturne"
        p.write_text("x")
        files.append(str(p))
    source = {"list": []}
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: source["list"])
    qtbot.addWidget(w)
    w.resize(1200, 760)
    w.show()
    qtbot.waitExposed(w)
    empty = w.stack_btn.mapTo(w, w.stack_btn.rect().topLeft())
    source["list"] = files
    w.refresh_recent()
    qtbot.wait(20)
    assert w.stack_btn.mapTo(w, w.stack_btn.rect().topLeft()) == empty


def test_a_list_rebuilt_while_work_runs_starts_locked(qtbot, tmp_path):
    p = tmp_path / "a.nocturne"
    p.write_text("x")
    state = {"busy": False}
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: [str(p)],
                      locked=lambda: state["busy"])
    qtbot.addWidget(w)
    assert w.recent_buttons[0].isEnabled()
    state["busy"] = True
    w.refresh_recent()
    assert not w.recent_buttons[0].isEnabled()


def test_the_recent_list_unlocks_when_work_ends(qtbot, tmp_path):
    from tests.ui.test_main_window import _window
    p = tmp_path / "a.nocturne"
    p.write_text("x")
    win = _window(qtbot, tmp_path)
    win.settings.recent_projects = [str(p)]
    win.show()                                  # the start page on screen
    qtbot.waitExposed(win)
    win._set_busy(True)
    win._welcome.refresh_recent()               # rebuilt mid-run (e.g. the page re-shown)
    assert not win._welcome.recent_buttons[0].isEnabled()
    win._set_busy(False)
    assert win._welcome.recent_buttons[0].isEnabled()


def test_a_list_built_locked_while_hidden_is_live_when_shown(qtbot, tmp_path):
    """Hidden, it is not rebuilt when work ends — showing it rebuilds it."""
    from tests.ui.test_main_window import _window
    p = tmp_path / "a.nocturne"
    p.write_text("x")
    win = _window(qtbot, tmp_path)
    win.settings.recent_projects = [str(p)]
    win._set_busy(True)
    win._welcome.refresh_recent()
    win._set_busy(False)
    win.show()
    qtbot.waitExposed(win)
    assert win._welcome.recent_buttons[0].isEnabled()
