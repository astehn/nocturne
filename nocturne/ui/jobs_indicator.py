"""Background work, in the toolbar: what is running, and the way to stop it.

Replaces the left column's interim jobs strip from the bottom-bar removal
(spec §6). Three things that strip could not do: draw progress, stay visible
when the log was hidden, and keep a FINISHED or FAILED stack in front of the
user until they have seen it — Andreas, 2026-09-25: "otherwise there's a real
risk of it being missed".

The "stopping…" rule carries over from that strip: a cancelled job stays
listed for as long as the queue still calls it the running one, because
SIGTERM returns at once and the process is not gone yet.

The `finished` event dict comes from an external child process, so only its
"output" field is read, only as a string, and only ever handed to a callback
that checks the file exists before opening anything.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QToolButton, QVBoxLayout, QWidgetAction)

from .theme import DANGER, SUCCESS, WARNING


class JobsIndicator(QToolButton):
    def __init__(self, queue, on_open, parent=None) -> None:
        super().__init__(parent)
        self._queue = queue
        self._on_open = on_open
        self._pct: dict[int, int] = {}
        self.notices: list[dict] = []
        self._popover: QFrame | None = None
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.clicked.connect(self._show_popover)
        queue.changed.connect(self._refresh)
        queue.progress.connect(self._on_progress)
        queue.finished.connect(self._on_finished)
        queue.failed.connect(self._on_failed)
        self._refresh()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Whoever calls `.show()` — a test, or Qt showing the window this
        button lives in — must not override "hidden while idle": if the queue
        has nothing outstanding and there is no notice, re-hide right away.

        Deliberately does not call the full `_refresh()` (and so never calls
        `.show()` from here): re-entering `.show()` while Qt is still in the
        middle of delivering THIS show event is what caused infinite
        recursion once this button sat in a real toolbar — the one-way
        "hide if empty" correction below carries no such risk.
        """
        super().showEvent(event)
        if not self._outstanding() and not self.notices:
            self.hide()

    def setVisible(self, visible: bool) -> None:  # noqa: N802 (Qt override)
        """`QToolBar.addWidget` wraps this button in a QWidgetAction behind
        the scenes, and the toolbar's layout re-asserts the widget's
        visibility from that action on every relayout — setting only this
        widget's own flag is silently overwritten the next time the toolbar
        reflows. Keeping the wrapping action in sync is what makes a hide
        actually stick once this button sits in a real toolbar.

        Guarded against re-entry: `QWidgetAction.setVisible` syncs back onto
        its default widget, which is this button, which would otherwise call
        straight back into this override forever.
        """
        super().setVisible(visible)
        if getattr(self, "_syncing_toolbar_action", False):
            return
        parent = self.parentWidget()
        if parent is None:
            return
        self._syncing_toolbar_action = True
        try:
            for act in parent.actions():
                if isinstance(act, QWidgetAction) and act.defaultWidget() is self:
                    act.setVisible(visible)
                    break
        finally:
            self._syncing_toolbar_action = False

    # --- state ---
    def _outstanding(self) -> list:
        running = self._queue.running()
        return [j for j in self._queue.jobs()
                if j.state in ("queued", "running") or j is running]

    def _row_text(self, job) -> str:
        if job.state == "cancelled":
            return f"{job.label} — stopping…"
        if job.state == "running":
            return f"{job.label} — {self._pct.get(id(job), 0)}%"
        return f"{job.label} — queued"

    def popover_rows(self) -> list[str]:
        return [self._row_text(j) for j in self._outstanding()] + [
            (f"✓ {n['label']} — ready" if n["kind"] == "done"
             else f"✗ {n['label']} — failed: {n['message']}") for n in self.notices]

    def _on_progress(self, job, pct: int, phase: str) -> None:
        self._pct[id(job)] = int(pct)
        self._refresh()

    def _on_finished(self, job, event: dict) -> None:
        out = event.get("output") if isinstance(event, dict) else None
        self.notices.append({"kind": "done", "label": job.label,
                             "path": out if isinstance(out, str) else ""})
        self._refresh()

    def _on_failed(self, job, message: str) -> None:
        self.notices.append({"kind": "failed", "label": job.label, "message": str(message)})
        self._refresh()

    def _refresh(self) -> None:
        out = self._outstanding()
        if out:
            stopping = [j for j in out if j.state == "cancelled"]
            if stopping and len(out) == 1:
                text, colour = "◌ Stopping…", WARNING
            elif len(out) == 1:
                j = out[0]
                text = f"⟳ Stacking {j.label} {self._pct.get(id(j), 0)}%"
                colour = None
            else:
                running = self._queue.running()
                pct = self._pct.get(id(running), 0) if running is not None else 0
                text, colour = f"⟳ {len(out)} jobs · {pct}%", None
        elif self.notices:
            last = self.notices[-1]
            if last["kind"] == "done":
                text, colour = f"✓ {last['label']} ready — open", SUCCESS
            else:
                text, colour = f"✗ {last['label']} failed", DANGER
        else:
            self.setText("")
            self.hide()
            return
        self.setText(text)
        self.setStyleSheet(f"color: {colour};" if colour else "")
        self.show()

    # --- actions ---
    def acknowledge(self, index: int) -> None:
        del self.notices[index]
        self._refresh()

    def open_notice(self, index: int) -> None:
        path = self.notices[index].get("path", "")
        del self.notices[index]
        self._refresh()
        self._on_open(path)

    def cancel_row(self, index: int) -> None:
        """Resolves `index` against `_outstanding()` right now. Safe for a
        caller that reads and acts in the same tick (a direct test call); NOT
        used by the popover's own buttons, which hold the queue open across
        clicks and so capture the job itself instead — see `_show_popover`."""
        self._queue.cancel(self._outstanding()[index])

    def _show_popover(self) -> None:
        pop = QFrame(self, Qt.WindowType.Popup)
        lay = QVBoxLayout(pop)
        # Captures the JOB itself, not its row index: the queue can advance
        # while this popover is open (a job finishes, the next is promoted to
        # running), which reshuffles what `_outstanding()` returns. An index
        # resolved at click time would then hit whatever job now sits at that
        # position — not the one this row was built for. `cancel_row(index)`
        # below is kept only for callers that resolve it immediately, in the
        # same tick they read it, before anything can reorder the queue.
        for job in self._outstanding():
            row = QHBoxLayout()
            row.addWidget(QLabel(self._row_text(job)))
            row.addStretch(1)
            if job.state == "running":
                b = QPushButton("Cancel")
                b.clicked.connect(lambda _=False, j=job: (self._queue.cancel(j), pop.close()))
                row.addWidget(b)
            elif job.state == "queued":
                b = QPushButton("Remove")
                b.clicked.connect(lambda _=False, j=job: (self._queue.cancel(j), pop.close()))
                row.addWidget(b)
            lay.addLayout(row)
        for i, n in enumerate(list(self.notices)):
            row = QHBoxLayout()
            if n["kind"] == "done":
                row.addWidget(QLabel(f"✓ {n['label']} — ready"))
                row.addStretch(1)
                ob = QPushButton("Open")
                ob.clicked.connect(lambda _=False, i=i: (pop.close(), self.open_notice(i)))
                row.addWidget(ob)
            else:
                row.addWidget(QLabel(f"✗ {n['label']} — {n['message']}"))
                row.addStretch(1)
            db = QPushButton("Dismiss")
            db.clicked.connect(lambda _=False, i=i: (self.acknowledge(i), pop.close()))
            row.addWidget(db)
            lay.addLayout(row)
        pop.move(self.mapToGlobal(self.rect().bottomLeft()))
        pop.show()
        self._popover = pop
