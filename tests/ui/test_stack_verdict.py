"""The night's verdict (spec 2026-09-27 decision 6), as one row of labelled
facts across the dialog over the chart (spec 2026-09-28 §2.4, layout C).
Stack only."""
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from astropy.io import fits
from PySide6.QtGui import QFontMetrics

from nocturne.settings import Settings
from nocturne.stacking.grade import FrameStats, judge
from nocturne.ui.haoiii_dialog import HaOIIIDialog
from nocturne.ui.stack_dialog import StackDialog
from nocturne.stacking.verdict import Verdict
from nocturne.ui.verdict_strip import MORE_TEXT, VerdictStrip, fact_html, move_label

T0 = datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc)
S30_CARDS = {"FOCALLEN": 160.0, "XPIXSZ": 2.9, "XBINNING": 1}


def _night(folder, n=12, soft=(2, 5), cards=None):
    """n subs 5 minutes apart; the `soft` ones at FWHM 3.0 — rejected at
    Normal (limit 2.875), kept at Relaxed (3.125). With `cards`, each path is
    a real tiny FITS carrying them, so the header read finds its optics."""
    stats = []
    for i in range(n):
        path = os.path.join(str(folder), f"Light_{i:02d}.fit")
        if cards is not None:
            hdu = fits.PrimaryHDU(np.zeros((4, 4), np.uint16))
            for k, v in cards.items():
                hdu.header[k] = v
            hdu.writeto(path)
        s = FrameStats(path, 800, 3.0 if i in soft else 2.5, 1000.0, 0.5, True,
                       exposure=10.0)
        s.captured = T0 + timedelta(minutes=5 * i)
        stats.append(s)
    judge(stats, "normal")
    return stats


def _dialog(qtbot, room=4000, **settings_kw):
    settings = Settings()
    for k, v in settings_kw.items():
        setattr(settings, k, v)
    d = StackDialog(settings)
    qtbot.addWidget(d)
    d._available_height = lambda: room
    return d, settings


def _top(d, w):
    return w.mapTo(d, w.rect().topLeft()).y()


# --- the strip itself -----------------------------------------------------------

def test_an_empty_strip_is_hidden(qtbot):
    s = VerdictStrip()
    qtbot.addWidget(s)
    assert s.isHidden()
    s.set_move_count(2)
    assert not s.isHidden() and not s.move_btn.isHidden() and s.back_btn.isHidden()
    assert s.move_btn.text() == "Move 2 frames to rejected/…"
    s.set_move_count(0)
    assert s.isHidden()


def test_the_button_labels(qtbot):
    assert move_label(1) == "Move 1 frame to rejected/…"
    assert move_label(64) == "Move 64 frames to rejected/…"
    s = VerdictStrip()
    qtbot.addWidget(s)
    s.set_back_count(3)
    assert s.back_btn.text() == "Move them back (3)" and not s.back_btn.isHidden()
    s.set_actions_enabled(False)
    assert not s.back_btn.isEnabled() and not s.move_btn.isEnabled()


# --- in Stack -------------------------------------------------------------------

def test_hidden_until_graded(qtbot, tmp_path):
    d, _ = _dialog(qtbot)
    assert d.verdict_strip.isHidden()
    d._on_graded(_night(tmp_path))
    assert not d.verdict_strip.isHidden()
    assert d.verdict_strip.headline.text() == "Good night."
    assert d.verdict_strip.details_text() == (
        "10 of 12 frames kept (2 of 2 minutes). Rejected: 2 soft. "
        "Stars: FWHM 2.5 px.")
    assert d.verdict_strip.fact_pairs() == [("Kept", "10 of 12 · 2 of 2 min"),
                                            ("Rejected", "2 soft"),
                                            ("Stars", "FWHM 2.5 px")]
    assert [l.text() for l in d.verdict_strip.fact_labels] == [
        fact_html(*pair) for pair in d.verdict_strip.fact_pairs()]
    assert d.verdict_strip.fact_labels[0].toolTip() == "10 of 12 frames kept (2 of 2 minutes)."


def test_the_star_size_comes_from_the_subs_own_header(qtbot, tmp_path):
    d, _ = _dialog(qtbot)
    d._on_graded(_night(tmp_path, cards=S30_CARDS))
    assert d._pixel_scale == pytest.approx(3.7385, abs=1e-3)
    assert "Stars about 9″ across (FWHM 2.5 px)." in d.verdict_strip.details_text()


def test_strictness_rewrites_the_verdict_but_a_tick_does_not(qtbot, tmp_path):
    d, _ = _dialog(qtbot)
    d._on_graded(_night(tmp_path))
    d.strictness_box.setCurrentText("Relaxed")
    assert d.verdict_strip.details_text().startswith("12 of 12 frames kept")
    before = d.verdict_strip.details_text()
    d.browser.set_checked(0, False)
    assert d.verdict_strip.details_text() == before, "a hand tick changed the night's verdict"
    assert d.status.text().startswith("Keeping 11 of 12")


