import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from nocturne.settings import Settings  # noqa: E402
from nocturne.stacking.grade import FrameStats, judge  # noqa: E402
from nocturne.ui.stack_dialog import StackDialog  # noqa: E402


def _stats(path, score, included=True):
    return FrameStats(path, 100, 3.0, 0.02, score, included)


def _stats2(path, score, included=True, reason="", warning="", exposure=20.0):
    s = FrameStats(path, 100, 3.0, 0.02, score, included)
    s.reason, s.warning, s.exposure = reason, warning, exposure
    return s


def test_grading_fills_table(qtbot, tmp_path):
    (tmp_path / "a.fit").write_text("x")
    (tmp_path / "b.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": [
        _stats(str(tmp_path / "a.fit"), 0.4, included=False),
        _stats(str(tmp_path / "b.fit"), 0.9, included=True),
    ]
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 2, timeout=2000)


def test_stack_calls_handoff_best_first(qtbot, tmp_path):
    for name in ("low.fit", "mid.fit", "high.fit"):
        (tmp_path / name).write_text("x")
    low, mid, high = (str(tmp_path / n) for n in ("low.fit", "mid.fit", "high.fit"))
    captured = {}
    got = {}
    dlg = StackDialog(Settings(), on_master=lambda img: got.setdefault("img", img))
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": [
        _stats(low, 0.4), _stats(mid, 0.6), _stats(high, 0.9),
    ]

    class _Img:
        pass

    def fake_stack(opts, on_progress=None):
        captured["opts"] = opts
        if on_progress:
            on_progress(1, 1, "integrating")
        from nocturne.stacking.stacker import StackResult
        return StackResult(_Img(), opts.include, [], len(opts.include), 30.0, opts.output_path)

    dlg._stack_runner = fake_stack
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 3, timeout=2000)
    dlg.output_edit.setText(str(tmp_path / "master.fits"))
    dlg.run()
    qtbot.waitUntil(lambda: "opts" in captured, timeout=2000)
    # include is best-first: highest score first
    assert captured["opts"].include[0] == high
    qtbot.waitUntil(lambda: "img" in got, timeout=2000)


def test_run_requires_output(qtbot):
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg.run()
    assert "output" in dlg.status.text().lower()


def test_dialog_closes_on_success(qtbot):
    from PySide6.QtWidgets import QDialog
    from nocturne.stacking.stacker import StackResult

    class _Img:
        pass

    handed = {}
    dlg = StackDialog(Settings(), on_master=lambda img: handed.setdefault("img", img))
    qtbot.addWidget(dlg)
    dlg._on_stacked(StackResult(_Img(), ["a", "b", "c"], [], 3, 30.0, "/x/m.fits"))
    assert "img" in handed                                   # master handed off first
    assert dlg.result() == QDialog.DialogCode.Accepted       # then dialog closed
    assert dlg._stack_btn.isEnabled()                        # busy cleared


def test_second_run_ignored_while_busy(qtbot, tmp_path):
    import threading
    for name in ("a.fit", "b.fit", "c.fit"):
        (tmp_path / name).write_text("x")
    paths = [str(tmp_path / n) for n in ("a.fit", "b.fit", "c.fit")]
    started, release, calls = threading.Event(), threading.Event(), []
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda p, on_progress=None, strictness="normal": [
        _stats(paths[0], 0.3), _stats(paths[1], 0.6), _stats(paths[2], 0.9),
    ]

    def slow_stack(opts, on_progress=None):
        calls.append(1)
        started.set()
        release.wait(2.0)
        from nocturne.stacking.stacker import StackResult
        return StackResult(object(), opts.include, [], len(opts.include), 30.0, opts.output_path)

    dlg._stack_runner = slow_stack
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 3, timeout=2000)
    dlg.output_edit.setText(str(tmp_path / "m.fits"))
    dlg.run()                                                 # dispatches, goes busy
    qtbot.waitUntil(lambda: started.is_set(), timeout=2000)
    assert dlg._stack_btn.isEnabled() is False                # button disabled while running
    dlg.run()                                                 # must be ignored (busy)
    release.set()
    qtbot.waitUntil(lambda: dlg._stack_btn.isEnabled(), timeout=2000)
    assert len(calls) == 1                                    # only one stack ran


