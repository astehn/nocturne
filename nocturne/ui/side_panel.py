"""The right column as fixed zones around one scrolling middle.

Every zone except the step panel has a FIXED height on every step, and the
step panel scrolls inside itself — so the panel's top edge and Next never
move, and no step can push the window taller. Before this, the column grew
with its tallest content: Curves grew the whole window ~115 px and it never
shrank back, and the busy/warning lines grew upward and moved everything
above them (Andreas' screenshots, 2026-09-25; spec §4.2).

The status slot is reserved even when empty — his call: ~64 px is the price
of nothing ever changing, where the alternative would have covered Apply and
Reset whenever something ran.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

# Measured 2026-09-25 at RIGHT_PANE_W (label width 382 px) under the app
# theme (Fusion + build_stylesheet), offscreen and cocoa alike: text lines
# 17 px, buttons 35, progress bar 19 (its minimum; its hint says 10), layout
# spacing 2, no margins. Busy = busy line 17 + bar 19 + elapsed/Cancel row 35
# + 2x2 = 75; error = two warning lines 34 + details row 35 + 2 = 71. Unthemed
# macOS style is smaller (busy 72, error 66). The old guess, 64, squeezed
# Cancel to 14 px.
STATUS_SLOT_H = 75
# Two clip lines (16 px each themed, 15-16 unthemed) + spacing 2 + the
# checkbox (18 themed, 20 unthemed) = 54. The longest real line, "…crushed
# to zero — scattered noise, not lost detail", wraps to two lines at 382 px;
# the old 40 left one line and elided the qualifier.
CLIP_SLOT_H = 54
LINEAR_CLIP_TEXT = "Clipping is shown once the image is stretched."
# What the step's scrolling zone gets BEFORE the histogram grows back toward
# its natural height: 208 px is what that zone measured at 1280x800 under the
# app stylesheet on main before the consistent-panels branch (2026-09-25), when
# Apply/Reset and the title still scrolled inside it. Andreas' call the same
# day: on short windows the histogram gives up height first, the way the
# activity box does in the left column.
SCROLL_COMFORT_H = 208


def _wrap_words(text: str, metrics, width: int) -> list[str]:
    """Greedy word-wrap of `text` to `width` px, using `metrics` to measure."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        if metrics.horizontalAdvance(trial) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