def test_a_folder_with_no_subs_hides_the_verdict(qtbot, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    d, _ = _dialog(qtbot)
    d._on_graded(_night(tmp_path))
    d.folder_edit.setText(str(empty))
    d.grade()
    assert d.verdict_strip.isHidden()


def test_the_strip_sits_over_the_chart_across_the_dialog(qtbot, tmp_path):
    """Layout C (spec 2026-09-28 §2.4): the night band — verdict, then chart —
    across the full width, above Show/Select and the list."""
    d, _ = _dialog(qtbot)
    d.resize(1280, 800)
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(_night(tmp_path))
    b = d.browser
    assert b.layout().indexOf(d.verdict_strip) == 0
    assert b.layout().indexOf(b.chart_panel) == 1
    assert not b.splitter.isAncestorOf(d.verdict_strip)
    qtbot.waitUntil(lambda: _top(d, d.verdict_strip) < _top(d, b.chart_panel)
                    < _top(d, b.view), timeout=2000)
    assert d.verdict_strip.width() >= b.width() - 1


def test_the_strip_never_widens_the_list(qtbot, tmp_path):
    """Long button labels must not undo 'the list is only as wide as its
    columns' — least of all under ⇤ bigger preview."""
    d, _ = _dialog(qtbot)
    d.resize(1280, 800)
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(_night(tmp_path))
    d.verdict_strip.set_move_count(1234)
    d.verdict_strip.set_back_count(1234)
    d.browser.set_bigger_preview(True)
    qtbot.waitUntil(lambda: d.browser.splitter.sizes()[0]
                    <= d.browser.list_natural_width() + 1, timeout=2000)


def test_haoiii_has_no_verdict(qtbot):
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    assert d.findChildren(VerdictStrip) == []


# --- a short screen: the headline only, until asked ---------------------------

def _minimum_all_folded_graded(qtbot, folder) -> int:
    d, _ = _dialog(qtbot, stack_help_expanded=False, frame_options_folded=True)
    d.resize(1280, 700)
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(_night(folder))
    # These rooms are under CHART_ROOM_MIN, where the chart starts folded.
    d.browser.chart_panel.set_folded(True)
    need = d._settled_minimum_height()
    d.close()
    return need


def test_a_screen_too_short_even_folded_keeps_only_the_headline(qtbot, tmp_path):
    room = _minimum_all_folded_graded(qtbot, tmp_path) - 1
    d, settings = _dialog(qtbot, room=room, stack_help_expanded=True)
    d.resize(1280, 700)
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(_night(tmp_path))
    qtbot.wait(50)
    s = d.verdict_strip
    assert s.is_compact() and not s.details_shown() and s.more_btn.isVisible()
    assert s.more_btn.text() == MORE_TEXT
    assert s.headline.toolTip().startswith("Good night. 10 of 12 frames kept")
    assert d.height() <= room, f"{d.height()} px on a {room} px screen"
    assert settings.stack_help_expanded is True, "the screen must not rewrite the preference"


def test_details_asked_for_stay_open_and_the_window_stays_on_screen(qtbot, tmp_path):
    room = _minimum_all_folded_graded(qtbot, tmp_path) - 1
    d, _ = _dialog(qtbot, room=room, stack_help_expanded=True)
    d.resize(1280, 700)
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(_night(tmp_path))
    d.verdict_strip.more_btn.click()
    qtbot.wait(50)
    assert not d.verdict_strip.is_compact() and d.verdict_strip.details_shown()
    d._keep_on_screen()
    qtbot.wait(50)
    assert not d.verdict_strip.is_compact(), "folded again behind the user's back"
    assert d.height() <= room


def test_a_roomy_screen_shows_the_whole_verdict(qtbot, tmp_path):
    d, _ = _dialog(qtbot)
    d.resize(1280, 800)
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(_night(tmp_path))
    assert not d.verdict_strip.is_compact()
    assert d.verdict_strip.details_shown() and not d.verdict_strip.more_btn.isVisible()

# --- labelled facts in one row, wrapping into labelled lines (spec §2.4, §8) ---

LONG = Verdict(
    "Good night, but trailing after 00:13.",
    ("316 of 420 frames kept (53 of 70 minutes).", "Rejected: 87 trailed · 17 soft.",
     "5 are already stacked masters, left out.", "Stars about 9″ across (FWHM 2.3 px).",
     "Background brightened towards the end (moon or twilight?)."),
    (("Kept", "316 of 420 · 53 of 70 min"), ("Rejected", "87 trailed · 17 soft"),
     ("Masters", "5 left out"), ("Stars", "about 9″ (FWHM 2.3 px)"),
     ("Trend", "Background brightened towards the end (moon or twilight?)")))


def _strip(qtbot, width):
    s = VerdictStrip()
    qtbot.addWidget(s)
    s.set_verdict(LONG)
    s.set_move_count(104)
    s.resize(width, 200)
    s.show()
    qtbot.waitExposed(s)
    return s


def _lines(s):
    return sorted({w.mapTo(s, w.rect().topLeft()).y()
                   for w in [s.headline] + s.fact_labels if not w.isHidden()})


def _whole_and_labelled(s, qtbot):
    """Every fact is one labelled unit on one line; the box shows all lines."""
    line = s.fontMetrics().height()
    for label, pair in zip(s.fact_labels, LONG.facts):
        assert label.text() == fact_html(*pair)
        assert not label.wordWrap() and label.height() < 2 * line, "a fact broke in two"
    box = s.facts_box
    qtbot.waitUntil(lambda: box.height() >= box.flow.heightForWidth(box.width()),
                    timeout=2000)


def test_a_wide_strip_is_one_row_with_move_at_its_right_end(qtbot):
    s = _strip(qtbot, 2400)
    qtbot.waitUntil(lambda: len(_lines(s)) == 1, timeout=2000)
    move_left = s.move_btn.mapTo(s, s.move_btn.rect().topLeft()).x()
    assert s.move_btn.mapTo(s, s.move_btn.rect().topRight()).x() >= s.width() - 12
    assert all(l.mapTo(s, l.rect().topRight()).x() < move_left for l in s.fact_labels)
    _whole_and_labelled(s, qtbot)


def test_a_narrow_strip_wraps_whole_facts_never_a_paragraph(qtbot):
    wide = _strip(qtbot, 2400)
    qtbot.waitUntil(lambda: len(_lines(wide)) == 1, timeout=2000)
    one_line = wide.minimumSizeHint().height()
    s = _strip(qtbot, 600)
    qtbot.waitUntil(lambda: len(_lines(s)) >= 2, timeout=2000)
    _whole_and_labelled(s, qtbot)
    # What StackDialog._settled_minimum_height reads: the wrapped lines count.
    qtbot.waitUntil(lambda: s.minimumSizeHint().height() > one_line, timeout=2000)


def test_folded_to_its_headline_the_strip_is_one_line(qtbot):
    s = _strip(qtbot, 600)
    s.set_compact(True)
    assert not s.details_shown() and s.more_btn.isVisible()
    qtbot.waitUntil(lambda: len(_lines(s)) == 1, timeout=2000)
    s.more_btn.click()
    assert s.details_shown() and not s.is_compact()


@pytest.mark.parametrize("width", [800, 1280])
def test_in_the_dialog_the_facts_wrap_into_labelled_lines(qtbot, tmp_path, width):
    """Spec §8, at 1280 and at the dialog's narrowest: with both buttons and
    his longest kind of verdict, the facts wrap whole and nothing is clipped."""
    d, _ = _dialog(qtbot)
    d.resize(width, 800)
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(_night(tmp_path))
    d.verdict_strip.set_verdict(LONG)
    d.verdict_strip.set_back_count(3)
    s = d.verdict_strip
    qtbot.waitUntil(lambda: len(_lines(s)) >= 2, timeout=2000)
    _whole_and_labelled(s, qtbot)


# --- inter-fact spacing dwarfs the intra-fact gap (Ruling R7, fix round 1) ----

def test_the_gap_between_facts_dwarfs_the_gap_inside_one(qtbot):
    """26px between facts against ~4px (one space character) between a
    fact's label and its value — real geometry on both sides, not the
    literal 26, so either a shrunk between-gap or a misjudged inside-gap
    fails this."""
    s = _strip(qtbot, 2400)
    qtbot.waitUntil(lambda: len(_lines(s)) == 1, timeout=2000)
    a, b = s.fact_labels[0], s.fact_labels[1]
    between = (b.mapTo(s, b.rect().topLeft()).x()
              - a.mapTo(s, a.rect().topRight()).x())
    inside = QFontMetrics(a.font()).horizontalAdvance(" ")
    assert between >= 4 * inside, (between, inside)


@pytest.mark.parametrize("width", [800, 1280, 1920])
def test_facts_stay_whole_and_move_is_never_clipped(qtbot, width):
    """Ruling R7's wider inter-fact gap must not cost a fact its wholeness or
    push Move / Move back off the strip's right edge, at any width."""
    s = _strip(qtbot, width)
    s.set_back_count(3)
    qtbot.waitUntil(lambda: s.facts_box.height()
                    >= s.facts_box.flow.heightForWidth(s.facts_box.width()),
                    timeout=2000)
    _whole_and_labelled(s, qtbot)
    assert s.move_btn.mapTo(s, s.move_btn.rect().topRight()).x() <= s.width()
    assert s.back_btn.mapTo(s, s.back_btn.rect().topRight()).x() <= s.width()
