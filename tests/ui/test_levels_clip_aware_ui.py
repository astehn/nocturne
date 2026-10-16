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


def _count_searches(monkeypatch):
    """Counts the REAL search, nocturne.core.levels.auto_black — wherever it is
    reached from (MainWindow's own call, or resolve_levels inside the step at
    Apply), so an Apply-time re-search is counted too."""
    import nocturne.core.levels as core_levels
    calls = []
    real = core_levels.auto_black

    def counting(img, *a, **k):
        calls.append(1)
        return real(img, *a, **k)
    monkeypatch.setattr(core_levels, "auto_black", counting)
    monkeypatch.setattr(mw, "auto_black", counting)
    return calls


def test_auto_is_searched_once_per_input(qtbot, tmp_path, monkeypatch):
    calls = _count_searches(monkeypatch)
    win = _at_levels(qtbot, tmp_path)
    win._on_levels_auto()
    for v in (-3, -6, -9):
        win._panel.red_slider.setValue(v)
        _settle(qtbot, win)
    win._on_levels_auto()                              # pressed again: same input
    win._apply_current_step()
    assert win.project.entries()[-1][1]["auto"] is True
    assert len(calls) == 1, f"Auto's search ran {len(calls)} times"


def test_another_picture_is_searched_afresh(qtbot, tmp_path, monkeypatch):
    calls = _count_searches(monkeypatch)
    win = _at_levels(qtbot, tmp_path)
    win._on_levels_auto()
    first = win._panel.black_slider.value()
    win._ask_pending = lambda *a, **k: "discard"
    other = AstroImage(_sky(seed=5, means=(0.30, 0.29, 0.28)), is_linear=False)
    win.open_image(other, "other")
    win._go_to_id("levels", user_initiated=False)
    win._on_levels_auto()
    assert len(calls) == 2, "image B reused image A's Auto"
    expected = auto_black(other)
    assert win._panel.black_slider.value() == int(expected.black * BLACK_STEPS) != first


def test_undoing_an_earlier_step_searches_afresh(qtbot, tmp_path, monkeypatch):
    calls = _count_searches(monkeypatch)
    win = _window(qtbot, tmp_path)
    win.open_image(_stop_image(), "stop")
    win._go_to_id("remove_green", user_initiated=False)
    win._panel.rg_slider.setValue(100)
    win._panel.apply_btn.click()
    assert win.project.entries()[-1][0] != "Levels" and len(win.project.entries()) == 1
    win._go_to_id("levels", user_initiated=False)
    win._on_levels_auto()
    win._ask_pending = lambda *a, **k: "discard"
    win._undo()
    assert win.project.entries() == []
    win._go_to_id("levels", user_initiated=False)
    win._on_levels_auto()
    assert len(calls) == 2, "Auto reused the decision made on the undone input"
    # De-green leaves this fixture's stop where it was, so equal numbers cannot
    # tell a stale decision from a fresh one: the decision must be the one
    # made for the input on screen now.
    assert win._levels_auto_cache[0] == win._base_token("levels"), (
        "Auto's decision belongs to the undone input")
    assert win._panel.black_slider.value() == int(
        auto_black(win._preview_base("levels")).black * BLACK_STEPS)


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


def test_the_colour_section_follows_the_levels_input_not_the_position(qtbot, tmp_path,
                                                                      monkeypatch):
    """The offsets act on the Levels INPUT; whatever the current position's
    shape says, an RGB input shows them. After a Levels commit the position
    (1) and the Levels input (0) differ, so reading the wrong one shows."""
    win = _at_levels(qtbot, tmp_path)
    win.apply_current(new_levels_option(0.05))
    assert win.project.position == 1
    real = win.project.shape_at
    monkeypatch.setattr(win.project, "shape_at",
                        lambda i: real(i) if i == 0 else (903, 1201))
    win._go_to_id("curves", user_initiated=False)
    win._go_to_id("levels", user_initiated=False)
    assert not win._panel.levels_colour_box.isHidden()


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
            "(unlimited Auto: 0.219) · blue −0.015 · Δ") in line, line


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


# --- returning to Levels shows the commit (review 2026-10-14, fix round 1) ---