class _ElidingLabel(QLabel):
    """A label whose real value can be any length but whose ON-SCREEN space
    cannot grow: both size-policy axes are Ignored, so it never pushes the
    fixed-height slot it lives in.

    Plain word-wrap into a cropped box hides the overflow with no cue — the
    text is just cut off mid-word, silently. This wraps to the label's own
    width and, if the wrapped text needs more lines than currently fit,
    truncates the visible lines and ends the last one with "…". `text()`
    still returns the FULL value (callers compare against the real string;
    the activity log gets the untruncated text too) — only the rendered
    glyphs are shortened. The tooltip carries the full text as well, so it's
    always one hover away.
    """

    def __init__(self, object_name: str = "") -> None:
        super().__init__("")
        if object_name:
            self.setObjectName(object_name)
        self._full_text = ""
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def text(self) -> str:
        return self._full_text

    def setText(self, text: str) -> None:  # noqa: N802 - Qt override
        self._full_text = text
        self.setToolTip(text)
        self._re_elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._re_elide()

    def _re_elide(self) -> None:
        full = self._full_text
        width = self.contentsRect().width()
        if not full or width <= 0:
            super().setText(full)
            return

        metrics = self.fontMetrics()
        lines = _wrap_words(full, metrics, width)
        line_height = metrics.lineSpacing() or metrics.height()
        available_h = self.height()
        max_lines = max(1, available_h // line_height) if available_h > 0 else len(lines)

        if len(lines) <= max_lines:
            super().setText(full)
            return

        words = full.split()
        consumed = sum(len(l.split()) for l in lines[: max_lines - 1])
        remainder = " ".join(words[consumed:])
        last = metrics.elidedText(remainder, Qt.TextElideMode.ElideRight, width)
        visible = lines[: max_lines - 1] + [last]
        super().setText("\n".join(visible))


class SidePanel(QWidget):
    def __init__(self, width: int, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(width)
        self.layout_ = QVBoxLayout(self)

        # histogram + info strip (MainWindow adds its widgets here; the
        # histogram itself through set_histogram, so its height can yield)
        self.histogram_zone = QVBoxLayout()
        self.layout_.addLayout(self.histogram_zone)
        self._hist: QWidget | None = None

        # clipping slot — fixed height, always present
        self.clip_slot = QWidget()
        self.clip_slot.setFixedHeight(CLIP_SLOT_H)
        clip_lay = QVBoxLayout(self.clip_slot)
        clip_lay.setContentsMargins(0, 0, 0, 0)
        clip_lay.setSpacing(2)
        self.clip_line = _ElidingLabel("importMeta")
        self.clip_check = QCheckBox("Show clipping")
        clip_lay.addWidget(self.clip_line, 1)
        clip_lay.addWidget(self.clip_check)
        self.layout_.addWidget(self.clip_slot)

        # ONE card (Ruling R6, the approved mockup): a rounded BG_2 frame
        # holding the step's fixed header on top and its scrolling controls
        # below, so the title reads as part of the card it names and the
        # scrollbar sits inside the card at its right edge. theme.py makes
        # everything plain inside it transparent: one visible surface.
        self.step_frame = QFrame()
        self.step_frame.setObjectName("stepFrame")
        frame_lay = QVBoxLayout(self.step_frame)
        frame_lay.setContentsMargins(0, 0, 0, 0)
        frame_lay.setSpacing(0)

        # The step's title row and two-line description, FIXED above the
        # scrolling controls (spec §3): a tall step scrolls its controls, never
        # its name. Handed in by MainWindow with set_header, like the actions.
        self.header_slot = QWidget()
        self.header_slot.setObjectName("stepHeaderSlot")
        self._header_lay = QVBoxLayout(self.header_slot)
        self._header_lay.setContentsMargins(0, 0, 0, 0)
        self._header_lay.setSpacing(0)
        frame_lay.addWidget(self.header_slot)

        # the one flexible zone
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(0)
        # Its own size hint must not compete with the histogram's: the zone
        # takes what is left (stretch 1) and _rebalance decides the split.
        self.scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        self.scroll.installEventFilter(self)
        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.panel = QWidget()
        self.body_layout.addWidget(self.panel)
        self.body_layout.addStretch(1)
        self.scroll.setWidget(body)
        frame_lay.addWidget(self.scroll, 1)
        self.layout_.addWidget(self.step_frame, 1)

        # The step's main action + Reset, pinned: the same place on every step
        # (Andreas, 2026-09-25 — "about muscle memory again"). Outside the
        # scroll area so a tall step (Curves) scrolls its controls, never Apply.
        # ONE row (his "one row + histogram" call, the same day): Apply takes
        # the stretch, Reset step sits at the right at its own size.
        self.action_slot = QWidget()
        self._action_lay = QHBoxLayout(self.action_slot)
        self._action_lay.setContentsMargins(0, 6, 0, 0)
        self._action_lay.setSpacing(8)
        self.action_slot.setFixedHeight(0)   # 0 until MainWindow sets the look's height (Task 5)
        self.layout_.addWidget(self.action_slot)

        # status slot — fixed height, reserved while empty
        self.status_slot = QWidget()
        self.status_slot.setFixedHeight(STATUS_SLOT_H)
        st = QVBoxLayout(self.status_slot)
        st.setContentsMargins(0, 0, 0, 0)
        st.setSpacing(2)
        self.peek_label = _ElidingLabel()
        self.peek_label.setStyleSheet("color: #9aa0a6;")
        self.busy_label = _ElidingLabel()
        self.busy_label.setStyleSheet("color: #9aa0a6;")
        self.progress = QProgressBar()
        self.progress.hide()
        busy_row = QHBoxLayout()
        self.elapsed_label = QLabel("")
        self.elapsed_label.setStyleSheet("color: #9aa0a6;")
        self.elapsed_label.hide()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.hide()
        busy_row.addWidget(self.elapsed_label)
        busy_row.addStretch(1)
        busy_row.addWidget(self.cancel_btn)
        self.warning = _ElidingLabel("warning")
        self.warning.setStyleSheet("color: #ff6b6b;")
        diag_row = QHBoxLayout()
        self.details_btn = QPushButton("Show details")
        self.details_btn.setFlat(True)
        self.details_btn.hide()
        self.copy_log_btn = QPushButton("Copy log")
        self.copy_log_btn.setFlat(True)
        self.copy_log_btn.hide()
        diag_row.addWidget(self.details_btn)
        diag_row.addWidget(self.copy_log_btn)
        diag_row.addStretch(1)
        for w in (self.peek_label, self.busy_label, self.progress):
            st.addWidget(w)
        st.addLayout(busy_row)
        st.addWidget(self.warning, 1)
        st.addLayout(diag_row)
        self.layout_.addWidget(self.status_slot)

        # nav — the LAST item (flush-nav invariant)
        nav = QHBoxLayout()
        self.back_btn = QPushButton("← Back")
        self.next_btn = QPushButton("Next →")
        self.next_btn.setObjectName("nav")
        nav.addWidget(self.back_btn)
        nav.addWidget(self.next_btn)
        self.layout_.addLayout(nav)

    def set_panel(self, new: QWidget) -> None:
        self.body_layout.replaceWidget(self.panel, new)
        self.panel.setParent(None)
        self.panel.deleteLater()
        self.panel = new

    def set_action_height(self, h: int) -> None:
        self.action_slot.setFixedHeight(h)

    @staticmethod
    def _clear(lay, keep) -> None:
        """Empty a slot's layout. A widget added to a slot is parented to it,
        so the slot — not the step that built it — owns it: detaching with
        setParent(None) alone would leave it owned by nobody and never
        destroyed, one leak per step change. Anything not being passed back in
        gets deleteLater()."""
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None and all(w is not k for k in keep):
                # Hidden at once: until the deferred delete lands it would
                # still paint, and inside the transparent step frame the old
                # step's title showed through the new one's.
                w.hide()
                w.deleteLater()

    def set_header(self, header: QWidget | None) -> None:
        """Replace the fixed header (the step's title row + description)."""
        self._clear(self._header_lay, (header,))
        if header is not None:
            self._header_lay.addWidget(header)

    def set_actions(self, primary: QWidget | None, reset: QWidget | None) -> None:
        """Replace the pinned action row: the main action on the left taking
        the stretch, Reset step at the right at its own size. No divider —
        the row is the whole grammar now, and nothing else may sit in it.

        With no main action (Enhancements) a stretch stands in for it, so
        Reset keeps its right-hand place and never moves between steps.
        """
        self._clear(self._action_lay, (primary, reset))
        if primary is not None:
            self._action_lay.addWidget(primary, 1)
        else:
            self._action_lay.addStretch(1)
        if reset is not None:
            reset.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._action_lay.addWidget(reset, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_histogram(self, view: QWidget) -> None:
        """Add the histogram as the zone's yielding part (see _rebalance)."""
        from .histogram_view import HIST_FLOOR_H
        self._hist = view
        view.setFixedHeight(HIST_FLOOR_H)
        self.histogram_zone.insertWidget(0, view)
        self._rebalance()

    def _rebalance(self) -> None:
        """Split the room the histogram and the step zone share.

        The step zone gets up to SCROLL_COMFORT_H first; only then does the
        histogram grow back toward its natural height, and past that the step
        zone takes the rest. On a short window the histogram therefore yields
        first, down to its readable floor, and only then the step zone.

        The split depends on the window size alone, never on the step, so
        nothing moves between steps. Their sum is the column height minus
        every fixed zone whatever the split is (the step zone takes all that
        is left), so reading it off the current geometry is stable.
        """
        from .histogram_view import HIST_FLOOR_H, HIST_NATURAL_H
        if self._hist is None:
            return
        both = self.scroll.height() + self._hist.height()
        target = max(HIST_FLOOR_H, min(HIST_NATURAL_H, both - SCROLL_COMFORT_H))
        if self._hist.height() != target or self._hist.minimumHeight() != target:
            self._hist.setFixedHeight(target)
            # Settle now, not on the next pass of the event loop: a reader
            # right after a resize must see the final split, not a transient.
            self.layout_.activate()

    def minimumSizeHint(self):  # noqa: N802 (Qt override)
        """The column's true minimum: the histogram at its floor, whatever
        height _rebalance has fixed it at for the current window. Without
        this the window could never be made shorter than its current size."""
        from .histogram_view import HIST_FLOOR_H
        hint = super().minimumSizeHint()
        if self._hist is not None:
            hint.setHeight(hint.height() - (self._hist.minimumHeight() - HIST_FLOOR_H))
        return hint

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._rebalance()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        # The step zone also changes size when a fixed zone above or below it
        # does (the header arriving, the action height being set).
        if obj is self.scroll and event.type() == QEvent.Type.Resize:
            self._rebalance()
        return super().eventFilter(obj, event)

    def set_clipping(self, text: str | None, tooltip: str = "") -> None:
        """None = linear. The slot keeps its height either way, so the panel
        below does not jump when the image passes Stretch."""
        if text is None:
            self.clip_line.setText(LINEAR_CLIP_TEXT)
            self.clip_line.setToolTip("")
            self.clip_line.setEnabled(False)
            self.clip_check.setEnabled(False)
        else:
            self.clip_line.setText(text)
            # The full line first, so an elided qualifier is always one hover away.
            self.clip_line.setToolTip(f"{text}\n\n{tooltip}" if tooltip else text)
            self.clip_line.setEnabled(True)
            self.clip_check.setEnabled(True)