def test_verdict_column_shows_reasons_and_warnings(qtbot, tmp_path):
    # _on_graded re-judges on arrival (I2), so the verdicts must come from
    # real FrameStats measurements that judge() actually gates on, not from
    # manually pre-set reason/warning strings.
    names = ["a.fit", "b.fit", "c.fit"] + [f"f{i}.fit" for i in range(7)]
    for name in names:
        (tmp_path / name).write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    stats = [
        FrameStats(str(tmp_path / "a.fit"), 800, 10.0, 0.02, 0.2, True, exposure=20.0),
        FrameStats(str(tmp_path / "b.fit"), 800, 2.4, 5.0, 0.8, True, exposure=20.0),
        FrameStats(str(tmp_path / "c.fit"), 800, 2.4, 0.02, 0.9, True, exposure=20.0),
    ] + [FrameStats(str(tmp_path / f"f{i}.fit"), 800, 2.4, 0.02, 0.9, True, exposure=20.0)
         for i in range(7)]
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": stats
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == len(stats), timeout=2000)
    assert dlg.table.columnCount() == 7
    from nocturne.ui.stack_dialog import _VERDICT_COL
    assert "softer" in dlg.table.item(0, _VERDICT_COL).text()
    assert "Brighter sky" in dlg.table.item(1, _VERDICT_COL).text()
    assert dlg.table.item(2, _VERDICT_COL).text() == "OK"


def test_status_line_speaks_minutes_of_light(qtbot, tmp_path):
    # _on_graded re-judges on arrival (I2), so the rejected frame must be
    # rejected by real gating (low star count -> clouds), not by a manually
    # pre-set included/reason pair.
    for i in range(5):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    stats = [FrameStats(str(tmp_path / "f0.fit"), 10, 2.4, 0.02, 0.5, True, exposure=20.0)]
    stats += [FrameStats(str(tmp_path / f"f{i}.fit"), 800, 2.4, 0.02, 0.5, True, exposure=20.0)
              for i in range(1, 5)]
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": stats
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 5, timeout=2000)
    # 4 of 5 kept x 20s = 1 of 2 minutes
    assert "Keeping 4 of 5 frames" in dlg.status.text()
    assert "minute" in dlg.status.text()


def test_strictness_rejudges_without_remeasuring(qtbot, tmp_path):
    for i in range(6):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    calls = []

    def runner(paths, on_progress=None, strictness="normal"):
        calls.append(strictness)
        return [_stats2(str(tmp_path / f"f{i}.fit"), 0.5, exposure=20.0)
                for i in range(6)]

    dlg._grade_runner = runner
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 6, timeout=2000)
    assert calls == ["normal"]
    dlg.strictness_box.setCurrentText("Strict")
    assert calls == ["normal"]          # measurement NOT re-run
    assert dlg.table.rowCount() == 6    # table re-judged in place


def test_on_graded_rejudges_with_current_strictness(qtbot, tmp_path):
    # Strictness captured at dispatch time must not win if the user changes
    # the knob before the async measurement returns. _on_graded must re-judge
    # with whatever the knob reads right now, before painting the table.
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    # A flat fwhm=2.4 base collapses to SD=0 once the single outlier is
    # iteratively clipped from upper_gate's stats, so it rejects the edge
    # frame at *every* strictness. Give the base a modest spread (as in the
    # Task-1 regression) so relaxed vs. strict actually diverge.
    stats = [FrameStats(f"f{i}.fit", 800, 2.4 + 0.3 * i / 29, 1200.0, 0.5, True)
             for i in range(30)]
    stats.append(FrameStats("edge.fit", 800, 2.9, 1200.0, 0.5, True))
    judge(stats, "relaxed")
    assert stats[-1].included is True   # relaxed keeps the edge frame

    dlg.strictness_box.setCurrentText("Strict")   # knob flipped mid-flight
    dlg._on_graded(stats)

    edge_row = len(stats) - 1
    assert dlg.table.item(edge_row, 0).checkState() == Qt.CheckState.Unchecked


