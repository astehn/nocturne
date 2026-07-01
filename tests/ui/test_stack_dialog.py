import pytest

pytest.importorskip("PySide6")
from seestar_processor.settings import Settings  # noqa: E402
from seestar_processor.stacking.grade import FrameStats  # noqa: E402
from seestar_processor.ui.stack_dialog import StackDialog  # noqa: E402


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
        from seestar_processor.stacking.stacker import StackResult
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
