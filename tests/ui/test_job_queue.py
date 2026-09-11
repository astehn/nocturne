"""One stack at a time, in its own process.

A stack holds ~8.7 GB for a 100 MB image (TODO:708, measured on a 1233-frame
run, where an optimisation attempt moved it by nothing — 8741 MB against 8743).
Two concurrent jobs would exceed 17 GB before the app's own footprint, so the
queue runs one and makes the rest wait. That is a memory guarantee, not a
preference, and the test below is what keeps it true.
"""
import json

import pytest

from nocturne.stacking.stacker import StackOptions
from nocturne.ui.job_queue import JobQueue, StackJob


def _job(name="IC 1396A"):
    return StackJob(name, StackOptions("average", 2.5, ["a", "b", "c"],
                                       f"/tmp/{name}.fits"))


class _FakeProc:
    """Stands in for a spawned child; the queue only needs these.

    `_spawn` starts a reader thread that iterates `proc.stdout` and later
    calls `proc.wait()` — without these the thread raises AttributeError in
    the background on every _spawn-exercising test.
    """
    def __init__(self):
        self.killed = False
        self.returncode = 0
        self.pid = 4242
        self.stdout = iter(())

    def wait(self):
        return self.returncode


def test_only_one_child_runs_at_a_time(qtbot, monkeypatch):
    spawned = []

    def fake_spawn(self, job):
        spawned.append(job)
        return _FakeProc()

    monkeypatch.setattr(JobQueue, "_spawn", fake_spawn)
    q = JobQueue()
    a, b = _job("A"), _job("B")
    q.enqueue(a)
    q.enqueue(b)
    assert len(spawned) == 1, "a second child was spawned while one was running"
    assert a.state == "running" and b.state == "queued"


def test_the_next_job_starts_when_the_first_finishes(qtbot, monkeypatch):
    spawned = []
    monkeypatch.setattr(JobQueue, "_spawn",
                        lambda self, job: (spawned.append(job), _FakeProc())[1])
    q = JobQueue()
    a, b = _job("A"), _job("B")
    q.enqueue(a)
    q.enqueue(b)
    q._on_child_done(a, 0, {"event": "done", "output": "/tmp/A.fits",
                            "frames": 10, "seconds": 100.0, "rejected": []})
    assert a.state == "done"
    assert b.state == "running"
    assert [j.label for j in spawned] == ["A", "B"]


def test_progress_events_reach_the_signal(qtbot, monkeypatch):
    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    q = JobQueue()
    seen = []
    q.progress.connect(lambda job, pct, phase: seen.append((job.label, pct, phase)))
    a = _job("A")
    q.enqueue(a)
    q._on_line(a, json.dumps({"event": "progress", "done": 41,
                              "phase": "aligning frames"}))
    assert seen == [("A", 41, "aligning frames")]


def test_a_failing_job_does_not_stop_the_queue(qtbot, monkeypatch):
    """One bad folder must not cost the rest of the night's work."""
    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    q = JobQueue()
    a, b = _job("A"), _job("B")
    q.enqueue(a)
    q.enqueue(b)
    q._on_child_done(a, 1, {"event": "error", "message": "need at least 3 frames"})
    assert a.state == "failed"
    assert b.state == "running"


def test_a_child_that_dies_silently_is_reported(qtbot, monkeypatch):
    """A segfault in a dependency produces no event at all. A thread could not
    survive this; a process can, and must say so rather than hanging."""
    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    q = JobQueue()
    msgs = []
    q.failed.connect(lambda job, msg: msgs.append(msg))
    a = _job("A")
    q.enqueue(a)
    q._on_child_done(a, -11, None)          # killed by signal, no final event
    assert a.state == "failed"
    assert msgs and "-11" in msgs[0]


def test_cancelling_a_running_job_kills_the_process_group(qtbot, monkeypatch):
    """A stacker spawns its own pool workers. Killing only the child leaves them
    holding the memory this whole design exists to reclaim."""
    killed = []
    import nocturne.ui.job_queue as jq
    monkeypatch.setattr(jq, "kill_process", lambda proc: killed.append(proc))
    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    q = JobQueue()
    a = _job("A")
    q.enqueue(a)
    q.cancel(a)
    assert killed, "the child was not killed through kill_process (process GROUP)"
    assert a.state == "cancelled"


def test_cancelling_a_queued_job_never_spawns_it(qtbot, monkeypatch):
    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    q = JobQueue()
    a, b = _job("A"), _job("B")
    q.enqueue(a)
    q.enqueue(b)
    q.cancel(b)
    assert b.state == "cancelled"
    q._on_child_done(a, 0, {"event": "done", "output": "x", "frames": 1,
                            "seconds": 1.0, "rejected": []})
    assert q.running() is None, "a cancelled job was started anyway"


def test_cancel_all_leaves_nothing_running_or_queued(qtbot, monkeypatch):
    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    import nocturne.ui.job_queue as jq
    monkeypatch.setattr(jq, "kill_process", lambda proc: None)
    q = JobQueue()
    for name in "ABC":
        q.enqueue(_job(name))
    q.cancel_all()
    assert q.running() is None
    assert all(j.state == "cancelled" for j in q.jobs())


def test_spawn_builds_its_argv_with_job_command(qtbot, tmp_path, monkeypatch):
    """`_spawn` must not hand-build `[sys.executable, "--stack-job", path]` —
    that shape is only correct in the shipped .app. From source `sys.executable`
    is a bare interpreter that knows neither the flag nor the module, so this
    has to go through `job_command`, which is tested (frozen both ways) in
    tests/test_stack_job_entry.py. This test checks only that JobQueue calls
    it rather than re-deriving the command itself."""
    import nocturne.ui.job_queue as jq

    calls = []

    def fake_job_command(options_path, frozen=None):
        calls.append((options_path, frozen))
        return ["sentinel-interpreter", "--stack-job", options_path]

    captured = {}

    def fake_popen(args, **kw):
        captured["args"] = args
        return _FakeProc()

    monkeypatch.setattr(jq, "job_command", fake_job_command)
    monkeypatch.setattr(jq.subprocess, "Popen", fake_popen)
    q = JobQueue()
    q.enqueue(_job("A"))
    assert calls, "JobQueue._spawn did not call job_command()"
    assert captured["args"][0] == "sentinel-interpreter"
    assert captured["args"][1] == "--stack-job"