def test_manual_override_survives_rejudge(qtbot, tmp_path):
    for i in range(6):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": [
        _stats2(str(tmp_path / f"f{i}.fit"), 0.5) for i in range(6)
    ]
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 6, timeout=2000)
    # user manually unchecks row 2
    dlg.table.item(2, 0).setCheckState(Qt.CheckState.Unchecked)
    assert 2 in dlg._user_touched
    dlg.strictness_box.setCurrentText("Relaxed")
    # re-judge would keep everything, but the user's choice wins:
    assert dlg.table.item(2, 0).checkState() == Qt.CheckState.Unchecked


def test_output_filename_derived_from_selection(qtbot, tmp_path):
    for i in range(3):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    stats = [_stats2(str(tmp_path / f"f{i}.fit"), 0.5, exposure=20.0)
             for i in range(3)]
    for s in stats:
        s.target = "NGC 7000"
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": stats
    dlg.folder_edit.setText(str(tmp_path))
    dlg.output_edit.setText("")          # nothing user-chosen
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 3, timeout=2000)
    assert dlg.output_edit.text() == str(tmp_path / "NGC7000_3x20s_1min.fits")


def test_user_edited_output_is_never_overwritten(qtbot, tmp_path):
    for i in range(3):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": [
        _stats2(str(tmp_path / f"f{i}.fit"), 0.5) for i in range(3)
    ]
    dlg.folder_edit.setText(str(tmp_path))
    dlg.output_edit.setText("keep-me.fits")
    dlg.output_edit.textEdited.emit("keep-me.fits")   # simulate manual typing
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 3, timeout=2000)
    assert dlg.output_edit.text() == "keep-me.fits"


def test_row_selection_requests_preview_and_caches(qtbot, tmp_path):
    import numpy as np
    for i in range(2):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": [
        _stats2(str(tmp_path / f"f{i}.fit"), 0.5) for i in range(2)
    ]
    loads = []

    def fake_loader(path):
        loads.append(path)
        return np.zeros((40, 60, 3), dtype=np.float32)

    dlg._preview_loader = fake_loader
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 2, timeout=2000)
    dlg.table.setCurrentCell(0, 1)
    qtbot.waitUntil(lambda: dlg.preview.has_image(), timeout=2000)
    assert loads == [str(tmp_path / "f0.fit")]
    dlg.table.setCurrentCell(1, 1)
    qtbot.waitUntil(lambda: len(loads) == 2, timeout=2000)
    dlg.table.setCurrentCell(0, 1)      # cached — no third load
    qtbot.wait(100)
    assert len(loads) == 2


def test_regrade_resyncs_preview_to_new_row_data(qtbot, tmp_path):
    import numpy as np
    for i in range(2):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": [
        _stats2(str(tmp_path / f"f{i}.fit"), 0.5) for i in range(2)
    ]
    loads = []

    def fake_loader(path):
        loads.append(path)
        return np.zeros((40, 60, 3), dtype=np.float32)

    dlg._preview_loader = fake_loader
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 2, timeout=2000)
    dlg.table.setCurrentCell(1, 1)
    qtbot.waitUntil(lambda: len(loads) == 1, timeout=2000)
    assert loads == [str(tmp_path / "f1.fit")]

    # grade a different folder — same row count, different paths, current cell
    # index (row 1) stays put, so currentCellChanged never fires.
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    for i in range(2):
        (other_dir / f"g{i}.fit").write_text("x")
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": [
        _stats2(str(other_dir / f"g{i}.fit"), 0.5) for i in range(2)
    ]
    dlg.folder_edit.setText(str(other_dir))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 2, timeout=2000)
    # preview must resync to the new row 1's file, not keep showing the old one
    qtbot.waitUntil(lambda: len(loads) == 2, timeout=2000)
    assert loads[-1] == str(other_dir / "g1.fit")


