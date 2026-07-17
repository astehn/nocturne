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
    assert dlg.table.columnCount() == 6
    assert "softer" in dlg.table.item(0, 5).text()
    assert "Brighter sky" in dlg.table.item(1, 5).text()
    assert dlg.table.item(2, 5).text() == "OK"


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
