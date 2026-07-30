import threading
import time

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


def _ready(dlg, tmp_path):
    (tmp_path / "r.json").write_text('{"version":1,"steps":[{"stage":"stretch","option":0.5}]}')
    (tmp_path / "in").mkdir(exist_ok=True)
    (tmp_path / "out").mkdir(exist_ok=True)
    dlg.recipe_edit.setText(str(tmp_path / "r.json"))
    dlg.input_edit.setText(str(tmp_path / "in"))
    dlg.output_edit.setText(str(tmp_path / "out"))


def test_cancel_button_is_hidden_until_a_run_starts(qtbot, tmp_path):
    dlg = BatchDialog(Settings())
    qtbot.addWidget(dlg)
    assert dlg.cancel_btn.isHidden()
    assert dlg.run_btn.isEnabled()


def test_run_shows_cancel_and_blocks_a_second_run(qtbot, tmp_path):
    # Two concurrent runs would write the same output filenames.
    dlg = BatchDialog(Settings())
    qtbot.addWidget(dlg)
    _ready(dlg, tmp_path)
    release = threading.Event()

    def fake_runner(recipe, paths, outdir, fmt, settings, on_progress=None, **kw):
        release.wait(timeout=5)
        return []

    dlg._batch_runner = fake_runner
    dlg.run()
    qtbot.waitUntil(lambda: not dlg.cancel_btn.isHidden(), timeout=2000)
    assert dlg.run_btn.isEnabled() is False
    release.set()
    qtbot.waitUntil(lambda: dlg.run_btn.isEnabled(), timeout=2000)
    assert dlg.cancel_btn.isHidden()


def test_cancelling_a_run_reports_progress_not_failure(qtbot, tmp_path):
    from nocturne.core.tasks import current
    dlg = BatchDialog(Settings())
    qtbot.addWidget(dlg)
    _ready(dlg, tmp_path)

    def fake_runner(recipe, paths, outdir, fmt, settings, on_progress=None, **kw):
        # Mimic run_batch: one file written, then the user cancels.
        if on_progress:
            on_progress(1, 3, "a.fit")
        tok = current()
        assert tok is not None, "the ambient token must reach the runner"
        deadline = time.monotonic() + 5          # bounded: never leak a spinning thread
        while not tok.cancelled and time.monotonic() < deadline:
            time.sleep(0.005)
        tok.check()          # raises Cancelled

    dlg._batch_runner = fake_runner
    dlg.run()
    qtbot.waitUntil(lambda: dlg.progress.value() == 1, timeout=2000)
    dlg._cancel_active()
    qtbot.waitUntil(lambda: "Cancelled" in dlg.status.text(), timeout=2000)
    assert "1 file(s) written" in dlg.status.text()
    assert "Failed" not in dlg.status.text()
    assert dlg.run_btn.isEnabled()


def test_failed_files_are_named_with_their_reason(qtbot, tmp_path):
    # run_batch already returns a per-file verdict; the dialog used to show only
    # a count, hiding every reason.
    dlg = BatchDialog(Settings())
    qtbot.addWidget(dlg)
    _ready(dlg, tmp_path)

    def fake_runner(recipe, paths, outdir, fmt, settings, on_progress=None, **kw):
        return [{"path": "/x/good.fit", "ok": True, "message": ""},
                {"path": "/x/bad.fit", "ok": False, "message": "no stars found"}]

    dlg._batch_runner = fake_runner
    dlg.run()
    qtbot.waitUntil(lambda: "Done" in dlg.status.text(), timeout=2000)
    text = dlg.status.text()
    assert "1/2 succeeded" in text
    assert "bad.fit" in text and "no stars found" in text
    assert "good.fit" not in text
