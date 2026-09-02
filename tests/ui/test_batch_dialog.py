import threading
import time

import pytest

pytest.importorskip("PySide6")
from nocturne.settings import Settings  # noqa: E402
from nocturne.ui.batch_dialog import BatchDialog  # noqa: E402


def test_batch_dialog_runs_with_fake_runner(qtbot, tmp_path):
    (tmp_path / "r.json").write_text('{"version":1,"steps":[{"stage":"stretch","option":0.5}]}')
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "a.fits").write_bytes(b"")   # an empty folder is refused now
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
    # A run needs something to run on: an empty input folder is now refused
    # rather than reported as "0/0 succeeded". The runner is faked in these
    # tests, so the file is never opened.
    (tmp_path / "in" / "a.fits").write_bytes(b"")
    dlg.recipe_edit.setText(str(tmp_path / "r.json"))
    dlg.input_edit.setText(str(tmp_path / "in"))
    dlg.output_edit.setText(str(tmp_path / "out"))


def test_cancel_button_is_hidden_until_a_run_starts(qtbot, tmp_path):
    dlg = BatchDialog(Settings())
    qtbot.addWidget(dlg)
    assert dlg.cancel_btn.isHidden()
    assert dlg.run_btn.isEnabled()


def test_run_shows_cancel_and_blocks_a_second_run(qtbot, tmp_path):
    # Two concurrent runs would write the same output filenames. Calling run()
    # again is the real test — a disabled QPushButton stops clicks, but not a
    # shortcut, a duplicate connect, or a programmatic call.
    dlg = BatchDialog(Settings())
    qtbot.addWidget(dlg)
    _ready(dlg, tmp_path)
    release = threading.Event()
    starts = []

    def fake_runner(recipe, paths, outdir, fmt, settings, on_progress=None, **kw):
        starts.append(True)
        release.wait(timeout=5)
        return []

    dlg._batch_runner = fake_runner
    dlg.run()
    qtbot.waitUntil(lambda: len(starts) == 1, timeout=2000)
    assert not dlg.cancel_btn.isHidden()
    assert dlg.run_btn.isEnabled() is False

    dlg.run()                      # second run, bypassing the button entirely
    dlg.run()
    release.set()
    qtbot.waitUntil(lambda: dlg.run_btn.isEnabled(), timeout=2000)
    assert len(starts) == 1, "a second worker started while one was in flight"
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


def test_run_refuses_up_front_when_every_file_would_overwrite_itself(qtbot, tmp_path):
    # Friendlier than fifty identical per-file failures after the fact.
    dlg = BatchDialog(Settings())
    qtbot.addWidget(dlg)
    _ready(dlg, tmp_path)
    indir = tmp_path / "in"
    (indir / "m42.fits").write_bytes(b"")
    (indir / "ngc281.fits").write_bytes(b"")
    dlg.output_edit.setText(str(indir))          # output folder == input folder
    dlg.format_box.setCurrentText("FITS")
    started = []
    dlg._batch_runner = lambda *a, **k: started.append(True) or []
    dlg.run()
    assert "overwrite" in dlg.status.text().lower()
    assert "output folder or format" in dlg.status.text()
    # Refused before any worker was spun up at all, not merely before it landed.
    assert dlg._active_token is None
    assert dlg.run_btn.isEnabled()
    qtbot.wait(100)
    assert started == [], "processing began despite every file colliding"


def test_a_partial_collision_still_runs(qtbot, tmp_path):
    # Only SOME files colliding is run_batch's business, per file — the dialog
    # must not refuse the whole batch and strand the files that are fine.
    dlg = BatchDialog(Settings())
    qtbot.addWidget(dlg)
    _ready(dlg, tmp_path)
    indir = tmp_path / "in"
    (indir / "m42.fits").write_bytes(b"")
    (indir / "ngc281.fit").write_bytes(b"")      # exports to ngc281.fits — no collision
    dlg.output_edit.setText(str(indir))
    dlg.format_box.setCurrentText("FITS")
    started = []
    dlg._batch_runner = lambda *a, **k: started.append(True) or []
    dlg.run()
    qtbot.waitUntil(lambda: started == [True], timeout=2000)


