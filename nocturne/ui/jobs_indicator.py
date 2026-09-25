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

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QToolButton, QVBoxLayout)

from .theme import DANGER, SUCCESS, WARNING


# The longest texts this button is expected to show whole. It sits at the
# HEAD of the toolbar, so any change in its width shifts every button after it
# sideways — measured before this was fixed: Open Image at x 16 idle, 137 with
# "✓ A ready — open", 219 with a longer label, and a jitter on every percent
# tick. So the width is set ONCE from these and never follows the text; a
# longer target name is elided, with the whole text in the tooltip.
# "Andromeda Galaxy" stands for a long Seestar OBJECT name (16 characters; the
# fallback "stacked master" is 14).
_SIZING_TEXTS = (
    "✓ Andromeda Galaxy ready — open",
    "⟳ Stacking Andromeda Galaxy 100%",
    "✗ Andromeda Galaxy failed",
    "⟳ 2 jobs · 100%",
    "◌ Stopping…",
)


class JobsIndicator(QToolButton):
    """Always present, fixed width, blank while idle — never hidden, because
    appearing would push the whole toolbar sideways (the same "reserve the
    room even when empty" rule as the status slot)."""

    def __init__(self, queue, on_open, parent=None) -> None:
        super().__init__(parent)
        self._queue = queue
        self._on_open = on_open
        self._pct: dict[int, int] = {}
        self.notices: list[dict] = []
        self._popover: QFrame | None = None
        self._full_text = ""
        self._text_room = 0
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._fix_width()
        self.clicked.connect(self._show_popover)
        queue.changed.connect(self._refresh)
        queue.progress.connect(self._on_progress)
        queue.finished.connect(self._on_finished)
        queue.failed.connect(self._on_failed)
        self._refresh()

    def _fix_width(self) -> None:
        """Width from the sizing texts in the CURRENT font. Re-measured only
        when the font changes (an app stylesheet applied after construction),
        never on the per-state colour change — that must not move anything."""
        fm = self.fontMetrics()
        self._text_room = max(fm.horizontalAdvance(t) for t in _SIZING_TEXTS)
        shown = self.text()
        self.setText(max(_SIZING_TEXTS, key=fm.horizontalAdvance))
        width = self.sizeHint().width()
        self.setText(shown)
        self.setFixedWidth(width)

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._fix_width()
            self._show_text(self._full_text)

    def _show_text(self, text: str) -> None:
        self._full_text = text
        elided = self.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideMiddle, self._text_room)
        self.setText(elided)
        self.setToolTip(text if elided != text else "")

    def full_text(self) -> str:
        """What the button says before elision."""
        return self._full_text

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
            text, colour = "", None
        # Idle: blank and inert, but still occupying its place.
        self.setEnabled(bool(text))
        self.setStyleSheet(f"color: {colour};" if colour else "")
        self._show_text(text)

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
        if not self._outstanding() and not self.notices:
            return                  # idle: the blank button does nothing
        pop = QFrame(None, Qt.WindowType.Popup)
        # Deleted on close, so a click no longer leaks a frame. Parentless
        # (a top-level popup, as QMenu is): as a CHILD of this button, a
        # closed popover still waiting on its deferred delete segfaulted when
        # the button itself was destroyed first — reproduced in the popover
        # tests, whose indicator dies as the test returns. The app stylesheet
        # is set on the QApplication, so it still styles this frame.
        pop.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
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
            row.addWidget(QLabel(self._row_text(job), pop))
            row.addStretch(1)
            if job.state == "running":
                b = QPushButton("Cancel", pop)
                b.clicked.connect(lambda _=False, j=job: self._queue.cancel(j))
                b.clicked.connect(pop.close)
                row.addWidget(b)
            elif job.state == "queued":
                b = QPushButton("Remove", pop)
                b.clicked.connect(lambda _=False, j=job: self._queue.cancel(j))
                b.clicked.connect(pop.close)
                row.addWidget(b)
            lay.addLayout(row)
        for i, n in enumerate(list(self.notices)):
            row = QHBoxLayout()
            if n["kind"] == "done":
                row.addWidget(QLabel(f"✓ {n['label']} — ready", pop))
                row.addStretch(1)
                ob = QPushButton("Open", pop)
                ob.clicked.connect(pop.close)
                ob.clicked.connect(lambda _=False, i=i: self.open_notice(i))
                row.addWidget(ob)
            else:
                row.addWidget(QLabel(f"✗ {n['label']} — {n['message']}", pop))
                row.addStretch(1)
            db = QPushButton("Dismiss", pop)
            db.clicked.connect(lambda _=False, i=i: self.acknowledge(i))
            db.clicked.connect(pop.close)
            row.addWidget(db)
            lay.addLayout(row)
        pop.move(self.mapToGlobal(self.rect().bottomLeft()))
        pop.show()
        self._popover = pop
