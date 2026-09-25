from nocturne.stacking.stacker import StackOptions
from nocturne.ui.job_queue import JobQueue, StackJob
from nocturne.ui.jobs_indicator import JobsIndicator


class _FakeProc:
    def __init__(self):
        self.returncode = None
        self.pid = 0


def _job(name="M 33"):
    return StackJob(name, StackOptions("average", 2.5, ["a", "b"], f"/tmp/{name}.fits"))


def _ind(qtbot, monkeypatch, opened=None):
    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    q = JobQueue()
    ind = JobsIndicator(q, on_open=(opened.append if opened is not None else lambda p: None))
    qtbot.addWidget(ind)
    ind.show()
    return q, ind


def test_hidden_when_nothing_is_queued(qtbot, monkeypatch):
    q, ind = _ind(qtbot, monkeypatch)
    assert ind.isHidden() and ind.text() == ""


def test_running_shows_label_and_percent(qtbot, monkeypatch):
    q, ind = _ind(qtbot, monkeypatch)
    job = _job(); q.enqueue(job)
    q.progress.emit(job, 42, "")
    assert not ind.isHidden()
    assert "M 33" in ind.text() and "42%" in ind.text()


def test_two_jobs_are_summarised(qtbot, monkeypatch):
    q, ind = _ind(qtbot, monkeypatch)
    q.enqueue(_job("A")); q.enqueue(_job("B"))
    assert "2 jobs" in ind.text()
    assert len(ind.popover_rows()) == 2


def test_a_cancelled_job_says_stopping_until_reaped(qtbot, monkeypatch):
    """Ported from the deleted panel's suite: SIGTERM returns at once; the job
    still holds its slot, and saying anything else teaches the user Cancel
    failed."""
    q, ind = _ind(qtbot, monkeypatch)
    job = _job(); q.enqueue(job)
    monkeypatch.setattr("nocturne.ui.job_queue.kill_process", lambda proc: None)
    q.cancel(job)
    assert "Stopping" in ind.text()


def test_done_stays_until_acted_on(qtbot, monkeypatch):
    """Andreas, 2026-09-25: otherwise there is a real risk of it being missed."""
    opened = []
    q, ind = _ind(qtbot, monkeypatch, opened)
    job = _job(); q.enqueue(job)
    q.finished.emit(job, {"output": "/tmp/M 33.fits", "frames": 3})
    # Drive completion the way the real reader thread does: `_on_child_done`
    # clears `_running` before the job's state changes, and `_outstanding()`
    # keys off `_running` — leaving it pointed at the job would keep the
    # indicator saying "Stacking" instead of "ready" forever.
    job.state = "done"; q._running = None; q.changed.emit()
    assert "ready" in ind.text().lower() and not ind.isHidden()
    q.changed.emit()                                 # unrelated churn does not clear it
    assert not ind.isHidden()
    ind.acknowledge(0)
    assert ind.isHidden()


def test_open_calls_back_with_the_path_and_clears(qtbot, monkeypatch, tmp_path):
    opened = []
    q, ind = _ind(qtbot, monkeypatch, opened)
    out = tmp_path / "m33.fits"; out.write_bytes(b"x")
    job = _job(); q.enqueue(job)
    q.finished.emit(job, {"output": str(out)})
    job.state = "done"; q._running = None; q.changed.emit()
    ind.open_notice(0)
    assert opened == [str(out)] and ind.isHidden()


def test_failed_is_red_and_stays(qtbot, monkeypatch):
    q, ind = _ind(qtbot, monkeypatch)
    job = _job(); q.enqueue(job)
    q.failed.emit(job, "out of memory")
    job.state = "failed"; q._running = None; q.changed.emit()
    assert "failed" in ind.text().lower() and not ind.isHidden()
