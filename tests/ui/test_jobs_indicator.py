import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

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


def _blank(ind) -> bool:
    """Idle, as the toolbar sees it: present, but saying nothing and offering
    nothing — no text, no popover rows, nothing to click."""
    return (not ind.isHidden() and ind.text() == "" and ind.popover_rows() == []
            and not ind.isEnabled())


def test_blank_but_present_when_nothing_is_queued(qtbot, monkeypatch):
    q, ind = _ind(qtbot, monkeypatch)
    assert _blank(ind)


def test_idle_click_opens_nothing(qtbot, monkeypatch):
    q, ind = _ind(qtbot, monkeypatch)
    ind._show_popover()
    assert ind._popover is None


def test_the_width_never_follows_the_text(qtbot, monkeypatch):
    """It heads the toolbar: a width change shifts every button after it.
    Captured idle, then compared exactly through every state, including a
    percent tick and a label long enough to need eliding."""
    q, ind = _ind(qtbot, monkeypatch)
    idle_width = ind.width()
    job = _job("Some Extremely Long Target Name Here"); q.enqueue(job)
    widths = []
    for pct in (0, 7, 42, 100):
        q.progress.emit(job, pct, "")
        widths.append(ind.width())
    q.enqueue(_job("B"))
    widths.append(ind.width())
    q.finished.emit(job, {"output": ""})
    job.state = "done"; q._running = None; q.changed.emit()
    widths.append(ind.width())
    assert widths == [idle_width] * len(widths)


def test_the_slot_is_the_fixed_width(qtbot, monkeypatch):
    from nocturne.ui.jobs_indicator import SLOT_W
    q, ind = _ind(qtbot, monkeypatch)
    assert ind.width() == SLOT_W


def test_a_long_label_is_elided_with_the_whole_text_in_the_tooltip(qtbot, monkeypatch):
    """The NAME is shortened, never the state word after it."""
    q, ind = _ind(qtbot, monkeypatch)
    job = _job("Some Extremely Long Target Name Here"); q.enqueue(job)
    q.finished.emit(job, {"output": ""})
    job.state = "done"; q._running = None; q.changed.emit()
    assert ind.full_text() == "✓ Some Extremely Long Target Name Here ready"
    assert ind.text() != ind.full_text() and "…" in ind.text()
    assert ind.text().startswith("✓ Some") and ind.text().endswith(" ready")
    assert ind.toolTip() == ind.full_text()
    assert ind.fontMetrics().horizontalAdvance(ind.text()) <= ind._text_room


def test_a_long_running_label_keeps_its_percent(qtbot, monkeypatch):
    q, ind = _ind(qtbot, monkeypatch)
    job = _job("Some Extremely Long Target Name Here"); q.enqueue(job)
    q.progress.emit(job, 42, "")
    assert "…" in ind.text() and ind.text().endswith(" 42%")


@pytest.mark.parametrize("label", ["M 33", "NGC 7000", "IC 1396A"])
def test_an_ordinary_label_is_shown_whole(qtbot, monkeypatch, label):
    q, ind = _ind(qtbot, monkeypatch)
    job = _job(label); q.enqueue(job)
    q.progress.emit(job, 100, "")
    assert ind.text() == f"⟳ {label} 100%" and ind.toolTip() == ""
    q.finished.emit(job, {"output": ""})
    job.state = "done"; q._running = None; q.changed.emit()
    assert ind.text() == f"✓ {label} ready" and ind.toolTip() == ""


def test_the_wording_has_no_filler(qtbot, monkeypatch):
    """Andreas, 2026-09-25: "⟳ M 33 42%", "⟳ 2 jobs 42%", "✓ M 33 ready",
    "✗ M 33 failed" — nothing a 140 px slot has to spend on "Stacking" or
    "— open"."""
    q, ind = _ind(qtbot, monkeypatch)
    a, b = _job("M 33"), _job("B")
    q.enqueue(a)
    q.progress.emit(a, 42, "")
    assert ind.text() == "⟳ M 33 42%"
    q.enqueue(b)
    assert ind.text() == "⟳ 2 jobs 42%"
    q.failed.emit(a, "boom")
    a.state = "failed"; b.state = "failed"; q._running = None; q.changed.emit()
    assert ind.text() == "✗ M 33 failed"


def test_running_shows_label_and_percent(qtbot, monkeypatch):
    q, ind = _ind(qtbot, monkeypatch)
    job = _job(); q.enqueue(job)
    q.progress.emit(job, 42, "")
    assert ind.isEnabled()
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
    assert "ready" in ind.text().lower() and ind.isEnabled()
    q.changed.emit()                                 # unrelated churn does not clear it
    assert "ready" in ind.text().lower() and ind.isEnabled()
    ind.acknowledge(0)
    assert _blank(ind)


def test_open_calls_back_with_the_path_and_clears(qtbot, monkeypatch, tmp_path):
    opened = []
    q, ind = _ind(qtbot, monkeypatch, opened)
    out = tmp_path / "m33.fits"; out.write_bytes(b"x")
    job = _job(); q.enqueue(job)
    q.finished.emit(job, {"output": str(out)})
    job.state = "done"; q._running = None; q.changed.emit()
    ind.open_notice(0)
    assert opened == [str(out)] and _blank(ind)


def test_failed_is_red_and_stays(qtbot, monkeypatch):
    q, ind = _ind(qtbot, monkeypatch)
    job = _job(); q.enqueue(job)
    q.failed.emit(job, "out of memory")
    job.state = "failed"; q._running = None; q.changed.emit()
    assert "failed" in ind.text().lower() and ind.isEnabled()


