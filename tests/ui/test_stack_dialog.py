import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from nocturne.settings import Settings  # noqa: E402
from nocturne.stacking.grade import FrameStats  # noqa: E402
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
    for name in ("a.fit", "b.fit", "c.fit"):
        (tmp_path / name).write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": [
        _stats2(str(tmp_path / "a.fit"), 0.2, included=False,
                reason="Stars softer than the rest of the session (FWHM 3.5 vs limit 3.0)"),
        _stats2(str(tmp_path / "b.fit"), 0.8, warning="Brighter sky (twilight, moon or light pollution) — kept"),
        _stats2(str(tmp_path / "c.fit"), 0.9),
    ]
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 3, timeout=2000)
    assert dlg.table.columnCount() == 6
    assert "softer" in dlg.table.item(0, 5).text()
    assert "Brighter sky" in dlg.table.item(1, 5).text()
    assert dlg.table.item(2, 5).text() == "OK"


def test_status_line_speaks_minutes_of_light(qtbot, tmp_path):
    for i in range(4):
        (tmp_path / f"f{i}.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    stats = [_stats2(str(tmp_path / f"f{i}.fit"), 0.5 + 0.1 * i) for i in range(4)]
    stats[0].included = False
    stats[0].reason = "Very few stars — likely clouds or trailing"
    dlg._grade_runner = lambda paths, on_progress=None, strictness="normal": stats
    dlg.folder_edit.setText(str(tmp_path))
    dlg.grade()
    qtbot.waitUntil(lambda: dlg.table.rowCount() == 4, timeout=2000)
    # 3 of 4 kept x 20s = 1 of 1 minute
    assert "Keeping 3 of 4 frames" in dlg.status.text()
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
