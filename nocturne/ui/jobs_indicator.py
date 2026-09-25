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

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QToolBar, QToolButton, QVBoxLayout,
                               QWidget)

from .theme import DANGER, SUCCESS, WARNING


# A FIXED slot. It sits at the HEAD of the toolbar, so any change in its
# width shifts every button after it sideways — measured before this was
# fixed: Open Image at x 16 idle, 137 with "✓ A ready — open", 219 with a
# longer label, and a jitter on every percent tick. So the width never
# follows the text, and a long target name is elided, whole in the tooltip.
#
# 140 px, measured 2026-09-25 at 1280x800 (offscreen, the suite's platform):
# "Starless Levels…", the newest toolbar tool, stays visible up to a 140 px
# slot and drops behind the overflow chevron at 150 — and it must stay
# reachable at the floor (test_toolbar_overflow_at_the_small_screen_floor).
# Sized for the wording rather than the other way round: "⟳ M 33 42%",
# "⟳ 2 jobs 42%", "✓ M 33 ready", "✗ M 33 failed", "◌ Stopping…" — no filler
# words, so ordinary Seestar names fit whole and only long ones elide.
SLOT_W = 140
_IDLE_STYLE = "background: transparent; border: none;"


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
        self._label = ""
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
        """The slot is SLOT_W whatever the font; the room for text inside it,
        and the height, are measured in the current font and style."""
        self.setFixedWidth(SLOT_W)
        shown = self.text()
        self.setText("")
        padding = self.sizeHint().width()
        # Height fixed too, from every glyph the states use: blank it was
        # 18 px and with "⟳" 22, which moved it 2 px on every job start.
        self.setText("⟳ ✓ ✗ ◌ M 33 100%")
        self.setFixedHeight(self.sizeHint().height())
        self.setText(shown)
        self._text_room = max(0, SLOT_W - padding)

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._fix_width()
            self._show_text(self._full_text, self._label)

    def _show_text(self, text: str, label: str = "") -> None:
        """Elide the TARGET NAME, never the state: "✓ Andromeda Ga… ready"
        still says it is ready, where eliding the end would drop exactly the
        word that matters."""
        self._full_text, self._label = text, label
        fm = self.fontMetrics()
        shown = text
        if fm.horizontalAdvance(text) > self._text_room:
            if label and label in text:
                rest = fm.horizontalAdvance(text.replace(label, "", 1))
                short = fm.elidedText(label, Qt.TextElideMode.ElideRight,
                                      max(0, self._text_room - rest))
                shown = text.replace(label, short, 1)
            else:
                shown = fm.elidedText(text, Qt.TextElideMode.ElideRight, self._text_room)
        self.setText(shown)
        self.setToolTip(text if shown != text else "")

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
        label = ""
        if out:
            stopping = [j for j in out if j.state == "cancelled"]
            if stopping and len(out) == 1:
                text, colour = "◌ Stopping…", WARNING
            elif len(out) == 1:
                j = out[0]
                label = j.label
                text = f"⟳ {label} {self._pct.get(id(j), 0)}%"
                colour = None
            else:
                running = self._queue.running()
                pct = self._pct.get(id(running), 0) if running is not None else 0
                text, colour = f"⟳ {len(out)} jobs {pct}%", None
        elif self.notices:
            last = self.notices[-1]
            label = last["label"]
            if last["kind"] == "done":
                text, colour = f"✓ {label} ready", SUCCESS
            else:
                text, colour = f"✗ {label} failed", DANGER
        else:
            text, colour = "", None
        # Idle: blank, inert and INVISIBLE — reserved space only. Under the
        # app stylesheet an idle, disabled tool button still painted a dark
        # box (Andreas saw it in the real window), so idle draws nothing.
        self.setEnabled(bool(text))
        self.setStyleSheet(_IDLE_STYLE if not text
                           else (f"color: {colour};" if colour else ""))
        self._show_text(text, label)

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


class JobsBar(QToolBar):
    """The indicator's own toolbar, placed after the main one on the same row
    so it sits at the window's right edge.

    Not in the main toolbar: its items overflow from the right, so an
    indicator appended there would be the first thing the chevron hides, and
    at its head it pushed every tool along. Immovable and never offered for
    hiding. QMainWindow gives a row's spare width to its LAST toolbar, so this
    one stretches — an expanding spacer, then the fixed-width indicator, pins
    the indicator to the right edge (a fixed-width bar left it mid-row, x 1773
    on a 2560 window)."""

    def __init__(self, indicator: JobsIndicator, parent=None) -> None:
        super().__init__("Background jobs", parent)
        self.setObjectName("jobsBar")
        self.setMovable(False)
        self.setFloatable(False)
        self.toggleViewAction().setVisible(False)
        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.addWidget(spacer)
        self.addWidget(indicator)
        self._indicator = indicator
        # No padding, margins or spacing: every pixel here comes out of the
        # main toolbar's row. With Qt's defaults the bar cost 148 px and hid
        # "Starless Levels…" at 1280; under the app stylesheet (padding 6,
        # spacing 4) the indicator itself fell into this bar's own overflow.
        self.setStyleSheet("QToolBar#jobsBar { padding: 0px; spacing: 0px; }")
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().setSpacing(0)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        """Never narrower than the indicator. QMainWindow squeezes the LAST
        toolbar in a row first, down to its own chevron (measured: 32 px under
        the app stylesheet, the indicator pushed into the overflow); the main
        toolbar must give way instead. A plain setMinimumWidth did not hold —
        it read back 0 once the window was laid out under the stylesheet."""
        hint = super().minimumSizeHint()
        m = self.contentsMargins()
        lay = self.layout().contentsMargins()
        need = (self._indicator.width() + m.left() + m.right()
                + lay.left() + lay.right())
        return QSize(max(hint.width(), need), hint.height())
