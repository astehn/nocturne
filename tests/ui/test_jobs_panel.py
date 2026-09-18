"""The panel is the only place a backgrounded job can be seen or stopped."""
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton

from nocturne.stacking.stacker import StackOptions
from nocturne.ui.job_queue import JobQueue, StackJob
from nocturne.ui.jobs_panel import JobsPanel


class _FakeProc:
    def __init__(self):
        self.returncode = None
        self.pid = 0          # see test_job_queue._FakeProc: never a real pid


def _queue(monkeypatch):
    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    return JobQueue()


def _job(name):
    return StackJob(name, StackOptions("average", 2.5, ["a", "b", "c"],
                                       f"/tmp/{name}.fits"))


def test_it_is_empty_with_no_jobs(qtbot, monkeypatch):
    q = _queue(monkeypatch)
    panel = JobsPanel(q)
    qtbot.addWidget(panel)
    assert panel.is_empty()
    assert panel.rows() == []


def test_a_running_job_and_a_queued_one_are_both_listed(qtbot, monkeypatch):
    q = _queue(monkeypatch)
    panel = JobsPanel(q)
    qtbot.addWidget(panel)
    q.enqueue(_job("IC 1396A"))
    q.enqueue(_job("NGC 7000"))
    rows = panel.rows()
    assert len(rows) == 2
    assert "IC 1396A" in rows[0]
    assert "NGC 7000" in rows[1] and "queued" in rows[1].lower()


def test_progress_appears_against_the_running_job(qtbot, monkeypatch):
    q = _queue(monkeypatch)
    panel = JobsPanel(q)
    qtbot.addWidget(panel)
    job = _job("IC 1396A")
    q.enqueue(job)
    q._on_line(job, json.dumps({"event": "progress", "done": 47,
                                "phase": "aligning frames"}))
    assert "47%" in panel.rows()[0]


def test_cancelling_from_the_panel_reaches_the_queue(qtbot, monkeypatch):
    q = _queue(monkeypatch)
    import nocturne.ui.job_queue as jq
    monkeypatch.setattr(jq, "kill_process", lambda proc: None)
    panel = JobsPanel(q)
    qtbot.addWidget(panel)
    job = _job("IC 1396A")
    q.enqueue(job)
    panel.cancel_row(0)
    assert job.state == "cancelled"


def test_a_finished_job_leaves_the_list(qtbot, monkeypatch):
    """The panel shows what is OUTSTANDING. A finished stack is reported in the
    log, which is the permanent record; leaving it here would turn a status
    panel into a second, worse history."""
    q = _queue(monkeypatch)
    panel = JobsPanel(q)
    qtbot.addWidget(panel)
    job = _job("IC 1396A")
    q.enqueue(job)
    q._on_child_done(job, 0, {"event": "done", "output": "/tmp/x.fits",
                              "frames": 5, "seconds": 50.0, "rejected": []})
    assert panel.is_empty()


def test_cancel_row_cancels_the_targeted_job_and_no_other(qtbot, monkeypatch):
    """Teeth: with two jobs outstanding, cancelling index 1 must hit the
    queued job at that slot, not the running one at slot 0. Asserting only
    that *a* job ended up cancelled would pass even if the panel cancelled
    the wrong one — so capture the untouched job's state and require it is
    still exactly what it was, not merely "not cancelled"."""
    q = _queue(monkeypatch)
    panel = JobsPanel(q)
    qtbot.addWidget(panel)
    running_job = _job("IC 1396A")
    queued_job = _job("NGC 7000")
    q.enqueue(running_job)
    q.enqueue(queued_job)
    running_state_before = running_job.state
    assert running_state_before == "running"

    panel.cancel_row(1)

    assert queued_job.state == "cancelled"
    assert running_job.state == running_state_before


