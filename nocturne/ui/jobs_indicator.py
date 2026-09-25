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

from PySide6.QtCore import QEvent, QPoint, QSize, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QToolBar, QToolButton, QVBoxLayout,
                               QWidget)

from .icons import load_icon
from .theme import BG_3, BORDER, DANGER, SUCCESS, TEXT, WARNING


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
# Sized for the wording rather than the other way round: "M 33 · 42%",
# "2 jobs · 42%", "M 33 ready", "M 33 failed", "Stopping…" — no filler
# words, so ordinary Seestar names fit whole and only long ones elide.
SLOT_W = 140
IDLE_TEXT = "Background tasks"
# The unused "log" icon — three lines, a list of work — rather than "stack":
# that one is the Stack tool's, a few buttons along the same row, and two
# identical icons would read as two ways into the same tool.
ICON = "log"
# Less side padding than the toolbar's 10 px: the slot is fixed and the label
# centred, so the padding only eats the room the label has. With the toolbar's
# own, "Background tasks" (117 px offscreen, 14 px) did not fit its 108.
#
# Transparent, with the toolbar's own hover and pressed backgrounds restated:
# the toolbar's buttons are drawn flat, but a tool button ADDED as a widget
# takes the stylesheet's `QWidget { background-color: BG_1 }` and drew the
# dark box Andreas saw in the real window. The two rules below only restore
# what that transparent background overrides.
_BASE_SHEET = ("QToolButton {{ background: transparent; padding-left: 2px; "
               "padding-right: 2px; {colour} }}"
               f" QToolButton:hover {{{{ background: {BG_3}; }}}}"
               f" QToolButton:pressed {{{{ background: {BORDER}; }}}}")


class JobsIndicator(QToolButton):
    """A toolbar tool like the others — icon, label under it — whose label is
    the state of the background work. Always present and a fixed width,
    because appearing or growing would move the toolbar (the same "reserve
    the room even when empty" rule as the status slot).

    Idle it says "Background tasks", dimmed and inert. Andreas, 2026-09-25:
    a blank reserved slot read as "dark unused space"; a label like every
    other tool's says what the place is for."""

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
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setAutoRaise(True)            # flat until hovered, as the toolbar's are
        self._icon_colour = None
        self.setIcon(load_icon(ICON))
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
        # Text under the icon: the hint is the WIDER of the two plus the
        # style's padding, so the padding is read off a text that is surely
        # wider than the icon.
        probe = "M" * 30
        self.setText(probe)
        padding = self.sizeHint().width() - self.fontMetrics().horizontalAdvance(probe)
        # Height fixed too, from every glyph the states use, so no state can
        # grow the row.
        self.setText("Background tasks · M 33 · 100% … Stopping")
        self.setFixedHeight(self.sizeHint().height())
        self.setText(shown)
        self._text_room = max(0, SLOT_W - padding)

    def match_icon_size(self, size: QSize) -> None:
        """Follow the toolbar's icon size; the fixed height is re-measured
        from it."""
        self.setIconSize(size)
        self._fix_width()
        self._show_text(self._full_text, self._label)

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._fix_width()
            self._show_text(self._full_text, self._label)

    def _show_text(self, text: str, label: str = "") -> None:
        """Elide the TARGET NAME, never the state: "Andromeda Ga… ready"
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
                text, colour = "Stopping…", WARNING
            elif len(out) == 1:
                j = out[0]
                label = j.label
                text = f"{label} · {self._pct.get(id(j), 0)}%"
                colour = None
            else:
                running = self._queue.running()
                pct = self._pct.get(id(running), 0) if running is not None else 0
                text, colour = f"{len(out)} jobs · {pct}%", None
        elif self.notices:
            last = self.notices[-1]
            label = last["label"]
            if last["kind"] == "done":
                text, colour = f"{label} ready", SUCCESS
            else:
                text, colour = f"{label} failed", DANGER
        else:
            text, colour = IDLE_TEXT, None
        idle = text == IDLE_TEXT and not label
        # Idle: disabled, so the toolbar's own :disabled rule dims it and it
        # takes no hover or click — there is nothing to show.
        self.setEnabled(not idle)
        sheet = _BASE_SHEET.format(colour=f"color: {colour};" if colour else "")
        if sheet != self.styleSheet():
            self.setStyleSheet(sheet)
        if colour != self._icon_colour:
            self._icon_colour = colour
            self.setIcon(load_icon(ICON, colour or TEXT))
        self._show_text(text, label)

    def is_idle(self) -> bool:
        return not self._outstanding() and not self.notices

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
            return                  # idle: nothing to show
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
        self._place_popover(pop)
        pop.show()
        self._keep_on_screen(pop)
        self._popover = pop

    def _place_popover(self, pop: QFrame) -> None:
        """Right-aligned under the indicator, kept on its screen. The
        indicator sits at the window's right edge, so anchoring at its
        bottom-LEFT ran the popover 112–437 px off the screen, hiding the
        Open/Dismiss/Cancel buttons — a done notice could become unclearable.
        """
        # Polished first: the stylesheet lands at polish and widened it by
        # 2 px after an unpolished adjustSize — enough to cross the edge.
        pop.ensurePolished()
        pop.adjustSize()
        w, h = pop.width(), pop.height()
        top_left = self.mapToGlobal(QPoint(0, 0))
        x = top_left.x() + self.width() - w
        y = top_left.y() + self.height()
        screen = self.screen() or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        x = max(avail.left(), min(x, avail.x() + avail.width() - w))
        if y + h > avail.y() + avail.height():
            y = top_left.y() - h            # no room below: open upwards
        y = max(avail.top(), min(y, avail.y() + avail.height() - h))
        pop.move(x, y)

    def _keep_on_screen(self, pop: QFrame) -> None:
        """Checked again once shown: a platform may still offset the window
        it was asked to place (the offscreen one adds a 2 px frame, measured),
        and a Cancel button off the edge is the failure this exists for."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        g = pop.frameGeometry()
        dx = min(0, avail.x() + avail.width() - (g.x() + g.width()))
        dx = dx or max(0, avail.x() - g.x())
        dy = min(0, avail.y() + avail.height() - (g.y() + g.height()))
        dy = dy or max(0, avail.y() - g.y())
        if dx or dy:
            pop.move(pop.x() + dx, pop.y() + dy)


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
        # The same icon size as the main toolbar's tools. A widget added to a
        # toolbar does not follow its icon size the way its actions do.
        indicator.match_icon_size(self.iconSize())
        self.iconSizeChanged.connect(indicator.match_icon_size)
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
