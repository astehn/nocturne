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
        self.pid = 0          # see test_job_queue._FakeProc: never a real pid


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
    before = win.activity.text()
    for pct in range(0, 31):
        win._job_queue._on_line(job, json.dumps({"event": "progress",
                                                 "done": pct, "phase": "aligning"}))
    added = win.activity.text()[len(before):]
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
    assert "182" in win.activity.text()
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
    assert "at least 3 frames" in win.activity.text()


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
    out_path = str(tmp_path / "master.fits")
    win._on_foreground_master(master, "stacked master", out_path)
    assert np.array_equal(win.project.current().data, before)
    assert "stacked master" in win.activity.text()
    assert out_path in win.activity.text(), \
        "the file exists on disk and the log must say where"


def test_a_foreground_stack_opens_when_nothing_is_open(qtbot, tmp_path):
    from tests.ui.test_main_window import _window

    win = _window(qtbot, tmp_path)
    assert win.project is None
    master = AstroImage(np.full((8, 8, 3), 0.9, np.float32), is_linear=False,
                        metadata={})
    win._on_foreground_master(master, "stacked master", str(tmp_path / "master.fits"))
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


def test_the_jobs_indicator_is_first_in_the_toolbar(qtbot, tmp_path, monkeypatch):
    from tests.ui.test_main_window import _window

    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    win = _window(qtbot, tmp_path)
    win.show(); qtbot.waitExposed(win)
    assert win._toolbar.widgetForAction(win._toolbar.actions()[0]) is win.jobs_indicator
    assert not win.jobs_indicator.isHidden() and win.jobs_indicator.text() == ""
    win._job_queue.enqueue(_job("A"))
    assert "A" in win.jobs_indicator.text() and win.jobs_indicator.isEnabled()


def test_open_on_a_missing_master_warns_instead_of_crashing(qtbot, tmp_path, monkeypatch):
    from tests.ui.test_main_window import _window

    win = _window(qtbot, tmp_path)
    win._open_finished_master(str(tmp_path / "gone.fits"))
    assert "no longer" in win._warning.text().lower()


def test_quitting_after_a_cancel_that_has_not_reaped_still_waits(qtbot, tmp_path):
    """Cancel from the indicator, then quit: nothing is left "queued" or
    "running" (the job is "cancelled"), but its reader thread can still be
    alive — JobsIndicator shows exactly this window as "stopping…", and
    `running()` keeps naming the job throughout it. Gating the wait on
    queued/running skipped it
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


def test_a_combine_result_survives_with_a_project_open(qtbot, tmp_path, monkeypatch):
    """Combine writes no file at all — combine_dialog.py hands the finished
    picture over as an in-memory AstroImage, and that is the ONLY delivery.
    The "never replace open work" rule was Andreas's ask for a BACKGROUND
    stack, which always writes a master to disk first; extending it to
    Combine — which has nothing to point at — would drop the whole result
    with one log line and no way to get it back. It must always open,
    exactly as it did before this branch.
    """
    from tests.ui.test_main_window import _make_fits, _window
    import nocturne.ui.combine_dialog as combine_dialog_module

    captured = {}

    class _FakeCombineDialog:
        """Stands in for the real dialog: captures the on_master callback
        _open_combine actually wires up, then fires it exactly as the real
        dialog does on a successful combine — without a real modal exec()."""

        def __init__(self, settings, parent=None, on_master=None):
            captured["on_master"] = on_master

        def exec(self):
            pass

    monkeypatch.setattr(combine_dialog_module, "CombineDialog", _FakeCombineDialog)

    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))

    win._open_combine()
    assert "on_master" in captured, "_open_combine never wired up a callback"

    result = AstroImage(np.full((8, 8, 3), 0.9, np.float32), is_linear=False,
                        metadata={})
    captured["on_master"](result)

    assert np.array_equal(win.project.current().data, result.data), \
        "a finished Combine has nowhere else to go — it must open, not be logged away"


def test_open_stack_hands_the_dialog_the_real_queues_busy_check(
        qtbot, tmp_path, monkeypatch):
    """The guard is tested; this tests the line that ARMS it.

    `test_a_fresh_dialog_refuses_to_start_while_the_queue_is_busy` builds a
    StackDialog directly with `queue_busy=lambda: True`, so it proves the
    dialog honours the callable — and stays green if `_open_stack` stops
    passing one. Deleting that kwarg reopened the two-writer race with all
    1505 UI and stacking tests still passing.

    So this asserts the wiring: the dialog is handed something, and what it is
    handed tracks the REAL queue rather than a constant.
    """
    from tests.ui.test_main_window import _window

    win = _window(qtbot, tmp_path)
    captured = {}

    class _Stub:
        def __init__(self, *a, **kw):
            captured.update(kw)

        def exec(self):
            return 0

    monkeypatch.setattr("nocturne.ui.stack_dialog.StackDialog", _Stub)
    win._open_stack()

    busy = captured.get("queue_busy")
    assert callable(busy), "_open_stack did not pass queue_busy to the dialog"
    assert busy() is False, "the queue is idle, so the dialog should be free"

    monkeypatch.setattr(JobQueue, "_spawn", lambda self, j: _FakeProc())
    win._job_queue.enqueue(_job())
    assert busy() is True, (
        "queue_busy is not reading the live queue — a dialog opened during a "
        "background stack would start a second writer")


def test_a_result_with_no_file_behind_it_is_refused_not_dropped(qtbot, tmp_path):
    """The structural half of the Combine fix.

    Routing a fileless result through here destroyed it silently — Combine
    writes nothing to disk, so "not opened, you have an image open" was the
    whole of its delivery. `path` is required now, and a falsy one raises
    rather than logging. Without a test, a later refactor making it optional
    again restores the data loss with a green suite.
    """
    from tests.ui.test_main_window import _window

    win = _window(qtbot, tmp_path)
    img = AstroImage(np.zeros((4, 4, 3), np.float32), is_linear=True, metadata={})
    with pytest.raises(ValueError, match="real file path"):
        win._on_foreground_master(img, "combined narrowband", "")


def test_a_job_starting_in_fullscreen_does_not_bring_the_column_back(qtbot, tmp_path, monkeypatch):
    """Fullscreen hides the chrome deliberately — the left column AND the
    toolbar the jobs indicator lives in — and a queue change must not undo
    that. Leaving fullscreen must restore both: the column because the chrome
    is back, the indicator because the job is still outstanding."""
    from tests.ui.test_main_window import _make_fits, _window

    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.show(); qtbot.waitExposed(win)
    win._toggle_fullscreen()
    qtbot.wait(50)
    win._job_queue.enqueue(_job("A"))
    assert not win._left_column.isVisible()
    win._exit_fullscreen()
    qtbot.wait(50)
    assert win._left_column.isVisible() and win.jobs_indicator.isVisible()
    assert "A" in win.jobs_indicator.text()
