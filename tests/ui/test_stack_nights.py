"""Several nights in Stack (spec 2026-09-28 §9.2-9.3; nights mockup, option
A): a chip per night in the verdict band; unticking one takes that night out
of the stack and out of every count, and ticking it back returns it with its
own verdicts and his own ticks inside it."""
import os
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QCheckBox

from nocturne.settings import Settings
from nocturne.stacking.grade import REASON_NOT_RAW, FrameStats, judge
from nocturne.stacking.verdict import NO_NIGHT_HEADLINE
from nocturne.ui import theme
from nocturne.ui.frame_browser import SHOW_ALL, SHOW_KEPT, SHOW_REJECTED
from nocturne.ui.haoiii_dialog import HaOIIIDialog
from nocturne.ui.stack_dialog import NO_NIGHT_STATUS, StackDialog
from nocturne.ui.verdict_strip import NIGHT_CHIP

EVE_21 = datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc)     # 22:00 CEST
EVE_26 = datetime(2026, 9, 26, 20, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def stockholm(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Stockholm")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _frames(fwhms, start, tag, step=2):
    out = []
    for i, f in enumerate(fwhms):
        s = FrameStats(f"/x/{tag}_{i:03d}.fit", 800, f, 1000.0, 0.5, True,
                       exposure=10.0, target="SH2-108")
        s.captured = start + timedelta(minutes=step * i)
        out.append(s)
    return out


def _sh2_108():
    """His Sh2-108 in miniature (measured 2026-09-28): the 21st windy and
    soft, one frame at 4.0 px; the 26th calm, running past midnight."""
    soft = _frames([3.0, 3.05, 3.1] * 6 + [4.0], EVE_21, "a")
    sharp = _frames([2.5, 2.6, 2.6, 2.6, 2.7] * 8, EVE_26, "b", step=5)
    stats = soft + sharp
    judge(stats, "normal")
    return stats


def _dialog(qtbot, stats=None, room=4000, settings=None):
    d = StackDialog(settings or Settings())
    qtbot.addWidget(d)
    d._available_height = lambda: room
    d.browser.preview_controller.loader = lambda p: np.zeros((8, 8, 3), np.float32)
    if stats is not None:
        d._on_graded(stats)
    return d


def _counts(d):
    return {m: int(b.text().split()[-1]) for m, b in d.browser._show_buttons.items()}


def _everything(d):
    """Every number on screen that must follow the nights."""
    s = d.verdict_strip
    return {"headline": s.headline.text(), "facts": s.fact_pairs(),
            "status": d.status.text(), "show": _counts(d), "name": d.name_edit.text(),
            "move": s.move_btn.text() if s.move_btn.isVisibleTo(s) else "",
            "chart": d.browser.chart.point_count(),
            "stack": len(d.browser.checked_frames()),
            "drizzle": d.drizzle_note.text()}


def test_a_one_night_folder_has_no_nights_line(qtbot):
    stats = _sh2_108()[19:]
    d = _dialog(qtbot, stats)
    assert d.verdict_strip.chips == [] and d.verdict_strip.nights_row.isHidden()
    assert d.verdict_strip.headline.text() == "Good night."


def test_two_nights_get_a_chip_each_and_a_headline_that_compares_them(qtbot):
    d = _dialog(qtbot, _sh2_108())
    s = d.verdict_strip
    assert not s.nights_row.isHidden()
    assert [c.text() for c in s.chips] == ["21 Sep Soft · 18 of 19 · FWHM 3.0 px",
                                           "26 Sep Good · 40 of 40 · FWHM 2.6 px"]
    assert all(c.isChecked() and c.objectName() == NIGHT_CHIP for c in s.chips)
    assert s.chips[0].toolTip().startswith("Good night. 18 of 19 frames kept")
    assert s.headline.text() == "One good night, one soft one."
    assert s.fact_pairs()[0] == ("Kept", "58 of 59 · 10 of 10 min")


def test_the_headline_agrees_with_the_chips_after_unticking_the_sharpest_night(qtbot):
    """I1 (final review, 2026-09-28): a chip's word never changes when
    another night is unticked — it is judged against ALL nights (plan
    decision 7) — so the headline must agree with it rather than re-picking
    "the sharpest" from only what is left ticked."""
    sharp = _frames([2.0] * 20, EVE_21, "a")
    soft_a = _frames([2.6] * 20, EVE_26, "b")
    soft_b = _frames([2.7] * 20, datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc), "c")
    stats = sharp + soft_a + soft_b
    judge(stats, "normal")
    d = _dialog(qtbot, stats)
    s = d.verdict_strip
    words = lambda: [c.text().split(" · ")[0] for c in s.chips]
    assert words() == ["21 Sep Good", "26 Sep Soft", "1 Oct Soft"]
    assert s.headline.text() == "One good night, two soft ones."
    s.chips[0].click()                       # untick the sharpest (21 Sep)
    assert words() == ["21 Sep Good", "26 Sep Soft", "1 Oct Soft"], \
        "a chip must not change its word when another night is unticked"
    assert s.headline.text() == "Two soft nights.", \
        "the headline must not re-pick a new 'sharpest' from what's left ticked"


def test_unticking_a_night_takes_it_out_of_every_count(qtbot):
    stats = _sh2_108()
    d = _dialog(qtbot, stats)
    included = [s.included for s in stats]
    d.verdict_strip.chips[0].click()
    assert _everything(d) == {
        "headline": "Good night.",
        "facts": [("Kept", "40 of 40 · 7 of 7 min"), ("Stars", "FWHM 2.6 px")],
        "status": "Keeping 40 of 40 frames — 7 of 7 minutes of light.",
        "show": {SHOW_ALL: 40, SHOW_KEPT: 40, SHOW_REJECTED: 0},
        "name": "SH2-108_40x10s_7min.fits", "move": "", "chart": 40, "stack": 40,
        "drizzle": "Suitable for Drizzle.",
    }
    assert [s.included for s in stats] == included, "unticking wrote to the frames"
    assert not d.verdict_strip.chips[0].isChecked()


def test_ticking_it_back_returns_the_night_exactly_as_it_was(qtbot):
    stats = _sh2_108()
    d = _dialog(qtbot, stats)
    d.browser.set_checked(0, False)          # his own tick inside the 21st
    before = _everything(d)
    included = [s.included for s in stats]
    d.verdict_strip.chips[0].click()
    assert _everything(d) != before
    d.verdict_strip.chips[0].click()
    assert _everything(d) == before
    assert [s.included for s in stats] == included


def test_space_on_a_focused_chip_toggles_it_without_losing_focus(qtbot):
    """Ruling R7 (Task 6 fix round 1): set_nights() rebuilt every chip on
    every call, so a Space press deleteLater()'d the very chip that had
    focus — a keyboard user had to Tab from the top of the dialog again
    after every toggle. The set of nights is unchanged here, so the fix
    updates the existing QCheckBox objects in place instead."""
    d = _dialog(qtbot, _sh2_108())
    d.show()
    qtbot.waitExposed(d)
    # `activateWindow()`/`raise_()` are no-ops under the offscreen platform
    # (it implements neither), so `isActiveWindow()` never turns true and
    # focus never lands — `setActiveWindow` bypasses the platform's window
    # manager and sets Qt's own notion of the active window directly, which
    # is what focus tracking actually reads. Deprecated in favour of the
    # instance method that does not work here; still the documented way to
    # drive focus under a platform with no real window manager.
    QApplication.setActiveWindow(d)
    chip = d.verdict_strip.chips[0]
    chip.setFocus(Qt.FocusReason.OtherFocusReason)
    assert QApplication.focusWidget() is chip

    def press_space():
        down = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space,
                         Qt.KeyboardModifier.NoModifier)
        up = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Space,
                       Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(chip, down)
        QApplication.sendEvent(chip, up)

    press_space()
    assert not chip.isChecked()
    assert d.verdict_strip.chips[0] is chip, "the chip was rebuilt, not updated in place"
    assert QApplication.focusWidget() is chip, "focus was lost after the toggle"

    press_space()
    assert chip.isChecked()
    assert QApplication.focusWidget() is chip


