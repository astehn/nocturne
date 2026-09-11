"""The two modes, and the rule that a finished stack never replaces open work."""
import json
import threading

import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.stacking.stacker import StackOptions
from nocturne.ui.job_queue import JobQueue, StackJob


class _FakeProc:
    def __init__(self):
        self.returncode = None
        self.pid = 1


def _job(name="IC 1396A"):
    return StackJob(name, StackOptions("average", 2.5, ["a", "b", "c"],
                                       f"/tmp/{name}.fits"))


def test_progress_reaches_the_log_at_intervals_not_every_tick(qtbot, tmp_path, monkeypatch):
    """Andreas asked for progress in the log. The log is append-only, and a job
    reporting every two seconds for an hour would bury everything else in it —
    so it goes in at every 10%, plus start and finish."""
    from tests.ui.test_main_window import _window

    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    win = _window(qtbot, tmp_path)
    job = _job()
    win._job_queue.enqueue(job)
    before = win.log_panel.toPlainText()
    for pct in range(0, 31):
        win._job_queue._on_line(job, json.dumps({"event": "progress",
                                                 "done": pct, "phase": "aligning"}))
    added = win.log_panel.toPlainText()[len(before):]
    assert added.count("IC 1396A") <= 4, f"the log is being flooded:\n{added}"
    assert "10%" in added and "20%" in added and "30%" in added


def test_a_finished_background_job_logs_and_does_not_open(qtbot, tmp_path, monkeypatch):
    from tests.ui.test_main_window import _make_fits, _window

    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    open_before = win.project.current().data.copy()
    job = _job()
    win._job_queue.enqueue(job)
    win._job_queue._on_child_done(job, 0, {"event": "done", "output": "/tmp/m.fits",
                                           "frames": 182, "seconds": 3640.0,
                                           "rejected": []})
    assert "182" in win.log_panel.toPlainText()
    assert np.array_equal(win.project.current().data, open_before), (
        "a background stack replaced the image the user had open")


def test_a_failed_job_says_why_in_the_log(qtbot, tmp_path, monkeypatch):
    from tests.ui.test_main_window import _window

    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    win = _window(qtbot, tmp_path)
    job = _job()
    win._job_queue.enqueue(job)
    win._job_queue._on_child_done(job, 1, {"event": "error",
                                           "message": "need at least 3 frames"})
    assert "at least 3 frames" in win.log_panel.toPlainText()


def test_a_foreground_stack_does_not_replace_open_work(qtbot, tmp_path):
    """Andreas raised this: a finishing stack would swap out whatever is open.
    The rule is one sentence — a finished stack never replaces work you have
    open — so with something open the master is logged instead.

    Captured and asserted UNCHANGED, not merely different from the master.
    """
    from tests.ui.test_main_window import _make_fits, _window

    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    before = win.project.current().data.copy()
    master = AstroImage(np.full((8, 8, 3), 0.9, np.float32), is_linear=False,
                        metadata={})
    win._on_foreground_master(master, "stacked master")
    assert np.array_equal(win.project.current().data, before)
    assert "stacked master" in win.log_panel.toPlainText()


def test_a_foreground_stack_opens_when_nothing_is_open(qtbot, tmp_path):
    from tests.ui.test_main_window import _window

    win = _window(qtbot, tmp_path)
    assert win.project is None
    master = AstroImage(np.full((8, 8, 3), 0.9, np.float32), is_linear=False,
                        metadata={})
    win._on_foreground_master(master, "stacked master")
    assert win.project is not None, "nothing was open, so it should have opened"


def test_quitting_with_jobs_running_warns_and_cancels(qtbot, tmp_path, monkeypatch):
    from tests.ui.test_main_window import _window

    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    import nocturne.ui.job_queue as jq
    monkeypatch.setattr(jq, "kill_process", lambda proc: None)
    win = _window(qtbot, tmp_path)
    win._job_queue.enqueue(_job("A"))
    win._job_queue.enqueue(_job("B"))

    asked = {}
    monkeypatch.setattr(win, "_confirm_quit_with_jobs",
                        lambda n: asked.setdefault("n", n) or True)
    win._cancel_jobs_for_quit()
    assert asked["n"] == 2, "the warning must say how many jobs are at stake"
    assert win._job_queue.running() is None
    assert all(j.state == "cancelled" for j in win._job_queue.jobs())


def test_the_panel_is_in_the_window_and_shows_when_a_job_starts(qtbot, tmp_path, monkeypatch):
    from tests.ui.test_main_window import _window

    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    win = _window(qtbot, tmp_path)
    win.show()
    qtbot.waitExposed(win)
    assert win.jobs_panel.parent() is not None, "the panel was never added to a layout"
    assert not win.jobs_panel.isVisible(), "an empty panel should not take height"
    win._job_queue.enqueue(_job("A"))
    assert win.jobs_panel.isVisible()
    assert "A" in win.jobs_panel.rows()[0]


def test_quitting_after_a_cancel_that_has_not_reaped_still_waits(qtbot, tmp_path):
    """Cancel in the panel, then quit: nothing is left "queued" or "running"
    (the job is "cancelled"), but its reader thread can still be alive —
    JobsPanel shows exactly this window as "stopping…", and `running()` keeps
    naming the job throughout it. Gating the wait on queued/running skipped it
    on precisely this route — the likeliest one — to the uncatchable
    delivery-time crash `wait_for_shutdown` exists to prevent.
    """
    from tests.ui.test_main_window import _window

    win = _window(qtbot, tmp_path)
    job = _job("A")
    win._job_queue._jobs.append(job)
    job.state = "cancelled"          # already cancelled: NOT queued, NOT running
    win._job_queue._running = job    # but still occupying the slot: not yet reaped

    # Nothing is queued/running, so quitting here must not even ask —
    # the user already chose to stop this job via Cancel.
    def _unexpected(_n):
        raise AssertionError("must not ask to quit — nothing is queued/running")

    win._confirm_quit_with_jobs = _unexpected

    still_alive = threading.Event()

    def slow_finish():
        still_alive.wait(timeout=0.3)

    t = threading.Thread(target=slow_finish)
    win._job_queue._reader_threads.append(t)
    t.start()

    assert win._cancel_jobs_for_quit() is True
    assert not t.is_alive(), \
        "closeEvent's wait never joined the leftover (not-yet-reaped) reader thread"
