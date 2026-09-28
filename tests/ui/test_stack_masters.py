"""Stacked masters among the subs are in no count (spec 2026-09-28 §3).

His IC 1805 folder held 5 masters beside 420 subs, and the dialog counted one
set of frames three ways: verdict 420, Show 425, Rejected 109 against Move
104. Every number on screen must agree, in both dialogs.

Ruling R1 (Andreas, 2026-09-28) extends the same treatment to a frame that
could not be measured (reason_code measure_failed): out of every count, sorts
last (after any masters), shows "—" not zeros — but the verdict still names
it apart from a master ("N could not be measured.").
"""
import os
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import Qt

from nocturne.settings import Settings
from nocturne.stacking.grade import (ONLY_MASTERS, REASON_MEASURE, REASON_NOT_RAW,
                                     FrameStats, is_left_out, is_master, judge)
from nocturne.stacking.verdict import ONLY_MASTERS_HEADLINE
from nocturne.ui import frame_browser as fb
from nocturne.ui.haoiii_dialog import HaOIIIDialog
from nocturne.ui.stack_dialog import StackDialog

T0 = datetime(2026, 9, 26, 21, 22, tzinfo=timezone.utc)


def _master(folder, k):
    """What grade_frame returns for a master in the subs folder, dated as one
    is: a stack's DATE-OBS lands before every sub, so a Time sort that did not
    special-case it would put it FIRST — the fake 21:21 atop his list."""
    s = FrameStats(os.path.join(str(folder), f"IC1805_master_{k}.fit"), 0, 0.0, 0.0,
                   0.0, False, reason_code="not_raw", reason=REASON_NOT_RAW, error=True)
    s.captured = T0 - timedelta(minutes=1)
    return s


def _unmeasured(folder, k):
    """What grade_frame returns for a sub it could not open or measure
    (Ruling R1): the same zeros as a master, and the same "in no count"
    treatment, but its own reason and its own place at the very end — after
    every master, never mixed in with them."""
    s = FrameStats(os.path.join(str(folder), f"IC1805_broken_{k}.fit"), 0, 0.0, 0.0,
                   0.0, False, reason_code="measure_failed", reason=REASON_MEASURE,
                   error=True)
    s.captured = T0 - timedelta(minutes=1)
    return s


def _night_with_masters(folder):
    """12 subs 5 minutes apart, two of them soft (rejected at Normal), and 3
    masters interleaved — not tacked on the end, where a sort bug would hide."""
    subs = []
    for i in range(12):
        s = FrameStats(os.path.join(str(folder), f"Light_{i:02d}.fit"), 800,
                       3.0 if i in (2, 5) else 2.5, 1000.0, 0.5, True, exposure=10.0)
        s.captured = T0 + timedelta(minutes=5 * i)
        subs.append(s)
    judge(subs, "normal")
    assert sum(1 for s in subs if s.reason) == 2, "fixture: two soft subs"
    stats = list(subs)
    for k, at in enumerate((0, 6, 11)):
        stats.insert(at + k, _master(folder, k))
    return stats


def _night_with_masters_and_unmeasured(folder):
    """As above, plus 2 frames that could not be measured, interleaved among
    the subs too — Ruling R1's fixture, so a fix that only special-cases
    `is_master` (and forgets `is_left_out`) is caught by a count, a sort AND
    a dash, not just one of the three."""
    stats = _night_with_masters(folder)
    for k, at in enumerate((2, 10)):
        stats.insert(at + k, _unmeasured(folder, k))
    return stats


def _stack(qtbot, stats):
    d = StackDialog(Settings())
    qtbot.addWidget(d)
    d._available_height = lambda: 4000
    d.folder_edit.setText(os.path.dirname(stats[0].path))    # Save to follows it
    d._on_graded(stats)
    return d


def _counts(browser):
    return {m: b.text() for m, b in browser._show_buttons.items()}


def test_every_count_on_screen_agrees_when_the_folder_holds_masters(qtbot, tmp_path):
    d = _stack(qtbot, _night_with_masters(tmp_path))
    assert _counts(d.browser) == {"all": "All 12", "kept": "Kept 10",
                                  "rejected": "Rejected 2"}
    verdict = d.verdict_strip.headline.toolTip()      # the whole verdict, as text
    assert "10 of 12 frames kept (2 of 2 minutes)." in verdict
    assert "3 are already stacked masters, left out." in verdict
    assert d.status.text() == "Keeping 10 of 12 frames — 2 of 2 minutes of light."
    assert d.verdict_strip.move_btn.text() == "Move 2 frames to rejected/…"
    assert d.name_edit.text() == "master_10x10s_2min.fits"