def _master(captured):
    m = FrameStats("/x/master.fits", 0, 0.0, 0.0, 0.0, False, reason_code="not_raw",
                   reason=REASON_NOT_RAW, error=True)
    m.captured = captured
    return m


def test_a_master_among_two_nights_gets_no_third_chip_and_is_never_counted(qtbot):
    """T6 (final review, 2026-09-28): `_update_verdict` builds its nights from
    `not is_master(s)`, so a master belongs to no night. Its capture stamp
    (1 Oct, a date neither real night touches) would conjure an obvious third
    chip if that filter ever slipped."""
    stats = _sh2_108() + [_master(datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc))]
    d = _dialog(qtbot, stats)
    s = d.verdict_strip
    assert len(s.chips) == 2, "a master must not form a third night chip"
    assert [c.text().split(" · ")[0] for c in s.chips] == ["21 Sep Soft", "26 Sep Good"]
    assert ("Masters", "1 left out") in s.fact_pairs()
    # Always shown, never counted: it is on screen whichever nights are ticked...
    assert d.browser.row_count() == len(stats)
    # ...but unticking every real night still leaves nothing countable.
    s.chips[0].click()
    s.chips[1].click()
    assert s.headline.text() == NO_NIGHT_HEADLINE


def test_every_night_unticked_leaves_nothing_to_stack(qtbot, tmp_path):
    d = _dialog(qtbot, _sh2_108())
    for chip in list(d.verdict_strip.chips):
        chip.click()
    s = d.verdict_strip
    assert s.headline.text() == NO_NIGHT_HEADLINE and s.fact_pairs() == []
    assert d.status.text() == NO_NIGHT_STATUS
    assert _counts(d) == {SHOW_ALL: 0, SHOW_KEPT: 0, SHOW_REJECTED: 0}
    assert not s.move_btn.isVisibleTo(s) and d.browser.checked_frames() == []
    assert len(s.chips) == 2 and not s.nights_row.isHidden(), "the chips must stay to tick back"
    d.save_to_edit.setText(str(tmp_path))
    d.name_edit.setText("x.fits")
    assert not d._validate_ready_to_run()
    assert d.status.text() == "Select at least 3 frames to stack."


