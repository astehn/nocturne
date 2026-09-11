"""One stack at a time, in its own process.

A stack holds ~8.7 GB for a 100 MB image (TODO:708, measured on a 1233-frame
run, where an optimisation attempt moved it by nothing — 8741 MB against 8743).
Two concurrent jobs would exceed 17 GB before the app's own footprint, so the
queue runs one and makes the rest wait. That is a memory guarantee, not a
preference, and the tests below are what keep it true.

The threading is the whole risk surface, so some of these drive the real reader
thread rather than calling its callbacks from the main thread.
"""
import json
import os
import threading
import time

import pytest

from nocturne.stacking.stacker import StackOptions
from nocturne.ui.job_queue import JobQueue, StackJob


def _job(name="IC 1396A"):
    return StackJob(name, StackOptions("average", 2.5, ["a", "b", "c"],
                                       f"/tmp/{name}.fits"))


def _done(name="A"):
    return {"event": "done", "output": f"/tmp/{name}.fits", "frames": 10,
            "seconds": 100.0, "rejected": []}


class _FakeProc:
    """Stands in for a spawned child; the queue only needs these.

    `_spawn` starts a reader thread that iterates `proc.stdout` and later
    calls `proc.wait()` — without these the thread raises AttributeError in
    the background on every _spawn-exercising test.
    """
    def __init__(self, lines=(), returncode=0):
        self.killed = False
        self.returncode = returncode
        self.pid = 4242
        self.stdout = iter([str(line) for line in lines])

    def wait(self):
        return self.returncode


def _settle(qtbot, q):
    """Let a real reader thread's queued signal land while the queue is alive.

    A pending queued event whose receiver is then garbage-collected segfaults
    the next test inside pytest-qt's event pump — seen for real while mutating
    this module.
    """
    qtbot.waitUntil(lambda: q.running() is None, timeout=2000)


def _drain(q, job, proc):
    """Run the real reader thread to completion and return only then."""
    t = threading.Thread(target=q._read, args=(job, proc, "/nonexistent/opts.json"))
    t.start()
    t.join(timeout=5)
    assert not t.is_alive(), "the reader thread never finished"


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


def test_the_reader_thread_only_emits(qtbot, monkeypatch):
    """The reader must reach the queue through a queued signal and no other way.

    When it mutated state itself there was a window — clear `_running`, emit
    `changed`, re-scan the job list — in which a main-thread `enqueue()` saw an
    idle queue and spawned. Driving that interleave produced three children
    where one is allowed: 26 GB. So with the reader thread dead and the event
    loop not yet turned, nothing may have moved, and every spawn must have
    happened on the GUI thread.
    """
    spawn_threads = []

    def fake_spawn(self, job):
        spawn_threads.append(threading.get_ident())
        return _FakeProc()

    monkeypatch.setattr(JobQueue, "_spawn", fake_spawn)
    q = JobQueue()
    a, b = _job("A"), _job("B")
    q.enqueue(a)
    q.enqueue(b)

    _drain(q, a, _FakeProc([json.dumps(_done("A")) + "\n"]))

    assert a.state == "running", "the reader thread mutated the queue itself"
    assert b.state == "queued", "the reader thread promoted the next job"
    assert spawn_threads == [threading.get_ident()], \
        "a child was spawned off the GUI thread"

    qtbot.waitUntil(lambda: a.state == "done", timeout=2000)
    assert b.state == "running"
    assert spawn_threads == [threading.get_ident()] * 2