def test_every_count_on_screen_agrees_with_masters_and_unmeasured_together(qtbot, tmp_path):
    """Ruling R1: the same invariant, but the folder also holds 2 subs that
    could not be measured. Every number must still agree, and the verdict
    must still name the two kinds apart."""
    d = _stack(qtbot, _night_with_masters_and_unmeasured(tmp_path))
    assert _counts(d.browser) == {"all": "All 12", "kept": "Kept 10",
                                  "rejected": "Rejected 2"}
    verdict = d.verdict_strip.headline.toolTip()
    assert "10 of 12 frames kept (2 of 2 minutes)." in verdict
    assert "2 could not be measured." in verdict
    assert "3 are already stacked masters, left out." in verdict
    assert d.status.text() == "Keeping 10 of 12 frames — 2 of 2 minutes of light."
    assert d.verdict_strip.move_btn.text() == "Move 2 frames to rejected/…"
    assert d.name_edit.text() == "master_10x10s_2min.fits"


def test_haoiii_counts_agree_too(qtbot, tmp_path):
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    d._on_graded(_night_with_masters(tmp_path))
    assert _counts(d.browser) == {"all": "All 12", "kept": "Kept 10",
                                  "rejected": "Rejected 2"}
    assert d.status.text() == "Graded 12 frames — 10 kept."


@pytest.mark.parametrize("order", [Qt.SortOrder.AscendingOrder,
                                   Qt.SortOrder.DescendingOrder])
@pytest.mark.parametrize("col", range(len(fb.HEADERS)))
def test_masters_sort_last_whatever_is_sorted(qtbot, tmp_path, col, order):
    stats = _night_with_masters(tmp_path)
    d = _stack(qtbot, stats)
    masters = {i for i, s in enumerate(stats) if is_master(s)}
    d.browser.view.sortByColumn(col, order)
    rows = d.browser.view_rows()
    assert set(rows[-3:]) == masters, (fb.HEADERS[col], order, rows)
    if col == fb.COL_TIME:          # and the subs are still in time order
        times = [stats[r].captured for r in rows[:-3]]
        assert times == sorted(times, reverse=order == Qt.SortOrder.DescendingOrder)


@pytest.mark.parametrize("order", [Qt.SortOrder.AscendingOrder,
                                   Qt.SortOrder.DescendingOrder])
@pytest.mark.parametrize("col", range(len(fb.HEADERS)))
def test_masters_then_unmeasured_sort_last_in_that_order(qtbot, tmp_path, col, order):
    """Ruling R1: masters and unmeasured frames both trail, but not jumbled —
    the 3 masters occupy the last-3-but-2 slots and the 2 unmeasured the very
    last 2, whatever column or direction is sorted."""
    stats = _night_with_masters_and_unmeasured(tmp_path)
    d = _stack(qtbot, stats)
    masters = {i for i, s in enumerate(stats) if is_master(s)}
    unmeasured = {i for i, s in enumerate(stats) if is_left_out(s) and not is_master(s)}
    d.browser.view.sortByColumn(col, order)
    rows = d.browser.view_rows()
    assert set(rows[-5:-2]) == masters, (fb.HEADERS[col], order, rows)
    assert set(rows[-2:]) == unmeasured, (fb.HEADERS[col], order, rows)
    if col == fb.COL_TIME:          # and the subs are still in time order
        times = [stats[r].captured for r in rows[:-5]]
        assert times == sorted(times, reverse=order == Qt.SortOrder.DescendingOrder)


def test_a_master_shows_dashes_not_zeros_and_says_why(qtbot, tmp_path):
    stats = _night_with_masters(tmp_path)
    d = _stack(qtbot, stats)
    m = next(i for i, s in enumerate(stats) if is_master(s))
    for col in (fb.COL_TIME, fb.COL_STARS, fb.COL_FWHM):
        assert d.browser.cell_text(m, col) == "—", fb.HEADERS[col]
    assert d.browser.cell_text(m, fb.COL_VERDICT) == "Stacked master, left out"
    assert d.browser.cell_tooltip(m, fb.COL_STARS) == (
        f"IC1805_master_0.fit\n{REASON_NOT_RAW}")