def test_unticking_the_current_frames_night_keeps_it_in_view(qtbot):
    """m2 (final review, 2026-09-28): a night going takes the cursor with it
    to a neighbour still listed (Qt's own proxy-filter behaviour), but the
    scroll offset used to stay put — the preview could show a frame the
    visible list did not. The list must follow the cursor."""
    stats = _sh2_108()
    d = _dialog(qtbot, stats)
    d.resize(900, 500)
    d.show()
    qtbot.waitExposed(d)
    view = d.browser.view
    d.browser.set_current_row(5)                  # a frame in the 21st
    view.scrollToBottom()
    assert view.verticalScrollBar().value() == view.verticalScrollBar().maximum()
    d.verdict_strip.chips[0].click()               # untick the 21st — the cursor's night
    idx = view.currentIndex()
    assert idx.isValid(), "Qt must have moved the cursor to a neighbour still listed"
    assert view.viewport().rect().intersects(view.visualRect(idx)), \
        "the frame the cursor jumped to must be scrolled into view"


def test_a_strictness_change_keeps_an_unticked_night_unticked(qtbot):
    d = _dialog(qtbot, _sh2_108())
    d.verdict_strip.chips[0].click()
    d.strictness_box.setCurrentText("Strict")
    assert [c.isChecked() for c in d.verdict_strip.chips] == [False, True]
    assert _counts(d)[SHOW_ALL] == 40


def test_a_night_too_small_to_judge_says_so_and_keeps_its_frames(qtbot):
    stats = _frames([2.5, 2.5, 6.0], EVE_21, "t") + _frames([2.5, 2.6] * 5, EVE_26, "n")
    judge(stats, "normal")
    d = _dialog(qtbot, stats)
    assert d.verdict_strip.chips[0].text() == "21 Sep Too few to judge · 3 of 3 · FWHM 2.5 px"
    assert all(s.included for s in stats[:3])
    assert d.verdict_strip.headline.text() == "One good night, one too short to judge."


