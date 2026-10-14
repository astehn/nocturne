"""Levels, clip-aware (spec 2026-10-14, Task 2): the Auto note and log line,
the per-colour black points, preview == commit through Auto's continuous black,
the cached Auto search, and an old project's version-1 Auto."""
import numpy as np
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

import nocturne.ui.main_window as mw
from nocturne.core.image import AstroImage
from nocturne.core.levels import BLACK_STEPS, auto_black, new_levels_option
from tests.core.test_levels_clip_aware import _blue_lane, _sky, _stop_image
from tests.ui.test_main_window import _shown, _window

NOTE = ("Auto stopped at 0.100 so no colour is crushed past the warning limit. "
        "Drag Black point right to go darker on purpose.")


def _settle(qtbot, win):
    qtbot.wait(120)                                   # past the 90 ms debounce
    qtbot.waitUntil(lambda: not win._previews.busy and win._previews._running is None,
                    timeout=10000)


def _at_levels(qtbot, tmp_path, img=None):
    win = _window(qtbot, tmp_path)
    win.open_image(img if img is not None else _stop_image(), "stop")
    win._go_to_id("levels", user_initiated=False)
    return win


def _key(widget, key, n=1):
    for _ in range(n):
        QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key,
                                                 Qt.KeyboardModifier.NoModifier))


def test_fixture_stops_between_two_slider_steps():
    """The (f) teeth below need an Auto black that rounds UP past itself."""
    a = auto_black(_stop_image())
    assert a.stopped and a.black < a.candidate
    assert round(a.black * BLACK_STEPS) > a.black * BLACK_STEPS, "fixture would not catch round-up"


def test_auto_that_stopped_shows_its_note_and_a_black_rounded_down(qtbot, tmp_path):
    win = _at_levels(qtbot, tmp_path)
    p = win._panel
    assert p.auto_note.isHidden()
    win._on_levels_auto()
    decided = auto_black(win._preview_base("levels"))
    assert p.auto_btn.isChecked()
    assert not p.auto_note.isHidden() and p.auto_note.text() == NOTE
    assert p.black_slider.value() / BLACK_STEPS <= decided.black, (
        "the slider shows a black above Auto's: dragging to it crosses the limit")
    assert p.black_slider.value() == int(decided.black * BLACK_STEPS)
    assert p.black_val.text() == "0.100"


def test_auto_that_did_not_stop_says_nothing(qtbot, tmp_path):
    win = _at_levels(qtbot, tmp_path, AstroImage(_sky(), is_linear=False))
    win._on_levels_auto()
    assert not auto_black(win._preview_base("levels")).stopped
    assert win._panel.auto_btn.isChecked() and win._panel.auto_note.isHidden()


def test_colour_sliders_keep_auto_and_black_point_drops_it(qtbot, tmp_path):
    win = _at_levels(qtbot, tmp_path)
    p = win._panel
    win._on_levels_auto()
    p.blue_slider.setValue(-15)
    assert win._levels_auto is True and p.auto_btn.isChecked()
    assert not p.auto_note.isHidden(), "a colour move hid the note about Auto's black"
    assert win._levels_pending == {"auto": True, "version": 2,
                                   "offsets": [0.0, 0.0, -0.015]}
    assert p.blue_val.text() == "−0.015"
    p.black_slider.setValue(p.black_slider.value() + 1)
    assert win._levels_auto is False and not p.auto_btn.isChecked()
    assert p.auto_note.isHidden()
    assert win._levels_pending["offsets"] == [0.0, 0.0, -0.015]
    assert "auto" not in win._levels_pending


def test_preview_is_the_commit_with_auto_and_an_offset(qtbot, tmp_path):
    """WYSIWYG through Auto's CONTINUOUS black: the slider shows 0.100, Auto
    applies 0.1005…; a preview drawn from the slider differs from the commit."""
    win = _at_levels(qtbot, tmp_path)
    win._on_levels_auto()
    win._panel.blue_slider.setValue(-15)
    _settle(qtbot, win)
    shown = win._displayed.data.copy()
    win._apply_current_step()
    name, option = win.project.entries()[-1]
    assert name == "Levels"
    assert option == {"auto": True, "version": 2, "offsets": [0.0, 0.0, -0.015]}
    assert np.array_equal(win.project.current().data, shown)


def test_auto_is_searched_once_per_input(qtbot, tmp_path, monkeypatch):
    calls = []
    real = mw.auto_black

    def counting(img, *a, **k):
        calls.append(1)
        return real(img, *a, **k)
    monkeypatch.setattr(mw, "auto_black", counting)
    win = _at_levels(qtbot, tmp_path)
    win._on_levels_auto()
    for v in (-3, -6, -9):
        win._panel.red_slider.setValue(v)
        _settle(qtbot, win)
    win._on_levels_auto()                              # pressed again: same input
    win._apply_current_step()
    assert len(calls) == 1, f"Auto's search ran {len(calls)} times"