def test_preview_cache_is_lru_of_four(qtbot, tmp_path):
    import numpy as np
    paths = []
    for i in range(6):
        p = tmp_path / f"f{i}.fit"
        p.write_text("x")
        paths.append(str(p))
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda ps, on_progress=None, strictness="normal": [
        _stats2(p, 0.5) for p in paths
    ]
    loads = []

    def fake_loader(path):
        loads.append(path)
        return np.zeros((8, 8, 3), dtype=np.float32)

    dlg._preview_loader = fake_loader
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 6, timeout=2000)
    for row in range(5):                       # visit rows 0..4 -> 5 loads
        dlg.table.setCurrentCell(row, 1)
        qtbot.waitUntil(lambda r=row: len(loads) == r + 1, timeout=2000)
    assert len(dlg._preview_cache) == 4        # LRU capped
    dlg.table.setCurrentCell(0, 1)             # row 0 was evicted -> reloads
    qtbot.waitUntil(lambda: len(loads) == 6, timeout=2000)
    dlg.table.setCurrentCell(4, 1)             # row 4 still cached -> no load
    qtbot.wait(100)
    assert len(loads) == 6


def test_preview_cache_lru_access_order_not_fifo(qtbot, tmp_path):
    # test_preview_cache_is_lru_of_four only proves the cache is capped at 4;
    # it can't distinguish true LRU (evicts least-recently-*accessed*) from
    # plain FIFO (evicts least-recently-*inserted*). Re-visiting row 0 before
    # the 5th load must make it MRU, so the 5th load evicts row 1 (not row 0).
    import numpy as np
    paths = []
    for i in range(6):
        p = tmp_path / f"f{i}.fit"
        p.write_text("x")
        paths.append(str(p))
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda ps, on_progress=None, strictness="normal": [
        _stats2(p, 0.5) for p in paths
    ]
    loads = []

    def fake_loader(path):
        loads.append(path)
        return np.zeros((8, 8, 3), dtype=np.float32)

    dlg._preview_loader = fake_loader
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 6, timeout=2000)

    for row in range(4):                       # visit rows 0..3 -> 4 loads, cache full
        dlg.table.setCurrentCell(row, 1)
        qtbot.waitUntil(lambda r=row: len(loads) == r + 1, timeout=2000)
    assert len(dlg._preview_cache) == 4

    dlg.table.setCurrentCell(0, 1)              # re-select row 0 -> cache hit, becomes MRU
    qtbot.wait(100)
    assert len(loads) == 4                      # no new load

    dlg.table.setCurrentCell(4, 1)              # 5th load -> must evict row 1, not row 0
    qtbot.waitUntil(lambda: len(loads) == 5, timeout=2000)

    dlg.table.setCurrentCell(0, 1)              # still cached -> FIFO would have evicted it
    qtbot.wait(100)
    assert len(loads) == 5                      # no new load

    dlg.table.setCurrentCell(1, 1)              # row 1 was evicted -> new load
    qtbot.waitUntil(lambda: len(loads) == 6, timeout=2000)


def test_stack_report_names_unregistered_frames(qtbot):
    from nocturne.stacking.stacker import StackResult
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    result = StackResult(
        image=None, used=["/x/a.fit", "/x/b.fit", "/x/c.fit"],
        rejected=[("/x/d.fit", "registration failed: no match"),
                  ("/x/e.fit", "unreadable: bad header")],
        frame_count=3, integration_seconds=60.0, output_path="/x/out.fits")
    text = dlg._stack_report(result)
    assert "3 frames" in text
    assert "d.fit" in text and "couldn't be aligned" in text
    assert "e.fit" in text


def test_splitter_holds_table_and_preview(qtbot):
    from PySide6.QtWidgets import QSplitter
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    assert isinstance(dlg.splitter, QSplitter)
    assert dlg.splitter.count() == 2
    assert dlg.splitter.widget(0) is dlg.table
    assert dlg.splitter.widget(1) is dlg.preview


def test_dialog_opens_roomy_and_resizable(qtbot):
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    assert (dlg.width(), dlg.height()) == (1100, 700)
    assert (dlg.minimumWidth(), dlg.minimumHeight()) == (800, 500)