def test_frames_without_a_capture_time_get_a_chip_of_their_own(qtbot):
    stats = _sh2_108()
    for s in stats[:19]:
        s.captured = None
    judge(stats, "normal")
    d = _dialog(qtbot, stats)
    assert [c.text().split(" · ")[0] for c in d.verdict_strip.chips] == ["26 Sep Good",
                                                                         "No date Soft"]


def test_an_unreadable_unstamped_frame_does_not_conjure_a_no_date_night(qtbot):
    """m3 (final review, 2026-09-28): a frame that could not be measured is
    in no count (is_left_out, the wider test than is_master alone) — it must
    not conjure a night of its own out of one unreadable, unstamped file, or
    a single-night folder gains a spurious Nights line and "No date" chip
    for a frame that appears in no count anyway."""
    stats = _sh2_108()[19:]                 # the 26th alone: a one-night folder
    bad = FrameStats("/x/junk.fit", 0, 0.0, 0.0, 0.0, False,
                     reason_code="measure_failed", reason="Could not be measured",
                     error=True)
    bad.captured = None
    d = _dialog(qtbot, stats + [bad])
    s = d.verdict_strip
    assert s.chips == [] and s.nights_row.isHidden(), "§9.2: a one-night folder looks as it did"
    assert s.headline.text() == "Good night."
    assert ("Unmeasured", "1 frame") in s.fact_pairs()


def test_the_chips_stay_when_the_screen_folds_the_facts(qtbot):
    d = _dialog(qtbot, _sh2_108())
    d.verdict_strip.set_compact(True)
    assert not d.verdict_strip.details_shown()
    assert not d.verdict_strip.nights_row.isHidden()


def test_haoiii_has_no_chips(qtbot):
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    d.browser.preview_controller.loader = lambda p: np.zeros((8, 8, 3), np.float32)
    d._on_graded(_sh2_108())
    assert len(d.browser.chart.night_lines()) == 1, "fixture lost its second night"
    assert not [c for c in d.findChildren(QCheckBox) if c.objectName() == NIGHT_CHIP]
    assert d._graded_line() == "Graded 59 frames — 58 kept."


# --- the 1280×800 floor (spec 2026-09-28 §8; CLAUDE.md) --------------------------

@pytest.fixture
def styled():
    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(theme.build_stylesheet())
    yield
    app.setStyleSheet(before)


def _big_sh2_108():
    """Both nights at his real size (42 and 211 subs), with rejects in each
    so the Rejected fact and the Move button are there; the 26th's sky
    brightens through its last third (a Trend of its own)."""
    soft = _frames(([3.0, 3.05, 3.1] * 14)[:41] + [4.0], EVE_21, "a")
    sharp = _frames(([2.5, 2.6, 2.6, 2.6, 2.7] * 43)[:205] + [3.4] * 6, EVE_26, "b", step=1)
    for i, s in enumerate(sharp):
        s.background = 1000.0 if i < 140 else 1300.0
    stats = soft + sharp
    judge(stats, "normal")
    return stats


def _at(qtbot, stats, room, width=1280, help_on=True, options_folded=False):
    settings = Settings(frame_options_folded=options_folded)
    settings.stack_help_expanded = help_on
    d = _dialog(qtbot, room=room, settings=settings)
    d.resize(width, 700)
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(stats)
    qtbot.wait(50)
    return d


def _on_screen(d, w) -> bool:
    top_left = w.mapTo(d, w.rect().topLeft())
    bottom_right = w.mapTo(d, w.rect().bottomRight())
    return d.rect().contains(top_left) and d.rect().contains(bottom_right)


def test_two_nights_fit_the_1280x800_laptop(qtbot, styled):
    d = _at(qtbot, _big_sh2_108(), 740)
    assert d.height() <= 740, f"{d.height()} px on a 740 px screen"
    assert d.preview.height() >= 220
    s = d.verdict_strip
    assert len(s.chips) == 2 and all(c.isVisible() and _on_screen(d, c) for c in s.chips)
    assert s.move_btn.isVisible(), "fixture lost its rejects"
    # The chips cost one line; the facts still fit whole at the floor.
    assert s.details_shown() and not s.is_compact()


