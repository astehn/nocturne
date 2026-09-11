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