def test_cancel_button_stops_a_grade(qtbot, tmp_path):
    import time
    from nocturne.core.tasks import current

    (tmp_path / "a.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)

    def slow_grade(paths, on_progress=None, strictness="normal"):
        for _ in range(200):
            tok = current()
            if tok is not None:
                tok.check()            # raises Cancelled when cancelled
            time.sleep(0.01)
        return []

    dlg._grade_runner = slow_grade
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg._active_token is not None, timeout=1000)
    dlg._cancel_btn.click()
    qtbot.waitUntil(lambda: not dlg._busy, timeout=3000)
    assert "Cancelled" in dlg.status.text()          # clean stop, not "Failed"
    assert dlg._active_token is None


def test_cells_carry_tooltips(qtbot, tmp_path):
    for i in range(3):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": [
        _stats2(str(tmp_path / f"f{i}.fit"), 0.5) for i in range(3)
    ]
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 3, timeout=2000)
    item = dlg.table.item(0, 5)
    assert item.toolTip() == item.text() != ""


def test_round_column_shows_elongation_and_survives_a_rejudge(qtbot, tmp_path):
    """A "stars trailed" verdict is unreadable without the number behind it, so
    elongation gets its own column. It also guards the off-by-one that adding
    that column created: _rejudge rewrites the verdict cell by index, and with a
    literal 5 it would now overwrite Bg instead."""
    from nocturne.stacking.grade import FrameStats
    from nocturne.ui.stack_dialog import StackDialog, _VERDICT_COL

    for i in range(10):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    stats = [FrameStats(str(tmp_path / f"f{i}.fit"), 800, 2.4, 0.02, 0.9, True,
                        elongation=1.05, exposure=20.0) for i in range(9)]
    stats.append(FrameStats(str(tmp_path / "f9.fit"), 800, 2.4, 0.02, 0.9, True,
                            elongation=1.90, exposure=20.0))
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": stats
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == len(stats), timeout=2000)

    trailed = next(r for r in range(dlg.table.rowCount())
                   if dlg.table.item(r, 4).text() == "1.90")
    assert "trailed" in dlg.table.item(trailed, _VERDICT_COL).text().lower()
    assert dlg.table.item(trailed, 5).text() == "0.020", "Bg column was overwritten"

    dlg.strictness_box.setCurrentText("Relaxed")
    assert dlg.table.item(trailed, 5).text() == "0.020", \
        "_rejudge wrote the verdict into the wrong column"


def test_framing_checkbox_reaches_the_stacker(qtbot, tmp_path):
    """Andreas preferred the uncropped master (2026-08-04): with coverage-aware
    integration and normalization the fringe is correctly exposed, just noisier,
    and on a 2 MP sensor those pixels are worth keeping. The choice is only
    real if it actually travels to run_stack — a checkbox wired to nothing looks
    identical from the outside."""
    from nocturne.stacking.grade import FrameStats
    from nocturne.stacking.stacker import StackResult
    from nocturne.ui.stack_dialog import StackDialog

    seen = {}

    def fake_stack(opts, on_progress=None):
        seen["autocrop"] = opts.autocrop
        return StackResult(object(), opts.include, [], len(opts.include), 30.0,
                           opts.output_path)

    for name in ("a.fit", "b.fit", "c.fit"):
        (tmp_path / name).write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    stats = [FrameStats(str(tmp_path / n), 800, 2.4, 0.02, 0.9, True, exposure=20.0)
             for n in ("a.fit", "b.fit", "c.fit")]
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": stats
    dlg._stack_runner = fake_stack
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 3, timeout=2000)
    dlg.output_edit.setText(str(tmp_path / "m.fits"))

    assert dlg.crop_check.isChecked(), "trimming stays the default"
    dlg.crop_check.setChecked(False)
    dlg.run()
    qtbot.waitUntil(lambda: "autocrop" in seen, timeout=3000)
    assert seen["autocrop"] is False, "the framing choice never reached run_stack"

    seen.clear()
    dlg.crop_check.setChecked(True)
    dlg.run()
    qtbot.waitUntil(lambda: "autocrop" in seen, timeout=3000)
    assert seen["autocrop"] is True


# --- mosaic ------------------------------------------------------------------

