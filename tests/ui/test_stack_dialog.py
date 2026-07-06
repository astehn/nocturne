import pytest

pytest.importorskip("PySide6")
from nocturne.settings import Settings  # noqa: E402
from nocturne.stacking.grade import FrameStats  # noqa: E402
from nocturne.ui.stack_dialog import StackDialog  # noqa: E402


def _stats(path, score, included=True):
    return FrameStats(path, 100, 3.0, 0.02, score, included)


def test_grading_fills_table(qtbot, tmp_path):
    (tmp_path / "a.fit").write_text("x")
    (tmp_path / "b.fit").write_text("x")
    dlg = StackDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._grade_runner = lambda paths, on_progress=None: [
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
    dlg._grade_runner = lambda paths, on_progress=None: [
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
    dlg._grade_runner = lambda p, on_progress=None: [
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