def test_dragging_a_colour_slider_updates_the_readout_live(qtbot, tmp_path):
    """Driven by real key events to the slider (CLAUDE.md: sendEvent)."""
    win = _at_levels(qtbot, tmp_path)
    win._on_levels_auto()
    _settle(qtbot, win)
    before = _shown(win)[("lo", "B")]
    blue = win._panel.blue_slider
    _key(blue, Qt.Key.Key_PageUp, 3)                  # darken blue by 0.030
    assert blue.value() == 30 and win._panel.blue_val.text() == "+0.030"
    _settle(qtbot, win)
    after = _shown(win)[("lo", "B")]
    assert float(after.rstrip("%")) > float(before.rstrip("%")), (before, after)


def test_a_mono_picture_hides_the_colour_section(qtbot, tmp_path):
    mono = AstroImage(_blue_lane(_sky())[..., 2].copy(), is_linear=False)
    win = _at_levels(qtbot, tmp_path, mono)
    assert win._panel.levels_colour_box.isHidden()
    win.open_image(_stop_image(), "colour")            # and back on a colour one
    win._go_to_id("levels", user_initiated=False)
    assert not win._panel.levels_colour_box.isHidden()


def test_log_line_when_auto_stopped(qtbot, tmp_path):
    win = _at_levels(qtbot, tmp_path)
    win._on_levels_auto()
    win._panel.blue_slider.setValue(-15)
    win._apply_current_step()
    line = win.log_panel.entries()[-1]
    assert ("Levels (auto) · black 0.100 — stopped at the clipping limit "
            "(unlimited Auto: 0.220) · blue −0.015 · Δ") in line, line


def test_log_line_for_hand_set_values(qtbot, tmp_path):
    win = _at_levels(qtbot, tmp_path)
    win._panel.black_slider.setValue(62)
    win._panel.blue_slider.setValue(-15)
    win._apply_current_step()
    line = win.log_panel.entries()[-1]
    assert "Levels · black 0.062 · blue −0.015 · Δ" in line, line
    assert win.project.entries()[-1][1] == new_levels_option(0.062, 1.0, 1.0, (0, 0, -0.015))


def test_log_label_knows_the_dict_auto():
    assert mw.MainWindow._step_log_label("levels", new_levels_option(auto=True), None) == "auto"
    assert mw.MainWindow._step_log_label("levels", "auto", None) == "auto"
    assert mw.MainWindow._step_log_label("levels", new_levels_option(0.1), None) == ""


def test_an_old_projects_auto_stays_version_1_until_auto_is_pressed(qtbot, tmp_path, monkeypatch):
    """Stretch's older-version rule, for Levels: a reopened project's "auto"
    (version 1) is shown as committed; nothing re-previews it as version 2
    until the user asks, and then it is pending and Apply upgrades it."""
    monkeypatch.setattr(mw.MainWindow, "_ask_pending", lambda self, *a, **k: "discard")
    win = _at_levels(qtbot, tmp_path)
    win.apply_current("auto")                         # what an old project holds
    assert win.project.entries()[-1][1] == "auto"
    committed = win.project.current().data.copy()
    win._go_to_id("curves", user_initiated=False)
    win._go_to_id("levels", user_initiated=False)
    _settle(qtbot, win)
    assert np.array_equal(win._displayed.data, committed), "opening the panel re-previewed it"
    assert win._has_pending() is False
    assert win._panel.auto_btn.isChecked() is False and win._panel.auto_note.isHidden()

    win._on_levels_auto()
    _settle(qtbot, win)
    shown = win._displayed.data.copy()
    assert not np.array_equal(shown, committed), "fixture: v2 must differ from v1 here"
    assert win._has_pending() is True, "a version-2 preview over a version-1 commit read as nothing"
    assert win._controls_match_commit("levels") is False
    win._apply_current_step()
    assert win.project.entries()[-1][1]["version"] == 2
    assert np.array_equal(win.project.current().data, shown)
    assert win._has_pending() is False
    assert win._controls_match_commit("levels") is True


def test_a_legacy_tuple_commit_matches_the_same_numbers_on_the_panel(qtbot, tmp_path):
    win = _at_levels(qtbot, tmp_path)
    win.apply_current((0.05, 1.0, 1.0))               # an older project's shape
    win._panel.black_slider.setValue(50)
    assert win._controls_match_commit("levels") is True
    win._panel.green_slider.setValue(5)
    assert win._controls_match_commit("levels") is False


def test_the_colour_sliders_are_gated_while_busy(qtbot, tmp_path):
    win = _at_levels(qtbot, tmp_path)
    p = win._panel
    sliders = (p.red_slider, p.green_slider, p.blue_slider)
    assert all(s.isEnabled() for s in sliders)
    win._set_busy(True, "Working…")
    assert not any(s.isEnabled() for s in sliders)
    win._set_busy(False)
    assert all(s.isEnabled() for s in sliders)


def test_double_click_resets_a_colour_slider(qtbot, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    win = _at_levels(qtbot, tmp_path)
    s = win._panel.red_slider
    s.setValue(-40)
    pos = QPointF(5, 5)
    QApplication.sendEvent(s, QMouseEvent(QEvent.Type.MouseButtonDblClick, pos, s.mapToGlobal(pos),
                                          Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                          Qt.KeyboardModifier.NoModifier))
    assert s.value() == 0 and win._panel.red_val.text() == "0.000"