def test_an_input_folder_with_no_images_says_so_and_does_not_run(qtbot, tmp_path):
    # Was: "Done — 0/0 succeeded", which reads as success.
    dlg = BatchDialog(Settings())
    qtbot.addWidget(dlg)
    _ready(dlg, tmp_path)
    tiffs = tmp_path / "tiffs"
    tiffs.mkdir()
    (tiffs / "m42.tiff").write_bytes(b"")
    dlg.input_edit.setText(str(tiffs))
    started = []
    dlg._batch_runner = lambda *a, **k: started.append(True) or []
    dlg.run()
    text = dlg.status.text()
    assert str(tiffs) in text, text                    # names the folder it looked in
    assert "0/0" not in text and "succeeded" not in text
    assert dlg._active_token is None
    qtbot.wait(100)
    assert started == [], "a run started on an empty input folder"


def test_the_empty_folder_message_lists_the_extensions_the_glob_actually_uses(qtbot, tmp_path):
    # Teeth against drift: the message and the glob must read from one list, or
    # the message becomes a confident lie the day a format is added.
    from nocturne.ui.batch_dialog import _INPUT_PATTERNS
    dlg = BatchDialog(Settings())
    qtbot.addWidget(dlg)
    _ready(dlg, tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    dlg.input_edit.setText(str(empty))
    dlg._batch_runner = lambda *a, **k: []
    dlg.run()
    text = dlg.status.text()
    assert _INPUT_PATTERNS, "the glob patterns must be a shared constant"
    for pat in _INPUT_PATTERNS:
        assert pat.lstrip("*") in text, f"{pat} missing from: {text}"


def _write_recipe(tmp_path, steps):
    import json
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"version": 1, "steps": steps}))
    return str(p)


def test_the_dialog_says_what_the_recipe_will_actually_do(qtbot, tmp_path):
    """Not blocked is not the same as "will do what you saved". Six of the eight
    tool-backed stages fall back to a free implementation without saying so, and
    a batch is the worst place to find that out — a whole folder is already
    done by then."""
    d = _dialog(qtbot, tmp_path) if "_dialog" in globals() else None
    if d is None:
        from nocturne.ui.batch_dialog import BatchDialog
        from nocturne.settings import Settings
        d = BatchDialog(Settings())
        qtbot.addWidget(d)
    d.recipe_edit.setText(_write_recipe(tmp_path, [
        {"stage": "stretch", "option": 0.6},
        {"stage": "star_reduction", "option": 0.4}]))
    text = d.status.text()
    assert "substitute" in text and "Star Reduction" in text
    assert d.run_btn.isEnabled(), "a substitution must not block the run"


def test_a_recipe_that_runs_as_saved_says_so(qtbot, tmp_path):
    from nocturne.ui.batch_dialog import BatchDialog
    from nocturne.settings import Settings
    d = BatchDialog(Settings())
    qtbot.addWidget(d)
    d.recipe_edit.setText(_write_recipe(tmp_path, [{"stage": "stretch", "option": 0.6}]))
    assert "will run as saved" in d.status.text()


def test_a_blocking_tool_still_wins_over_the_plan(qtbot, tmp_path):
    """The block is the actionable message; the plan must not replace it."""
    from nocturne.ui.batch_dialog import BatchDialog
    from nocturne.settings import Settings
    d = BatchDialog(Settings())
    qtbot.addWidget(d)
    d.recipe_edit.setText(_write_recipe(tmp_path, [{"stage": "background", "option": "strong"}]))
    assert "GraXpert" in d.status.text()
    assert d.run_btn.isEnabled() is False