def _away_and_back(win):
    win._go_to_id("curves", user_initiated=False)
    win._go_to_id("levels", user_initiated=False)


def _channels_after_blue_move(qtbot, win, committed):
    """Arrival renders nothing and is not pending; a blue move changes blue
    only — red and green stay exactly the committed picture."""
    assert np.array_equal(win._displayed.data, committed)
    assert win._has_pending() is False
    win._panel.blue_slider.setValue(win._panel.blue_slider.value() - 15)
    _settle(qtbot, win)
    shown = win._displayed.data
    assert np.array_equal(shown[..., 0], committed[..., 0])
    assert np.array_equal(shown[..., 1], committed[..., 1])
    assert not np.array_equal(shown[..., 2], committed[..., 2])
    return shown


def test_returning_to_a_v2_auto_shows_it_selected(qtbot, tmp_path):
    win = _at_levels(qtbot, tmp_path)
    win._on_levels_auto()
    win._panel.blue_slider.setValue(-15)
    win._apply_current_step()
    committed = win.project.current().data.copy()
    _away_and_back(win)
    p = win._panel
    assert p.auto_btn.isChecked() and win._levels_auto is True
    assert p.auto_note.text() == NOTE and not p.auto_note.isHidden()
    assert p.black_slider.value() == 100 and p.blue_slider.value() == -15
    assert win._controls_match_commit("levels") is True
    _channels_after_blue_move(qtbot, win, committed)
    assert win._levels_auto is True, "a colour move on a revisit dropped Auto"
    win._apply_current_step()
    assert win.project.entries()[-1][1] == {"auto": True, "version": 2,
                                            "offsets": [0.0, 0.0, -0.03]}


def test_returning_to_hand_set_values_shows_them(qtbot, tmp_path):
    win = _at_levels(qtbot, tmp_path)
    win._panel.black_slider.setValue(62)
    win._panel.gamma_slider.setValue(120)
    win._panel.red_slider.setValue(8)
    win._apply_current_step()
    committed = win.project.current().data.copy()
    _away_and_back(win)
    p = win._panel
    assert (p.black_slider.value(), p.gamma_slider.value(), p.white_slider.value(),
            p.red_slider.value(), p.blue_slider.value()) == (62, 120, 100, 8, 0)
    assert not p.auto_btn.isChecked() and p.auto_note.isHidden()
    assert win._controls_match_commit("levels") is True
    _channels_after_blue_move(qtbot, win, committed)


def test_returning_to_an_old_v1_auto_keeps_its_exact_black(qtbot, tmp_path):
    from nocturne.core.levels import auto_levels
    win = _at_levels(qtbot, tmp_path)
    win.apply_current("auto")                         # an older project's Auto
    committed = win.project.current().data.copy()
    v1_black = auto_levels(win._preview_base("levels").data)[0]
    _away_and_back(win)
    p = win._panel
    assert not p.auto_btn.isChecked(), "v1 shown as selected: pressing it would give v2"
    assert p.black_slider.value() == int(v1_black * BLACK_STEPS)
    assert win._panel.commit_option()["black"] == v1_black
    _channels_after_blue_move(qtbot, win, committed)
    win._apply_current_step()
    option = win.project.entries()[-1][1]
    assert option == new_levels_option(v1_black, 1.0, 1.0, (0.0, 0.0, -0.015))


def test_auto_enhance_log_line_says_where_auto_stopped(qtbot, tmp_path):
    """Auto Enhance and a preset log through _record_auto_run; its Levels line
    carries the same stop detail as the panel's Apply (one helper)."""
    from nocturne.core.auto_enhance import AUTO_LEVELS, run_auto_plan
    from nocturne.settings import Settings
    win = _at_levels(qtbot, tmp_path)
    run = run_auto_plan(win.project.current(), [("levels", AUTO_LEVELS)], Settings())
    win._record_auto_run(run, "Auto Enhance (Natural)")
    line = win.log_panel.entries()[-1]
    assert line.endswith("Levels (auto) · black 0.100 — stopped at the clipping limit "
                         "(unlimited Auto: 0.219) — Auto Enhance (Natural)"), line