@pytest.mark.parametrize("bad", [
    "a stray print from a dependency",
    "null",                                     # valid JSON, not an object
    "123",
    "[1, 2]",
    '{"event": "something invented later"}',
    '{"event": "progress", "done": "not a number"}',
])
def test_a_bad_line_costs_one_line_not_the_job(qtbot, monkeypatch, bad):
    """A reader that dies leaves its job "running" for ever: no signal is ever
    emitted, `running()` keeps returning it, and the queue never moves again.
    So the `done` after the bad line still has to land."""
    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    q = JobQueue()
    a = _job("A")
    q.enqueue(a)
    seen = []
    q.finished.connect(lambda job, ev: seen.append(ev))

    _drain(q, a, _FakeProc([bad + "\n", json.dumps(_done("A")) + "\n"]))

    qtbot.waitUntil(lambda: a.state == "done", timeout=2000)
    assert seen and seen[0]["output"] == "/tmp/A.fits", \
        "the bad line killed the reader before the done event"


def test_the_child_leads_its_own_process_group(qtbot, monkeypatch):
    """Without `start_new_session=True`, `os.getpgid(child)` is Nocturne's OWN
    process group — so cancelling a stack SIGTERMs the app itself."""
    import nocturne.ui.job_queue as jq

    captured = {}

    def fake_popen(args, **kw):
        captured.update(kw)
        return _FakeProc()

    monkeypatch.setattr(jq.subprocess, "Popen", fake_popen)
    q = JobQueue()
    q.enqueue(_job("A"))
    assert captured.get("start_new_session") is True, (
        "the child must lead its own process group: kill_process does "
        "os.killpg(os.getpgid(pid)), which without this kills Nocturne")
    _settle(qtbot, q)


def test_a_spawn_that_fails_fails_that_job_and_carries_on(qtbot, monkeypatch):
    """Popen raises ENOMEM/EMFILE exactly when it is likeliest: right after
    8.7 GB was resident. That must not leave the queue believing for ever that
    something is running."""
    def fake_spawn(self, job):
        if job.label == "A":
            raise OSError(12, "Cannot allocate memory")
        return _FakeProc()

    monkeypatch.setattr(JobQueue, "_spawn", fake_spawn)
    q = JobQueue()
    msgs = []
    q.failed.connect(lambda job, m: msgs.append((job.label, m)))
    a, b = _job("A"), _job("B")
    q.enqueue(a)
    assert a.state == "failed"
    assert msgs and msgs[0][0] == "A"
    assert q.running() is None, "a failed spawn left the queue wedged as busy"
    q.enqueue(b)
    assert b.state == "running"


def test_a_failed_spawn_leaves_no_options_file(qtbot, monkeypatch):
    """The reader deletes the options file; if there is no reader, `_spawn` must."""
    import glob
    import tempfile
    import nocturne.ui.job_queue as jq

    pattern = os.path.join(tempfile.gettempdir(), "nocturne_job_*.json")
    before = set(glob.glob(pattern))

    def boom(args, **kw):
        raise OSError(12, "Cannot allocate memory")

    monkeypatch.setattr(jq.subprocess, "Popen", boom)
    q = JobQueue()
    q.enqueue(_job("A"))
    assert set(glob.glob(pattern)) == before


def test_the_next_job_starts_when_the_first_finishes(qtbot, monkeypatch):
    spawned = []
    monkeypatch.setattr(JobQueue, "_spawn",
                        lambda self, job: (spawned.append(job), _FakeProc())[1])
    q = JobQueue()
    a, b = _job("A"), _job("B")
    q.enqueue(a)
    q.enqueue(b)
    q._on_child_done(a, 0, _done("A"))
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


def test_cancel_waits_for_the_child_before_starting_the_next(qtbot, monkeypatch):
    """SIGTERM does not wait. Promoting the next job from `cancel` would start
    it while the killed child still held its 8.7 GB — the same memory contract
    broken by a different route. The child's own death promotes it."""
    spawned = []
    monkeypatch.setattr(JobQueue, "_spawn",
                        lambda self, job: (spawned.append(job.label), _FakeProc())[1])
    import nocturne.ui.job_queue as jq
    monkeypatch.setattr(jq, "kill_process", lambda proc: None)
    q = JobQueue()
    a, b = _job("A"), _job("B")
    q.enqueue(a)
    q.enqueue(b)
    q.cancel(a)
    assert spawned == ["A"], "the replacement started while the killed child lived"
    failures = []
    q.failed.connect(lambda job, msg: failures.append(job.label))
    q._on_child_done(a, -15, None)          # the child finally dies
    assert spawned == ["A", "B"], "the cancelled child's death wedged the queue"
    assert a.state == "cancelled" and not failures


