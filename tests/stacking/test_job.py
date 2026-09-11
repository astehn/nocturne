"""The child process that stacks and reports over stdout.

It speaks the newline-delimited JSON protocol RC-Astro progress introduced in
v0.30.0, so the parent can read it with the same run_cli(on_line=...) stream.
"""
import io
import json

import pytest

from nocturne.stacking.job import emit, options_from_json, run_job


def _opts_text(**over):
    d = {"method": "average", "kappa": 2.5, "include": ["a.fit", "b.fit", "c.fit"],
         "output_path": "/tmp/out.fits", "autocrop": True, "pixfrac": 0.9}
    d.update(over)
    return json.dumps(d)


def test_options_round_trip_from_json():
    """StackOptions is all primitives, which is what makes the process boundary
    cheap — no marshalling layer."""
    o = options_from_json(_opts_text())
    assert o.method == "average"
    assert o.kappa == 2.5
    assert o.include == ["a.fit", "b.fit", "c.fit"]
    assert o.output_path == "/tmp/out.fits"
    assert o.autocrop is True
    assert o.pixfrac == 0.9


def test_unknown_keys_are_refused_not_ignored():
    """A silently dropped option would stack with a setting the user did not
    choose and say nothing."""
    with pytest.raises(ValueError):
        options_from_json(_opts_text(nonsense=1))


def test_emit_writes_one_json_object_per_line():
    buf = io.StringIO()
    emit({"event": "progress", "done": 41}, out=buf)
    emit({"event": "done", "output": "/tmp/out.fits"}, out=buf)
    lines = buf.getvalue().splitlines()
    assert [json.loads(ln)["event"] for ln in lines] == ["progress", "done"]


def test_a_successful_run_reports_progress_then_done(monkeypatch):
    import nocturne.stacking.job as job

    class _Result:
        output_path = "/tmp/out.fits"
        frame_count = 182
        integration_seconds = 3640.0
        rejected = [("bad.fit", "trailing")]

    def fake_run_stack(opts, *, on_progress=None):
        on_progress(1, 4, "aligning frames")
        on_progress(2, 4, "aligning frames")
        return _Result()

    monkeypatch.setattr(job, "run_stack", fake_run_stack)
    buf = io.StringIO()
    code = run_job(_opts_text(), out=buf)
    events = [json.loads(ln) for ln in buf.getvalue().splitlines()]
    assert code == 0
    assert [e["event"] for e in events] == ["progress", "progress", "done"]
    assert events[0]["done"] == 25 and events[0]["phase"] == "aligning frames"
    assert events[-1]["frames"] == 182
    assert events[-1]["output"] == "/tmp/out.fits"
    assert events[-1]["rejected"] == [["bad.fit", "trailing"]]


def test_a_failure_is_reported_as_an_error_event(monkeypatch):
    """The parent has no exception to catch across a process boundary, so the
    message has to travel as data."""
    import nocturne.stacking.job as job

    def boom(opts, *, on_progress=None):
        raise ValueError("need at least 3 frames to stack")

    monkeypatch.setattr(job, "run_stack", boom)
    buf = io.StringIO()
    code = run_job(_opts_text(), out=buf)
    events = [json.loads(ln) for ln in buf.getvalue().splitlines()]
    assert code != 0, "a failed job must exit non-zero"
    assert events[-1]["event"] == "error"
    assert "at least 3 frames" in events[-1]["message"]


def test_the_child_imports_no_qt():
    """It runs in a process with no display and no event loop. A stray Qt import
    would pull in a GUI toolkit for a batch job, and on a headless machine can
    fail outright."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[2] / "nocturne" / "stacking" / "job.py"
    text = src.read_text(encoding="utf-8")
    assert "PySide6" not in text and "QtCore" not in text


def test_main_missing_flag_emits_error_event():
    """A missing --stack-job flag must emit an error event, not a silent traceback.
    The parent cannot catch exceptions across a process boundary."""
    import nocturne.stacking.job as job
    buf = io.StringIO()
    code = job.main(["prog_name"], out=buf)
    events = [json.loads(ln) for ln in buf.getvalue().splitlines()]
    assert code != 0, "missing flag must exit non-zero"
    assert len(events) == 1
    assert events[0]["event"] == "error"
    assert "--stack-job" in events[0]["message"]


def test_main_missing_file_emits_error_event():
    """A missing or unreadable options file must emit an error event."""
    import nocturne.stacking.job as job
    buf = io.StringIO()
    code = job.main(["prog_name", "--stack-job", "/nonexistent/path.json"], out=buf)
    events = [json.loads(ln) for ln in buf.getvalue().splitlines()]
    assert code != 0, "missing file must exit non-zero"
    assert len(events) == 1
    assert events[0]["event"] == "error"


def test_emit_flushes_without_waiting_for_eof():
    """Flushing is the single constraint this module exists to honour — a buffered
    stdout would deliver an hour of progress all at once at exit, the exact hang
    problem this feature solves. Test the real contract: spawn a child that emits
    and then blocks, read from the pipe without waiting for EOF, and assert the
    line arrives."""
    import pathlib
    import subprocess
    import select

    repo_root = pathlib.Path(__file__).resolve().parents[2]
    # Create a tiny script that imports our module and emits, then sleeps forever
    script = '''
import sys
sys.path.insert(0, {!r})
from nocturne.stacking.job import emit
emit({{"event": "test", "value": 42}})
# Sleep forever — the parent reads and kills us
import time
time.sleep(3600)
'''.format(str(repo_root))

    # Run it and read one line from stdout without waiting for EOF
    proc = subprocess.Popen(
        [str(repo_root / ".venv" / "bin" / "python"), "-c", script],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    try:
        # Use a short timeout to catch if the line never appears (unbuffered failure)
        ready, _, _ = select.select([proc.stdout], [], [], 2.0)
        if not ready:
            raise TimeoutError("emit() did not flush — data still in buffer")
        line = proc.stdout.readline()
        assert line, "no output received from child"
        event = json.loads(line)
        assert event["event"] == "test"
        assert event["value"] == 42
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def test_on_progress_with_zero_total():
    """The guard 'if n else 0' must stay: on_progress(i, 0, label) must not divide
    by zero. Test the case so the guard is never removed."""
    import nocturne.stacking.job as job
    import unittest.mock

    class _Result:
        output_path = "/tmp/out.fits"
        frame_count = 1
        integration_seconds = 10.0
        rejected = []

    def fake_run_stack(opts, *, on_progress=None):
        on_progress(0, 0, "initializing")
        return _Result()

    with unittest.mock.patch.object(job, "run_stack", fake_run_stack):
        buf = io.StringIO()
        code = job.run_job(_opts_text(), out=buf)
        events = [json.loads(ln) for ln in buf.getvalue().splitlines()]
        assert code == 0
        assert events[0]["event"] == "progress"
        assert events[0]["done"] == 0  # Guard produced 0, not ZeroDivisionError