def test_preset_log_line_shows_a_saved_hand_set_levels(qtbot, tmp_path):
    from nocturne.core.auto_enhance import run_auto_plan
    from nocturne.settings import Settings
    win = _at_levels(qtbot, tmp_path)
    opt = new_levels_option(0.062, 1.0, 1.0, (0, 0, -0.015))
    run = run_auto_plan(win.project.current(), [("levels", opt)], Settings(),
                        levels_auto=False)
    win._record_auto_run(run, "Preset (M 8)")
    line = win.log_panel.entries()[-1]
    assert line.endswith("Levels · black 0.062 · blue −0.015 — Preset (M 8)"), line


# --- final whole-branch review: arrival cost, minors, parked tests ----------

def test_arrival_after_auto_enhance_does_not_search_again(qtbot, tmp_path, monkeypatch):
    """Auto Enhance already decided Auto on this very input; returning to
    Levels reuses that decision (only a reopened project pays the search)."""
    from nocturne.core.auto_enhance import AUTO_LEVELS, run_auto_plan
    from nocturne.settings import Settings
    calls = _count_searches(monkeypatch)
    win = _at_levels(qtbot, tmp_path)
    run = run_auto_plan(win.project.current(),
                        [("levels", AUTO_LEVELS), ("local_contrast", 0.15)], Settings())
    assert len(calls) == 1
    win._record_auto_run(run, "Auto Enhance (Natural)")
    _away_and_back(win)
    assert len(calls) == 1, f"arrival searched again ({len(calls) - 1} more)"
    p = win._panel
    assert p.auto_btn.isChecked() and p.auto_note.text() == NOTE
    assert win._controls_match_commit("levels") is True


def test_arrival_after_a_panel_apply_does_not_search_again(qtbot, tmp_path, monkeypatch):
    calls = _count_searches(monkeypatch)
    win = _at_levels(qtbot, tmp_path)
    win.apply_current(new_levels_option(auto=True))     # Apply without a press first
    assert len(calls) == 1
    _away_and_back(win)
    assert len(calls) == 1, "arrival searched the input Apply had just searched"
    assert win._panel.auto_btn.isChecked()


def test_arrival_reads_the_shape_without_loading_the_levels_input(qtbot, tmp_path,
                                                                 monkeypatch):
    from nocturne.core.auto_enhance import AUTO_LEVELS, run_auto_plan
    from nocturne.settings import Settings
    win = _at_levels(qtbot, tmp_path)
    run = run_auto_plan(win.project.current(), [("levels", AUTO_LEVELS)], Settings())
    win._record_auto_run(run, "Auto Enhance (Natural)")
    win._go_to_id("curves", user_initiated=False)
    win._base_cache = None                               # nothing held in memory
    loads = []
    real = win.project.state_at
    monkeypatch.setattr(win.project, "state_at", lambda i: (loads.append(i), real(i))[1])
    win._go_to_id("levels", user_initiated=False)
    assert 0 not in loads, "arrival loaded the Levels input"
    assert not win._panel.levels_colour_box.isHidden()


def test_returning_to_an_untouched_v1_auto_leaves_apply_unlit(qtbot, tmp_path):
    win = _at_levels(qtbot, tmp_path)
    win.apply_current("auto")
    _away_and_back(win)
    assert win._has_pending() is False
    assert win._controls_match_commit("levels") is True, "Apply lit on an untouched v1 Auto"
    win._panel.blue_slider.setValue(-15)
    assert win._controls_match_commit("levels") is False


def test_log_line_floors_a_hand_set_black_like_the_panel():
    assert mw.MainWindow._levels_log_detail(new_levels_option(0.0629), None) == " · black 0.062"


def test_off_grid_midtones_and_white_survive_a_colour_nudge(qtbot, tmp_path):
    """A hand-edited recipe or preset can carry values off the slider grid;
    touching a colour must not snap midtones or white to it."""
    win = _at_levels(qtbot, tmp_path)
    win.apply_current(new_levels_option(0.0623, 1.234, 0.987))
    _away_and_back(win)
    p = win._panel
    assert (p.gamma_slider.value(), p.white_slider.value()) == (123, 99)
    assert win._controls_match_commit("levels") is True
    p.blue_slider.setValue(-15)
    win._apply_current_step()
    assert win.project.entries()[-1][1] == new_levels_option(0.0623, 1.234, 0.987,
                                                             (0.0, 0.0, -0.015))