def test_a_chip_click_at_the_floor_never_folds_the_facts(qtbot, styled):
    """Unticking the 21st leaves the 26th alone, and one night's verdict
    carries a Trend the session's cannot (build_verdict's one_night): at
    800 px wide it wraps onto one more line, so the strip grows on HIS click.
    As with a move's report line (I1), the frame list gives up the height —
    never the facts he is reading. Pinned with zero slack: the screen is
    exactly as tall as the dialog needs before the click, and help, options
    and chart are already folded, so the verdict is the only fold left."""
    d = _at(qtbot, _big_sh2_108(), 4000, width=800, help_on=False, options_folded=True)
    d.browser.chart_panel.set_folded(True)
    qtbot.wait(50)
    room = d._natural_minimum_height()
    d._available_height = lambda: room
    d.resize(d.width(), room)
    qtbot.wait(50)
    assert d.verdict_strip.details_shown() and not d.verdict_strip.is_compact()
    d.verdict_strip.chips[0].click()
    qtbot.wait(50)
    assert d._natural_minimum_height() > room, "fixture: the click must grow the dialog"
    assert any(label == "Trend" for label, _v in d.verdict_strip.fact_pairs())
    assert d.verdict_strip.details_shown() and not d.verdict_strip.is_compact(), \
        "a chip click folded the verdict to its headline"
    assert d.height() <= room, f"{d.height()} px on a {room} px screen"


# --- a night moved into rejected/ whole ----------------------------------------------

def _two_night_runner(paths, on_progress=None, strictness="normal"):
    """Light_00-05 on the 21st, Light_06-11 on the 26th, all sharp."""
    import os
    stats = []
    for p in sorted(paths):
        i = int(os.path.basename(p)[6:8])
        s = FrameStats(p, 800, 2.5, 1000.0, 0.5, True, exposure=10.0)
        s.captured = (EVE_21 + timedelta(minutes=2 * i) if i < 6
                      else EVE_26 + timedelta(minutes=2 * (i - 6)))
        stats.append(s)
    return stats


def test_a_night_moved_whole_into_rejected_keeps_its_chip(qtbot, tmp_path):
    from tests.ui.test_stack_rejected import _folder
    folder, _paths = _folder(tmp_path, n=12)
    d = _dialog(qtbot)
    d._grade_runner = _two_night_runner
    d._confirm = lambda title, text: True
    d.folder_edit.setText(str(folder))
    d.grade()
    qtbot.waitUntil(lambda: not d._busy, timeout=3000)
    for row in range(6, 12):
        d.browser.set_checked(row, False)
    d.verdict_strip.move_btn.click()
    assert sorted(os.listdir(folder / "rejected"))[1:] == [f"Light_{i:02d}.fit" for i in range(6, 12)]
    s = d.verdict_strip
    assert [c.text().split(" · ")[0] for c in s.chips] == ["21 Sep Good", "26 Sep Good"]
    assert _counts(d) == {SHOW_ALL: 12, SHOW_KEPT: 6, SHOW_REJECTED: 6}
    assert s.back_btn.text() == "Move them back (6)"
    s.chips[1].click()                        # the moved night out of the counts
    assert _counts(d) == {SHOW_ALL: 6, SHOW_KEPT: 6, SHOW_REJECTED: 0}
    assert not s.move_btn.isVisibleTo(s) and s.back_btn.isVisibleTo(s)
    s.back_btn.click()                        # back home, still in an unticked night
    assert not (folder / "rejected" / "Light_06.fit").exists()
    assert _counts(d) == {SHOW_ALL: 6, SHOW_KEPT: 6, SHOW_REJECTED: 0}
    s.chips[1].click()
    assert _counts(d) == {SHOW_ALL: 12, SHOW_KEPT: 12, SHOW_REJECTED: 0}
    assert not any(st.included for st in d._stats[6:]), "his unticks came back undone"
