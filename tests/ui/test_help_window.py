""""How this works" opens the help in its own window — nothing in the column.

Andreas, 2026-10-05: inline, the step help was a wall of text nobody would
read, and scrolling it moved Apply and Reset — the right column is for
controls. Now the link opens ONE reused help window at the step's topic; it
follows the step while open and keeps its size and place.
"""
from tests.ui.test_main_window import _make_fits, _window


def _at(qtbot, tmp_path, step="levels"):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.3, "linked": True})
    win._go_to_id(step)
    return win


def _shown_topic(dlg):
    from nocturne.ui.help_dialog import _TOPIC_ROLE
    item = dlg.nav.currentItem()
    return item.data(_TOPIC_ROLE) if item else None


def test_no_help_text_in_the_column(qtbot, tmp_path):
    from PySide6.QtWidgets import QLabel
    win = _at(qtbot, tmp_path)
    labels = win._side.scroll.widget().findChildren(QLabel, "stepExplainer")
    assert labels == [], "the step's long help must not live in the right column"


def test_the_link_opens_the_help_window_at_this_step(qtbot, tmp_path):
    from nocturne.ui import help_content as hc
    win = _at(qtbot, tmp_path)
    win._panel.help_link.linkActivated.emit("#")
    dlg = win._help_dlg
    qtbot.addWidget(dlg)
    assert dlg.isVisible() and not dlg.isModal()
    assert _shown_topic(dlg) == hc.stage_topic_id("levels")


def test_one_window_reused(qtbot, tmp_path):
    win = _at(qtbot, tmp_path)
    win._panel.help_link.linkActivated.emit("#")
    first = win._help_dlg
    qtbot.addWidget(first)
    win._panel.help_link.linkActivated.emit("#")
    assert win._help_dlg is first


def test_it_follows_the_step_while_open(qtbot, tmp_path):
    from nocturne.ui import help_content as hc
    win = _at(qtbot, tmp_path)
    win._panel.help_link.linkActivated.emit("#")
    qtbot.addWidget(win._help_dlg)
    assert hc.stage_topic_id("curves") != hc.stage_topic_id("levels"), "fixture"
    assert _shown_topic(win._help_dlg) == hc.stage_topic_id("levels")
    win._go_to_id("curves")
    assert _shown_topic(win._help_dlg) == hc.stage_topic_id("curves")
    win._go_to_id("levels")
    assert _shown_topic(win._help_dlg) == hc.stage_topic_id("levels"), "and keeps following"


def test_a_topic_you_chose_is_not_pulled_away(qtbot, tmp_path):
    """Browsed to another topic in the window, then Next: stay on it."""
    win = _at(qtbot, tmp_path)
    win._panel.help_link.linkActivated.emit("#")
    dlg = win._help_dlg
    qtbot.addWidget(dlg)
    dlg.show_topic("getting-started")               # the user clicked it in the list
    win._go_to_id("curves")
    assert _shown_topic(dlg) == "getting-started"


def test_quitting_with_the_help_open_keeps_its_size(qtbot, tmp_path):
    win = _at(qtbot, tmp_path)
    win._panel.help_link.linkActivated.emit("#")
    dlg = win._help_dlg
    qtbot.addWidget(dlg)
    dlg.resize(770, 570)
    win._confirm_save_if_dirty = lambda: True       # no unsaved-project prompt in a test
    win.close()
    from nocturne.settings import load_settings
    saved = load_settings(win._settings_path).help_window_geometry
    assert saved, "geometry saved on quit"
    from PySide6.QtCore import QByteArray
    from nocturne.ui.help_dialog import HelpDialog
    probe = HelpDialog(); qtbot.addWidget(probe)
    probe.restoreGeometry(QByteArray.fromHex(saved.encode()))
    assert (probe.width(), probe.height()) == (770, 570)


def test_a_closed_window_does_not_reopen_on_its_own(qtbot, tmp_path):
    win = _at(qtbot, tmp_path)
    win._panel.help_link.linkActivated.emit("#")
    dlg = win._help_dlg
    qtbot.addWidget(dlg)
    dlg.reject()
    win._go_to_id("curves")
    assert not dlg.isVisible(), "following the step must not pop a closed window back up"


def test_it_keeps_its_size_and_place(qtbot, tmp_path):
    win = _at(qtbot, tmp_path)
    win._panel.help_link.linkActivated.emit("#")
    dlg = win._help_dlg
    qtbot.addWidget(dlg)
    dlg.resize(780, 580)        # within the 800x600 offscreen screen: Qt clamps a restore to the screen
    dlg.reject()                                   # Close, Esc or the close box
    assert win.settings.help_window_geometry, "remembered on close"
    from nocturne.settings import load_settings
    assert load_settings(win._settings_path).help_window_geometry == win.settings.help_window_geometry
    win._help_dlg = None                           # as after a restart
    win._panel.help_link.linkActivated.emit("#")
    qtbot.addWidget(win._help_dlg)
    assert (win._help_dlg.width(), win._help_dlg.height()) == (780, 580)


def test_opening_the_help_moves_nothing_in_the_column(qtbot, tmp_path):
    win = _at(qtbot, tmp_path)
    win.resize(1280, 800); win.show(); qtbot.waitExposed(win)
    apply_btn = win._panel.apply_btn
    before = (apply_btn.mapTo(win, apply_btn.rect().topLeft()), win._side.scroll.verticalScrollBar().maximum())
    win._panel.help_link.linkActivated.emit("#")
    qtbot.addWidget(win._help_dlg)
    qtbot.wait(20)
    after = (apply_btn.mapTo(win, apply_btn.rect().topLeft()), win._side.scroll.verticalScrollBar().maximum())
    assert after == before


def test_the_stylesheet_has_no_dangling_selector_comma():
    """Qt drops a rule whose selector list ends in a comma, SILENTLY, and the
    sheet after it parses differently: removing the help label's selector left
    `…#stepCard,` before the brace and the step notes changed font and clipped
    (seen in the first render, 2026-10-05)."""
    import re
    from nocturne.ui.theme import build_stylesheet
    bad = re.findall(r",\s*\{", build_stylesheet())
    assert bad == []