def test_an_unmeasured_frame_shows_dashes_too_and_its_own_reason(qtbot, tmp_path):
    """Ruling R1: the same dash treatment, but the tooltip and Verdict cell
    still say "couldn't measure", never the master's wording."""
    stats = _night_with_masters_and_unmeasured(tmp_path)
    d = _stack(qtbot, stats)
    u = next(i for i, s in enumerate(stats) if is_left_out(s) and not is_master(s))
    for col in (fb.COL_TIME, fb.COL_STARS, fb.COL_FWHM):
        assert d.browser.cell_text(u, col) == "—", fb.HEADERS[col]
    assert d.browser.cell_text(u, fb.COL_VERDICT) == REASON_MEASURE
    assert d.browser.cell_tooltip(u, fb.COL_STARS) == (
        f"IC1805_broken_0.fit\n{REASON_MEASURE}")


def test_masters_show_only_under_all(qtbot, tmp_path):
    stats = _night_with_masters(tmp_path)
    b = _stack(qtbot, stats).browser
    assert len(b.view_rows()) == 15
    b.set_show(fb.SHOW_KEPT)
    assert len(b.view_rows()) == 10 and not any(is_master(stats[r]) for r in b.view_rows())
    b.set_show(fb.SHOW_REJECTED)
    assert len(b.view_rows()) == 2 and not any(is_master(stats[r]) for r in b.view_rows())


def test_masters_and_unmeasured_show_only_under_all(qtbot, tmp_path):
    stats = _night_with_masters_and_unmeasured(tmp_path)
    b = _stack(qtbot, stats).browser
    assert len(b.view_rows()) == 17
    b.set_show(fb.SHOW_KEPT)
    assert len(b.view_rows()) == 10 and not any(is_left_out(stats[r]) for r in b.view_rows())
    b.set_show(fb.SHOW_REJECTED)
    assert len(b.view_rows()) == 2 and not any(is_left_out(stats[r]) for r in b.view_rows())


def test_a_folder_of_only_masters(qtbot, tmp_path):
    """Review Focus: nothing to judge, nothing to stack — and every surface
    says so rather than showing zeros."""
    stats = [_master(tmp_path, k) for k in range(3)]
    d = _stack(qtbot, stats)
    assert _counts(d.browser) == {"all": "All 0", "kept": "Kept 0", "rejected": "Rejected 0"}
    assert d.verdict_strip.headline.text() == ONLY_MASTERS_HEADLINE
    assert d.status.text() == ONLY_MASTERS
    assert d.verdict_strip.move_btn.isHidden()
    assert d.browser.current_row() == -1 and d.browser.chart.isHidden()
    d.run()
    assert "at least 3" in d.status.text()
    h = HaOIIIDialog(Settings())
    qtbot.addWidget(h)
    h._on_graded([_master(tmp_path, k) for k in range(3)])
    assert h.status.text() == ONLY_MASTERS


def test_a_folder_of_masters_and_unmeasured_only(qtbot, tmp_path):
    """Ruling R1: a folder with nothing raw and nothing readable either —
    still says so, and still tells the two kinds apart."""
    stats = [_master(tmp_path, 0), _master(tmp_path, 1), _unmeasured(tmp_path, 0)]
    d = _stack(qtbot, stats)
    assert _counts(d.browser) == {"all": "All 0", "kept": "Kept 0", "rejected": "Rejected 0"}
    assert d.status.text() == ONLY_MASTERS
    verdict = d.verdict_strip.headline.toolTip()
    assert "No frame could be measured." in verdict
    assert "1 could not be measured." in verdict
    assert "2 are already stacked masters, left out." in verdict


def test_unticking_every_frame_keeps_the_counts_in_step(qtbot, tmp_path):
    """Review Focus: every frame left out. Select None under All unticks the
    subs; the masters were never ticked, and still count nowhere."""
    stats = _night_with_masters(tmp_path)
    d = _stack(qtbot, stats)
    d.browser.select_none()
    assert d.status.text().startswith("Keeping 0 of 12 frames")
    assert d.verdict_strip.move_btn.text() == "Move 12 frames to rejected/…"
    assert _counts(d.browser)["rejected"] == "Rejected 2", "Show follows the grader"