def test_a_fresh_visit_shows_defaults_and_searches_nothing(qtbot, tmp_path, monkeypatch):
    calls = _count_searches(monkeypatch)
    win = _at_levels(qtbot, tmp_path)
    p = win._panel
    assert (p.black_slider.value(), p.gamma_slider.value(), p.white_slider.value(),
            p.red_slider.value(), p.green_slider.value(), p.blue_slider.value()) == (
        0, 100, 100, 0, 0, 0)
    assert not p.auto_btn.isChecked() and p.auto_note.isHidden()
    assert win._has_pending() is False and calls == []


def test_undo_past_levels_forgets_its_commit(qtbot, tmp_path):
    win = _at_levels(qtbot, tmp_path)
    imported = win.project.current().data.copy()
    win._on_levels_auto()
    win._panel.blue_slider.setValue(-15)
    win._apply_current_step()
    win._undo()
    assert win.project.entries() == []
    _away_and_back(win)
    p = win._panel
    assert (p.black_slider.value(), p.blue_slider.value()) == (0, 0)
    assert not p.auto_btn.isChecked() and p.auto_note.isHidden()
    assert win._has_pending() is False
    assert np.array_equal(win._displayed.data, imported)


def test_a_midtone_move_on_a_revisited_v2_keeps_autos_exact_black(qtbot, tmp_path):
    win = _at_levels(qtbot, tmp_path)
    win._on_levels_auto()
    win._apply_current_step()
    exact = auto_black(win._preview_base("levels")).black
    assert exact * BLACK_STEPS != int(exact * BLACK_STEPS), "fixture: black must be off grid"
    _away_and_back(win)
    win._panel.gamma_slider.setValue(120)
    assert win._levels_auto is False                    # a midtone move is a choice
    win._apply_current_step()
    assert win.project.entries()[-1][1] == new_levels_option(exact, 1.2, 1.0)


def test_dragging_black_point_keeps_the_note_until_the_drag_ends(qtbot, tmp_path):
    """His find (2026-10-16): the note vanished mid-drag, the sliders jumped up
    and Black point was no longer under the pointer. During a drag the layout
    must hold still; the note goes when the slider is released."""
    win = _at_levels(qtbot, tmp_path)
    win.resize(1440, 900)
    win.show()
    qtbot.waitExposed(win)
    p = win._panel
    win._on_levels_auto()
    qtbot.wait(20)
    assert not p.auto_note.isHidden(), "fixture: Auto must have stopped"
    y_before = p.black_slider.mapTo(win, p.black_slider.rect().topLeft()).y()

    p.black_slider.setSliderDown(True)                 # the user grabs the handle
    p.black_slider.setValue(p.black_slider.value() + 5)
    qtbot.wait(20)
    assert win._levels_auto is False, "dragging Black point still takes over from Auto"
    assert not p.auto_note.isHidden(), "the note vanished mid-drag"
    assert p.black_slider.mapTo(win, p.black_slider.rect().topLeft()).y() == y_before, (
        "Black point moved under the pointer during the drag")

    p.black_slider.setSliderDown(False)                # released
    qtbot.wait(20)
    assert p.auto_note.isHidden(), "the note outlived the drag"


def test_a_released_drag_that_returns_to_auto_keeps_nothing_stale(qtbot, tmp_path):
    """Pressing Auto again during or after the deferred hide must not leave the
    note hidden by a late release."""
    win = _at_levels(qtbot, tmp_path)
    p = win._panel
    win._on_levels_auto()
    p.black_slider.setSliderDown(True)
    p.black_slider.setValue(p.black_slider.value() + 5)
    p.black_slider.setSliderDown(False)
    win._on_levels_auto()                              # back to Auto
    p.black_slider.setSliderDown(True)
    p.black_slider.setSliderDown(False)                # a click with no move
    qtbot.wait(20)
    assert win._levels_auto is True and not p.auto_note.isHidden()