def test_cancel_row_cancels_the_targeted_job_and_no_other(qtbot, monkeypatch):
    """Ported from the deleted panel's suite. Teeth: with two jobs outstanding,
    cancelling index 1 must hit the queued job at that slot, not the running
    one at slot 0. Asserting only that *a* job ended up cancelled would pass
    even if the wrong one were hit — so capture the untouched job's state and
    require it is still exactly what it was, not merely "not cancelled".
    `cancel_row` resolves its index immediately here, in the same tick it is
    read, so the index-vs-identity hazard the popover has (see the stale-row
    test below) does not apply to this direct call."""
    q, ind = _ind(qtbot, monkeypatch)
    running_job, queued_job = _job("IC 1396A"), _job("NGC 7000")
    q.enqueue(running_job)
    q.enqueue(queued_job)
    running_state_before = running_job.state
    assert running_state_before == "running"

    ind.cancel_row(1)

    assert queued_job.state == "cancelled"
    assert running_job.state == running_state_before


def _popover_buttons(ind):
    """The buttons a user can actually reach, in displayed (construction)
    order — reading the live popover, not `popover_rows()`, which recomputes
    its text from the queue on every call and so agrees with the model no
    matter what was actually wired to which button."""
    return ind._popover.findChildren(QPushButton)


def test_clicking_the_first_rows_cancel_button_stops_that_job_and_no_other(qtbot, monkeypatch):
    """Ported from the deleted panel's suite, through the popover this time.

    Through the button, not through `cancel_row`: the connection between a
    row's button and its job is the part only a real click exercises, and it
    is the only way a user can stop a job from the toolbar.

    Clicks the FIRST row deliberately. A lambda connected without capturing
    its loop variable as a default argument calls back with the LAST job for
    every row — a click on the last row cannot tell that apart from correct
    behaviour; row 0 can.
    """
    q, ind = _ind(qtbot, monkeypatch)
    monkeypatch.setattr("nocturne.ui.job_queue.kill_process", lambda proc: None)
    running, queued = _job("IC 1396A"), _job("NGC 7000")
    q.enqueue(running)
    q.enqueue(queued)

    ind._show_popover()
    buttons = _popover_buttons(ind)
    assert len(buttons) == 2, "one button per outstanding job"
    before = queued.state
    qtbot.mouseClick(buttons[0], Qt.MouseButton.LeftButton)

    assert running.state == "cancelled"
    assert queued.state == before, (
        "clicking row 1's button hit row 2's job — the buttons are wired to "
        "the wrong rows")


def test_a_stale_popover_row_still_targets_its_own_job_after_the_queue_advances(
        qtbot, monkeypatch):
    """Regression for a real bug found in review: the popover's Cancel/Remove
    buttons used to capture a ROW INDEX and re-resolve `_outstanding()[index]`
    at click time. The queue can advance while the popover is still open — a
    running job finishes, the next one is promoted — which reshuffles what
    that index means. Reproduced: A running, B and C queued; popover built
    (B is row 1); A finishes; clicking "B's" button cancelled C instead,
    because C had slid into slot 1 once A dropped out of `_outstanding()`.

    The fix captures the JOB itself in each button's closure, so the row
    keeps meaning what it meant when it was drawn, no matter what the queue
    does to the list around it.
    """
    q, ind = _ind(qtbot, monkeypatch)
    monkeypatch.setattr("nocturne.ui.job_queue.kill_process", lambda proc: None)
    a, b, c = _job("A"), _job("B"), _job("C")
    q.enqueue(a); q.enqueue(b); q.enqueue(c)
    assert a.state == "running" and b.state == "queued" and c.state == "queued"

    ind._show_popover()
    buttons = _popover_buttons(ind)
    assert len(buttons) == 3
    b_button = buttons[1]          # the row that said "B" when it was drawn

    # A finishes while the popover is still open — the real ordering: the
    # queue clears `_running` and the job's state moves to "done" together.
    q._running = None
    a.state = "done"
    q.finished.emit(a, {"output": "/tmp/A.fits"})
    q.changed.emit()

    qtbot.mouseClick(b_button, Qt.MouseButton.LeftButton)

    assert b.state == "cancelled", "the button built for B did not cancel B"
    assert c.state == "queued", "B's row cancelled C instead of B"


@pytest.mark.parametrize("event", [None, {}, {"output": 123}])
def test_a_malformed_finished_event_does_not_crash_and_stores_no_path(
        qtbot, monkeypatch, event):
    """Ported from the deleted panel's suite (adapted: unlike JobsPanel,
    JobsIndicator DOES read the `finished` event, so its guard is what is
    under test here, not mere non-crashing). A child process is an external,
    unvalidated source: `None` (nothing came through), `{}` (a `done` event
    missing every key the schema normally guarantees), and a present but
    wrong-typed "output" must all leave the stored notice path exactly `""`,
    never raise, and never be mistaken for a real path."""
    q, ind = _ind(qtbot, monkeypatch)
    job = _job(); q.enqueue(job)

    ind._on_finished(job, event)   # the queue's own `finished` signal is typed
                                    # `dict` and would reject `None` outright;
                                    # calling the handler directly is what
                                    # actually exercises its guard against
                                    # each malformed shape.

    assert ind.notices[-1]["path"] == ""


def test_a_closed_popover_is_deleted_not_leaked(qtbot, monkeypatch):
    """Every click on the indicator builds a fresh frame; without
    WA_DeleteOnClose each closed one lived until the app quit."""
    from PySide6.QtWidgets import QApplication
    q, ind = _ind(qtbot, monkeypatch)
    q.enqueue(_job("A"))
    ind._show_popover()
    gone = []
    ind._popover.destroyed.connect(lambda *_: gone.append(True))
    ind._popover.close()
    QApplication.sendPostedEvents(None, 0)      # 0 = QEvent.DeferredDelete
    QApplication.processEvents()
    assert gone == [True]