def _sub_with_pointing(tmp_path, name, ra, dec):
    import numpy as np
    from tests.stacking.synthetic import make_star_field, write_color_fits
    p = tmp_path / name
    write_color_fits(p, make_star_field(shape=(40, 40), seed=1), exptime=10.0,
                     header={"RA": ra, "DEC": dec})
    return str(p)


def test_mosaic_option_is_offered_when_the_subs_span_several_pointings(qtbot, tmp_path):
    """A user who shot a mosaic should be told so. Nothing in the dialog
    currently distinguishes 400 subs of one field from 400 across twenty."""
    paths = [_sub_with_pointing(tmp_path, f"a{i}.fit", 10.0, 41.0) for i in range(3)]
    paths += [_sub_with_pointing(tmp_path, f"b{i}.fit", 10.0, 43.0) for i in range(3)]

    settings = Settings()
    settings.astap_path = str(tmp_path / "astap")
    (tmp_path / "astap").write_text("#!/bin/sh\n")
    (tmp_path / "astap").chmod(0o755)   # a real tool is EXECUTABLE, not merely present

    dlg = StackDialog(settings)
    qtbot.addWidget(dlg)
    dlg.folder_edit.setText(str(tmp_path))
    dlg.scan_pointings()

    assert dlg.mosaic_check.isEnabled()
    assert "2" in dlg.mosaic_check.text(), dlg.mosaic_check.text()


def test_mosaic_option_stays_off_for_a_single_pointing(qtbot, tmp_path):
    """One field is an ordinary stack. Offering a mosaic there would invite a
    slower, worse result for no reason."""
    for i in range(4):
        _sub_with_pointing(tmp_path, f"a{i}.fit", 10.0, 41.0)

    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg.folder_edit.setText(str(tmp_path))
    dlg.scan_pointings()

    assert not dlg.mosaic_check.isEnabled()
    assert not dlg.mosaic_check.isChecked()


def test_mosaic_says_it_needs_astap_when_there_is_none(qtbot, tmp_path):
    """Mosaic geometry comes from plate solving. Without ASTAP the honest move
    is to say so, not to fall back to something worse in silence."""
    paths = [_sub_with_pointing(tmp_path, f"a{i}.fit", 10.0, 41.0) for i in range(3)]
    paths += [_sub_with_pointing(tmp_path, f"b{i}.fit", 10.0, 43.0) for i in range(3)]

    settings = Settings()
    settings.astap_path = ""
    dlg = StackDialog(settings)
    qtbot.addWidget(dlg)
    dlg.folder_edit.setText(str(tmp_path))
    dlg.scan_pointings()

    assert not dlg.mosaic_check.isEnabled()
    assert "ASTAP" in dlg.mosaic_check.toolTip()


def test_stacking_with_mosaic_checked_runs_the_mosaic_path(qtbot, tmp_path):
    """The checkbox must actually change what runs — a control that looks right
    and does nothing is the specific failure worth guarding."""
    paths = [_sub_with_pointing(tmp_path, f"a{i}.fit", 10.0, 41.0) for i in range(3)]
    paths += [_sub_with_pointing(tmp_path, f"b{i}.fit", 10.0, 43.0) for i in range(3)]

    settings = Settings()
    settings.astap_path = str(tmp_path / "astap")
    (tmp_path / "astap").write_text("#!/bin/sh\n")
    (tmp_path / "astap").chmod(0o755)

    dlg = StackDialog(settings)
    qtbot.addWidget(dlg)
    dlg.folder_edit.setText(str(tmp_path))
    dlg.output_edit.setText(str(tmp_path / "out.fits"))
    dlg._on_graded([_stats2(p, 0.9) for p in paths])       # fills the table
    dlg.scan_pointings()
    dlg.mosaic_check.setChecked(True)

    seen = {}
    def fake_mosaic(opts, on_progress=None):
        seen["opts"] = opts
        raise RuntimeError("stop here — only the routing is under test")
    dlg._mosaic_runner = fake_mosaic
    dlg._stack_runner = lambda *a, **k: pytest.fail("must not run the plain stacker")

    dlg.run()
    qtbot.waitUntil(lambda: "opts" in seen, timeout=3000)
    assert seen["opts"].astap_path == str(tmp_path / "astap")
    assert len(seen["opts"].include) == 6


