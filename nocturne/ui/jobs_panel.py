"""What is still running in the background, and the only way to stop it.

Shows OUTSTANDING work only: a finished stack is reported in the processing log,
which is the permanent record, so leaving it here would make this a second and
worse history.

A cancelled job is still OUTSTANDING until its child is actually reaped:
`JobQueue.cancel` sends SIGTERM and returns immediately, so the ~8.7 GB it holds
is still resident and `JobQueue.running()` keeps naming it. Dropping it from
this list the instant Cancel is pressed — or still showing it as running —
would both be lies; either teaches the user that Cancel did nothing and they
press it again. So a job stays listed, as "stopping…", for as long as the
queue still calls it the running one, regardless of its own `state`.

Deliberately does not connect `finished`/`failed`: those carry the child's
"done" event dict, which is unvalidated data from an external process. Reading
none of its fields here — only `job.state`, which the queue itself sets — means
a malformed event can never crash this panel, which is exactly the surface
that is supposed to still be usable when something else has gone wrong.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)


class JobsPanel(QWidget):
    def __init__(self, queue, parent=None) -> None:
        super().__init__(parent)
        self._queue = queue
        self._pct: dict[int, int] = {}        # id(job) -> last percent
        self._labels: list[QLabel] = []
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        queue.changed.connect(self._rebuild)
        queue.progress.connect(self._on_progress)
        self._rebuild()

    def _outstanding(self) -> list:
        running = self._queue.running()
        return [j for j in self._queue.jobs()
                if j.state in ("queued", "running") or j is running]

    def _row_text(self, job) -> str:
        if job.state == "cancelled":
            # Still occupying the one slot — SIGTERM was sent, the process
            # hasn't died yet. Not "running": that would claim progress is
            # still being made.
            return f"{job.label} — stopping…"
        if job.state == "running":
            return f"{job.label} — {self._pct.get(id(job), 0)}%"
        return f"{job.label} — queued"

    def rows(self) -> list[str]:
        return [self._row_text(job) for job in self._outstanding()]

    def is_empty(self) -> bool:
        return not self._outstanding()

    def cancel_row(self, index: int) -> None:
        self._queue.cancel(self._outstanding()[index])

    # --- Qt plumbing ---
    def _rebuild(self) -> None:
        """Full rebuild on `changed` (jobs added, removed, or moved slots).

        Progress ticks do NOT come through here — see `_on_progress` — so a
        button is never destroyed out from under an in-flight click.
        """
        while self._lay.count():
            item = self._lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._labels = []
        for index, job in enumerate(self._outstanding()):
            row = QWidget(self)
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            label = QLabel(self._row_text(job))
            row_lay.addWidget(label)
            row_lay.addStretch(1)
            button = QPushButton("Cancel")
            button.clicked.connect(
                lambda _checked=False, i=index: self.cancel_row(i))
            row_lay.addWidget(button)
            self._lay.addWidget(row)
            self._labels.append(label)
        # Prune percent history for jobs the queue no longer knows about, so
        # a long session doesn't accumulate one entry per stack ever run.
        live = {id(j) for j in self._queue.jobs()}
        self._pct = {k: v for k, v in self._pct.items() if k in live}

    def _on_progress(self, job, pct: int, phase: str) -> None:
        self._pct[id(job)] = pct
        for label, outstanding_job in zip(self._labels, self._outstanding()):
            if outstanding_job is job:
                label.setText(self._row_text(job))
                break