def test_cancelling_a_queued_job_never_spawns_it(qtbot, monkeypatch):
    spawned = []
    monkeypatch.setattr(JobQueue, "_spawn",
                        lambda self, job: (spawned.append(job.label), _FakeProc())[1])
    q = JobQueue()
    a, b = _job("A"), _job("B")
    q.enqueue(a)
    q.enqueue(b)
    q.cancel(b)
    before = list(spawned)                  # capture, then assert UNCHANGED
    q._on_child_done(a, 0, _done("A"))
    assert spawned == before, "a cancelled job was started anyway"
    assert b.state == "cancelled"
    assert q.running() is None


def test_cancel_all_leaves_nothing_running_or_queued(qtbot, monkeypatch):
    """Cancelling job by job made each cancellation promote the next, so
    stopping a three-job queue started all three — four interpreters, each
    importing numpy and astropy, in answer to the user asking it to stop."""
    spawned = []
    monkeypatch.setattr(JobQueue, "_spawn",
                        lambda self, job: (spawned.append(job.label), _FakeProc())[1])
    killed = []
    import nocturne.ui.job_queue as jq
    monkeypatch.setattr(jq, "kill_process", lambda proc: killed.append(proc))
    q = JobQueue()
    for name in "ABC":
        q.enqueue(_job(name))
    q.cancel_all()
    assert spawned == ["A"], f"cancel_all spawned {spawned[1:]} in order to kill them"
    assert len(killed) == 1
    assert all(j.state == "cancelled" for j in q.jobs())
    a = q.jobs()[0]
    q._on_child_done(a, -15, None)          # the killed child dies
    assert q.running() is None
    assert spawned == ["A"]


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
    _settle(qtbot, q)


def test_wait_for_shutdown_joins_the_real_reader_thread_and_delivers_its_exit(qtbot):
    """closeEvent must not destroy the queue while a reader thread might still
    emit into it (see JobQueue.wait_for_shutdown). Proven with a REAL thread —
    every other test above exercises `_reader_threads` empty, since `_spawn`
    is monkeypatched away before it ever starts one."""
    q = JobQueue()
    a = _job("A")
    q._jobs.append(a)
    a.state = "running"
    q._running = a
    proc = _FakeProc([json.dumps(_done("A")) + "\n"])
    q._proc = proc
    t = threading.Thread(target=q._read, args=(a, proc, "/nonexistent/opts.json"))
    q._reader_threads.append(t)
    finished = []
    q.finished.connect(lambda job, ev: finished.append(job))
    t.start()

    q.wait_for_shutdown(timeout=2.0)

    assert not t.is_alive(), "wait_for_shutdown returned before the reader thread finished"
    assert q.running() is None
    assert finished == [a], "the queued _child_exited signal was never delivered"


def test_wait_for_shutdown_gives_up_after_its_bound_rather_than_hang(qtbot):
    """A reader thread wedged on a child that ignores SIGTERM must not hang
    the app on quit forever — the bound exists for exactly this."""
    q = JobQueue()
    a = _job("A")
    q._jobs.append(a)
    a.state = "running"
    q._running = a
    never_set = threading.Event()
    t = threading.Thread(target=never_set.wait)   # blocks until we release it
    q._reader_threads.append(t)
    t.start()
    try:
        start = time.monotonic()
        q.wait_for_shutdown(timeout=0.2)
        elapsed = time.monotonic() - start
        assert elapsed < 1.5, "wait_for_shutdown did not respect its bound"
        assert q.running() is None, \
            "gave up waiting on the thread, but left the stale slot behind"
    finally:
        never_set.set()
        t.join(timeout=2)