def test_progress_counts_panels_not_frames_during_a_mosaic(qtbot, tmp_path):
    """The mosaic's phases count panels. Reporting "6/38 frames" while placing
    panel 6 of 38 is simply wrong, and on a forty-minute run the progress line
    is most of what the user has to go on."""
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)

    dlg._on_progress(6, 38, "Step 3 of 3 — placing panel 6")
    assert "6/38 panels" in dlg.status.text(), dlg.status.text()

    dlg._on_progress(5, 20, "Step 1 of 3 — aligning frames")
    assert "5/20 frames" in dlg.status.text(), dlg.status.text()


def test_a_mosaic_is_named_a_mosaic(qtbot, tmp_path):
    """M31_302x10s_50min.fits does not say the one thing that makes this file
    different from every other master in the folder."""
    settings = Settings()
    settings.astap_path = str(tmp_path / "astap")
    (tmp_path / "astap").write_text("#!/bin/sh\n")
    (tmp_path / "astap").chmod(0o755)   # a real tool is EXECUTABLE, not merely present

    dlg = StackDialog(settings)
    qtbot.addWidget(dlg)
    dlg.folder_edit.setText(str(tmp_path))
    stats = [_stats2(str(tmp_path / f"s{i}.fit"), 0.9, exposure=10.0) for i in range(4)]
    for s in stats:
        s.target = "M 31"
    dlg._on_graded(stats)

    import os
    plain = os.path.basename(dlg.output_edit.text())
    assert "mosaic" not in plain.lower()

    dlg.mosaic_check.setEnabled(True)
    dlg.mosaic_check.setChecked(True)
    named = os.path.basename(dlg.output_edit.text())
    assert "mosaic" in named.lower(), named
    assert named.startswith("M31_mosaic_"), named


def test_turning_the_mosaic_option_off_takes_the_word_back_out(qtbot, tmp_path):
    settings = Settings()
    settings.astap_path = str(tmp_path / "astap")
    (tmp_path / "astap").write_text("#!/bin/sh\n")
    (tmp_path / "astap").chmod(0o755)   # a real tool is EXECUTABLE, not merely present
    dlg = StackDialog(settings)
    qtbot.addWidget(dlg)
    dlg.folder_edit.setText(str(tmp_path))
    stats = [_stats2(str(tmp_path / f"s{i}.fit"), 0.9, exposure=10.0) for i in range(4)]
    for s in stats:
        s.target = "M 31"
    dlg._on_graded(stats)
    dlg.mosaic_check.setEnabled(True)

    import os
    dlg.mosaic_check.setChecked(True)
    dlg.mosaic_check.setChecked(False)
    assert "mosaic" not in os.path.basename(dlg.output_edit.text()).lower()


def test_a_hand_typed_output_name_is_never_overwritten(qtbot, tmp_path):
    """The mosaic rename must respect the existing rule: once the user edits the
    path, the dialog stops touching it."""
    settings = Settings()
    settings.astap_path = str(tmp_path / "astap")
    (tmp_path / "astap").write_text("#!/bin/sh\n")
    (tmp_path / "astap").chmod(0o755)   # a real tool is EXECUTABLE, not merely present
    dlg = StackDialog(settings)
    qtbot.addWidget(dlg)
    dlg.folder_edit.setText(str(tmp_path))
    dlg._on_graded([_stats2(str(tmp_path / "s0.fit"), 0.9, exposure=10.0)])

    dlg.output_edit.setText("/tmp/my_name.fits")
    dlg._mark_output_edited("/tmp/my_name.fits")
    dlg.mosaic_check.setEnabled(True)
    dlg.mosaic_check.setChecked(True)
    assert dlg.output_edit.text() == "/tmp/my_name.fits"