def test_a_cancelled_running_job_reads_as_stopping_and_stays_listed(
        qtbot, monkeypatch):
    """The queue keeps `running()` pointed at a cancelled job until its child
    is actually reaped (SIGTERM does not wait). The panel must render that
    honestly: still present, but never claiming ordinary progress."""
    q = _queue(monkeypatch)
    import nocturne.ui.job_queue as jq
    monkeypatch.setattr(jq, "kill_process", lambda proc: None)
    panel = JobsPanel(q)
    qtbot.addWidget(panel)
    job = _job("IC 1396A")
    q.enqueue(job)

    panel.cancel_row(0)

    assert not panel.is_empty()
    row = panel.rows()[0]
    assert "stopping" in row.lower()
    assert "%" not in row

    # The child dies later; only then does the job actually leave the panel.
    q._on_child_done(job, -15, None)
    qtbot.waitUntil(lambda: panel.is_empty())


def test_a_done_event_missing_fields_does_not_crash_the_panel(
        qtbot, monkeypatch):
    """A child process is an external, unvalidated source. A `done` event
    missing keys the schema normally guarantees must not take the panel — or
    the queue driving it — down."""
    q = _queue(monkeypatch)
    panel = JobsPanel(q)
    qtbot.addWidget(panel)
    job = _job("IC 1396A")
    q.enqueue(job)

    q._on_child_done(job, 0, {"event": "done"})  # no output/frames/seconds

    assert panel.is_empty()
    assert panel.rows() == []


def _cancel_buttons(panel):
    """The buttons a user can actually reach, in displayed order.

    Read off the layout rather than `findChildren`, which walks the tree in
    construction order — that happens to match today and would stop matching
    the moment a row is rebuilt in place.
    """
    return [r.findChild(QPushButton) for r in _rows(panel) if r is not None]


def _rows(panel):
    lay = panel.layout()
    return [lay.itemAt(i).widget() for i in range(lay.count())]


def _labels(panel):
    """What is actually painted, as distinct from what `rows()` recomputes.

    `rows()` derives its text from the queue on every call, so it agrees with
    the model whatever the labels say — it cannot see a label written with the
    wrong job's text. Only reading the widgets can.
    """
    return [r.findChild(QLabel).text() for r in _rows(panel) if r is not None]


def test_clicking_the_first_rows_cancel_button_stops_that_job_and_no_other(
        qtbot, monkeypatch):
    """Through the button, not through `cancel_row`.

    `cancel_row` is correct and separately tested; the connection between a
    row's button and its index is the part only a real click exercises, and it
    is the ONLY way a user can stop a job.

    It clicks the FIRST row deliberately. Python closures capture the loop
    variable, not its value, so a button connected without the default-arg
    capture calls `cancel_row` with the LAST index for every row — which a
    click on the last row cannot tell from correct behaviour. Row 0 can.
    """
    q = _queue(monkeypatch)
    panel = JobsPanel(q)
    qtbot.addWidget(panel)
    running, queued = _job("IC 1396A"), _job("NGC 7000")
    q.enqueue(running)
    q.enqueue(queued)

    buttons = _cancel_buttons(panel)
    assert len(buttons) == 2, "one Cancel button per outstanding job"
    before = queued.state
    qtbot.mouseClick(buttons[0], Qt.MouseButton.LeftButton)

    assert running.state == "cancelled"
    assert queued.state == before, (
        "clicking row 1's Cancel hit row 2's job — the buttons are wired to "
        "the wrong rows")


def test_a_progress_tick_writes_only_the_running_jobs_label(qtbot, monkeypatch):
    """Progress is matched by job identity, and this is what pins that.

    It reads the LABELS, not `rows()`. `rows()` recomputes its text from the
    queue on every call, so it reports what the model says and agrees with
    itself no matter what was painted — a tick that wrote the running job's
    text onto every row would leave `rows()` looking perfect.
    """
    q = _queue(monkeypatch)
    panel = JobsPanel(q)
    qtbot.addWidget(panel)
    running, queued = _job("IC 1396A"), _job("NGC 7000")
    q.enqueue(running)
    q.enqueue(queued)
    before = _labels(panel)[1]

    q.progress.emit(running, 42, "integrating")

    labels = _labels(panel)
    assert "42" in labels[0]
    assert labels[1] == before, (
        "the running job's progress was written onto the queued job's row")
    assert "NGC 7000" in labels[1]
