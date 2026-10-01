"""End to end in the Stack window: frames moved through it carry their
measurements into the record, and a reopened folder draws them grey on the
chart — still off the list and out of the counts (2026-10-01)."""
import os
from datetime import datetime, timezone

from nocturne.settings import Settings
from nocturne.stacking import reject_move as rm
from nocturne.stacking.grade import FrameStats
from nocturne.ui.stack_dialog import StackDialog

T0 = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)


def _subs(tmp_path, n=4):
    folder = tmp_path / "VdB 141"
    folder.mkdir()
    stats = []
    for i in range(n):
        p = folder / f"Light_{i:02d}.fit"
        p.write_bytes(bytes([65 + i]) * 100)
        s = FrameStats(str(p), 800 + i, 2.4 + i / 10, 0.02, 0.5, True, exposure=10.0)
        s.captured = T0.replace(minute=i * 10)
        stats.append(s)
    return str(folder), stats


def test_moving_through_the_dialog_records_the_measurements(qtbot, tmp_path):
    folder, stats = _subs(tmp_path)
    stats[3].included, stats[3].reason = False, "Stars trailed"
    dlg = StackDialog(Settings()); qtbot.addWidget(dlg)
    dlg._stats = stats
    dlg._graded_folder = folder
    dlg.browser.set_frames(stats)
    dlg._confirm = lambda *a: True
    dlg._move_rejected()
    (h,) = rm.read_moved_history(folder)
    assert h["fwhm"] == stats[3].fwhm and h["captured"] == stats[3].captured
    assert h["reason"] == "Stars trailed" and h["star_count"] == stats[3].star_count


def test_a_reopened_folder_draws_the_moved_frames_grey_but_does_not_list_them(qtbot, tmp_path):
    folder, stats = _subs(tmp_path)
    moved = stats[3]
    rm.move_to_rejected(folder, [moved.path], [s.path for s in stats],
                        measured={os.path.abspath(moved.path): {
                            "captured": moved.captured, "fwhm": moved.fwhm,
                            "star_count": moved.star_count, "reason": "Stars trailed"}})
    # Reopened: only what is left at the top was graded.
    left = stats[:3]
    dlg = StackDialog(Settings()); qtbot.addWidget(dlg)
    dlg._stats = left
    dlg._graded_folder = folder
    dlg.browser.set_frames(left)
    dlg._sync_reject_buttons(check_disk=True)
    chart = dlg.browser.chart
    rows = [r for r, _x in chart.plotted()]
    assert len(rows) == 4, "the moved frame is back on the chart"
    from nocturne.ui.quality_chart import MOVED_COLOUR
    assert chart.point_colour(3) == MOVED_COLOUR
    assert dlg.browser.model.rowCount() == 3, "but not on the list"
    assert len(dlg._stats) == 3, "and not in what is counted or stacked"