def test_the_reference_frame_is_first_in_the_stack_order(qtbot, tmp_path):
    """run_stack aligns everything to paths[0], so whatever leads the list IS
    the reference. Ordering purely by score put a SOFT frame there whenever
    transparency varied — see grade.pick_reference for the four real sessions
    measured, where the score's correlation with FWHM inverted on the difficult
    one and chose a reference 38% softer than the sharpest available."""
    from nocturne.stacking.grade import FrameStats
    from nocturne.ui.stack_dialog import StackDialog
    from nocturne.settings import Settings

    d = StackDialog(Settings())
    qtbot.addWidget(d)
    # the difficult-session pattern: the frames with the most stars are the soft ones
    stats = [FrameStats(f"soft{i}.fit", 850, 2.95, 0.001, 0.0, True, elongation=1.10)
             for i in range(5)]
    stats += [FrameStats(f"sharp{i}.fit", 600, 2.15, 0.001, 0.0, True, elongation=1.10)
              for i in range(5)]
    for s in stats:
        s.score = s.star_count * (1.0 / (1.0 + s.fwhm)) / s.elongation

    d._on_graded(stats)                      # the real path: judges and fills the table
    paths = d._included_paths_best_first()

    assert paths, "no frames were selected"
    assert paths[0].startswith("sharp"), (
        f"the reference is {paths[0]} — a soft frame leads the stack order")
    assert len(paths) == 10, "the fix must not drop or duplicate frames"
    assert len(set(paths)) == 10, "a frame appears twice"


@pytest.fixture
def no_modal(monkeypatch):
    """Stop a finished stack opening a MODAL box that never gets clicked.

    `_on_stacked` shows QMessageBox.information when anything was skipped, and a
    modal in a headless run blocks forever — this hung the suite for ten minutes
    before it was noticed. Any test that exercises the skipped-frames path needs
    this.
    """
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: shown.append(a[-1] if a else ""))
    return shown


def _dialog(qtbot, _tmp_path):
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    return dlg


def _mosaic_result(dropped=None):
    from nocturne.stacking.mosaic import MosaicResult
    from nocturne.core.image import AstroImage
    import numpy as np
    return MosaicResult(
        image=AstroImage(np.zeros((8, 8, 3), np.float32), is_linear=True, metadata={}),
        panel_count=4, frame_count=284, integration_seconds=2840.0,
        dropped=list(dropped or []), output_path="/tmp/mosaic.fits")


def test_a_finished_mosaic_reaches_the_editor_like_any_other_stack(qtbot, tmp_path, no_modal):
    """A mosaic used to finish and go nowhere.

    Both paths share `_on_stacked`, which builds a report BEFORE handing the
    image over — and the report read `result.rejected`, which only StackResult
    has. MosaicResult calls the same thing `dropped`, so a finished mosaic
    raised AttributeError in the completion handler: no image in the editor, and
    the dialog left open for the user to close and reopen the file by hand.

    Andreas reported it as an annoyance; it was an unhandled exception.
    """
    dlg = _dialog(qtbot, tmp_path)
    handed = []
    dlg._on_master = handed.append

    dlg._on_stacked(_mosaic_result())

    assert handed, "the finished mosaic never reached the editor"
    assert handed[0].data.shape == (8, 8, 3)
    from PySide6.QtWidgets import QDialog
    assert dlg.result() == QDialog.DialogCode.Accepted.value, \
        "the dialog should close itself, as it does for an ordinary stack"


def test_the_mosaic_report_counts_panels_not_just_frames(qtbot, tmp_path, no_modal):
    """'Done — stacked 284 frames' is true but useless for a mosaic: what the
    user wants to know is how many pointings were assembled."""
    dlg = _dialog(qtbot, tmp_path)
    dlg._on_master = lambda _img: None
    dlg._on_stacked(_mosaic_result())
    text = dlg.status.text()
    assert "4" in text and "panel" in text.lower(), text
    assert "284" in text


def test_a_dropped_panel_is_reported_to_the_user(qtbot, tmp_path, no_modal):
    """Panels that could not be stacked or solved are REPORTED, not silently
    missing — a mosaic with a hole in it should say why."""
    dlg = _dialog(qtbot, tmp_path)
    dlg._on_master = lambda _img: None
    dlg._on_stacked(_mosaic_result(
        dropped=[("/x/panel3.fits", "panel could not be solved")]))
    text = dlg.status.text()
    assert "panel3" in text or "1" in text, text
