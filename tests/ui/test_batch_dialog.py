import pytest

pytest.importorskip("PySide6")
from nocturne.settings import Settings  # noqa: E402
from nocturne.ui.batch_dialog import BatchDialog  # noqa: E402


def test_batch_dialog_runs_with_fake_runner(qtbot, tmp_path):
    (tmp_path / "r.json").write_text('{"version":1,"steps":[{"stage":"stretch","option":0.5}]}')
    (tmp_path / "in").mkdir()
    (tmp_path / "out").mkdir()
    dlg = BatchDialog(Settings())
    qtbot.addWidget(dlg)
    captured = {}

    def fake_runner(recipe, paths, outdir, fmt, settings, on_progress=None, **kw):
        captured["fmt"] = fmt
        if on_progress:
            on_progress(1, 1, "x")
        return [{"path": "x", "ok": True, "message": ""}]

    dlg._batch_runner = fake_runner
    dlg.recipe_edit.setText(str(tmp_path / "r.json"))
    dlg.input_edit.setText(str(tmp_path / "in"))
    dlg.output_edit.setText(str(tmp_path / "out"))
    dlg.format_box.setCurrentText("PNG")
    dlg.run()
    qtbot.waitUntil(lambda: "fmt" in captured, timeout=2000)
    assert captured["fmt"] == "PNG"
    qtbot.waitUntil(lambda: "Done" in dlg.status.text(), timeout=2000)


def test_batch_dialog_requires_recipe_and_output(qtbot):
    dlg = BatchDialog(Settings())
    qtbot.addWidget(dlg)
    dlg.run()  # nothing filled in
    assert "Pick" in dlg.status.text()
