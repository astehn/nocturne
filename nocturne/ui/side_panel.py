"""The right column as fixed zones around one scrolling middle.

Every zone has the same height on every step, and the step panel scrolls
inside itself — so the panel's top edge and Next never move, and no step can
push the window taller. Only the histogram and the step zone share their room,
split by the window's height alone (the histogram yields first on a short
window, `_rebalance`); every other zone is fixed. Before this, the column grew
with its tallest content: Curves grew the whole window ~115 px and it never
shrank back, and the busy/warning lines grew upward and moved everything
above them (Andreas' screenshots, 2026-09-25; spec §4.2).

The status slot is reserved even when empty — his call: ~64 px is the price
of nothing ever changing, where the alternative would have covered Apply and
Reset whenever something ran.
"""
from __future__ import annotations

from typing import NamedTuple, Sequence

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QSizePolicy,
                               QStackedWidget, QVBoxLayout, QWidget)

from .progress_ring import ProgressRing
from .theme import CHANNEL_TINT, TEXT, TEXT_DIM, WARNING

# Measured 2026-09-25 at RIGHT_PANE_W (label width 382 px) under the app
# theme (Fusion + build_stylesheet), offscreen and cocoa alike: text lines
# 17 px, buttons 35, progress bar 19 (its minimum; its hint says 10), layout
# spacing 2, no margins. Busy = busy line 17 + bar 19 + elapsed/Cancel row 35
# + 2x2 = 75; error = two warning lines 34 + details row 35 + 2 = 71. Unthemed
# macOS style is smaller (busy 72, error 66). The old guess, 64, squeezed
# Cancel to 14 px.
STATUS_SLOT_H = 75
# The clipping read-out: two value lines + spacing 2, the Show clipping toggle
# beside them rather than under them. Measured 2026-10-14 under the app theme at
# RIGHT_PANE_W: lines 16 px on cocoa (17 offscreen), toggle 23, so 34 / 36 —
# 36 holds both. The old line-plus-checkbox slot was 54; the 18 px saved went to
# the step card (+11) and histogram (+7) at 1280x800, all to the histogram at
# 1440x900. Widest row: values end at x=258 of 376, toggle starts at 291.
CLIP_SLOT_H = 36
LINEAR_CLIP_TEXT = "Clipping is shown once the image is stretched."
# One legend for every clipping view — the main window's toggle and Starless
# Levels' own — so a mark never means two things in two places.
CLIP_LEGEND = ("The mark's colour is the channel that died:\n"
               "  red / green / blue — that one channel is at zero\n"
               "  yellow / magenta / cyan — those two are\n"
               "  white — all three, so the pixel really is black\n"
               "Amber marks a channel blown to white instead.")
CLIP_TOGGLE_TIP = ("Show clipping — paint the clipped pixels on the picture, "
                   "live, even mid-slider.\n\n" + CLIP_LEGEND)
_PER_CHANNEL_NOTE = (
    "Measured per CHANNEL, not per pixel. A pixel whose red alone sits at zero "
    "still shows colour from green and blue — but the red signal there is "
    "gone, and no later adjustment brings it back. In an HOO palette, red "
    "carries Ha.")
_ARROW = {"lo": ("▼", "▼ Crushed to black — how much of each channel sits at "
                      "zero, in the shadows.\n\n" + _PER_CHANNEL_NOTE),
          "hi": ("▲", "▲ Blown to white — how much of each channel sits at "
                      "full, in the highlights.\n\n" + _PER_CHANNEL_NOTE)}
_WIDEST_VALUE = "100.0%"
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


class ClipValue(NamedTuple):
    """One figure of the read-out: a channel's clipped fraction at one end,
    whether it is past the limit, and the words that explain it."""
    channel: str
    frac: float
    over: bool
    tooltip: str


class ClipReadout(QWidget):
    """Two fixed lines — ▼ crushed, ▲ blown — each R G B in the same place
    every time, with the Show clipping toggle beside them.

    The old single sentence named only the worst channel and was amber as a
    whole, so its wording and length changed from picture to picture and the
    eye stopped reading it (Andreas, IC 1396A, 2026-10-14). Now nothing moves:
    every cell has a fixed width, and only a value past its limit changes
    colour. What the sentence used to say lives in each value's tooltip."""

    ENDS = ("lo", "hi")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        numbers = QWidget()
        grid = QGridLayout(numbers)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(2)
        self._arrows: dict[str, QLabel] = {}
        self._letters: dict[tuple[str, int], QLabel] = {}
        self._values: dict[tuple[str, int], QLabel] = {}
        for r, end in enumerate(self.ENDS):
            glyph, tip = _ARROW[end]
            arrow = QLabel(glyph)
            arrow.setObjectName("clipArrow")
            arrow.setToolTip(tip)
            grid.addWidget(arrow, r, 0)
            self._arrows[end] = arrow
            for i, ch in enumerate("RGB"):
                letter = QLabel(ch)
                letter.setObjectName("clipLetter")
                letter.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                value = QLabel("0.0%")
                value.setObjectName("clipValue")
                # Left, against its own letter: right-aligned, a short value
                # sat nearer the NEXT letter and "7.4%  G" read as green's.
                value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                grid.addWidget(letter, r, 1 + 2 * i)
                grid.addWidget(value, r, 2 + 2 * i)
                self._letters[(end, i)] = letter
                self._values[(end, i)] = value
        grid.setColumnStretch(7, 1)
        self._numbers = numbers
        self.linear_label = QLabel(LINEAR_CLIP_TEXT)
        self.linear_label.setObjectName("clipLinear")
        self.linear_label.setWordWrap(True)
        self.linear_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._stack.addWidget(numbers)
        self._stack.addWidget(self.linear_label)
        row.addWidget(self._stack, 1)

        # Checkable, like Crop's segment buttons; the full name fits beside the
        # numbers at the fixed pane width (measured, see CLIP_SLOT_H).
        self.toggle = QPushButton("Show clipping")
        self.toggle.setObjectName("shapeSeg")
        self.toggle.setCheckable(True)
        self.toggle.setToolTip(CLIP_TOGGLE_TIP)
        self.toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        row.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignVCenter)

        self._fitted_for = None
        self.set_values([ClipValue(c, 0.0, False, "") for c in "RGB"],
                        [ClipValue(c, 0.0, False, "") for c in "RGB"])

    # -- access, for MainWindow and the tests --
    def arrow(self, end: str) -> QLabel:
        return self._arrows[end]

    def letter_label(self, end: str, i: int) -> QLabel:
        return self._letters[(end, i)]

    def value_label(self, end: str, i: int) -> QLabel:
        return self._values[(end, i)]

    def is_linear(self) -> bool:
        return self._stack.currentWidget() is self.linear_label

    # -- state --
    def set_linear(self) -> None:
        self._stack.setCurrentWidget(self.linear_label)
        self.linear_label.setEnabled(False)
        self.toggle.setEnabled(False)

    def set_values(self, lo: Sequence[ClipValue], hi: Sequence[ClipValue]) -> None:
        for end, vals in (("lo", lo), ("hi", hi)):
            for i in range(3):
                letter, value = self._letters[(end, i)], self._values[(end, i)]
                shown = i < len(vals)
                letter.setVisible(shown)
                value.setVisible(shown)
                if not shown:
                    continue
                v = vals[i]
                letter.setText(v.channel)
                tint = CHANNEL_TINT.get(v.channel, TEXT)
                letter.setStyleSheet(f"color: {tint}; font-weight: 600;")
                value.setText(f"{v.frac * 100:.1f}%")
                # Grey when fine, amber past the limit — and nothing else
                # changes, so the eye goes straight to the one that matters.
                value.setStyleSheet(f"color: {WARNING}; font-weight: 700;" if v.over
                                    else f"color: {TEXT_DIM};")
                value.setToolTip(v.tooltip)
        self._stack.setCurrentWidget(self._numbers)
        self.linear_label.setEnabled(True)
        self.toggle.setEnabled(True)

    # -- fixed cell widths --
    def _fit_cells(self) -> None:
        """Every value cell as wide as its widest possible text in BOLD, so a
        value turning amber or reaching 100% never moves its neighbours. From
        the polished font, since the stylesheet sets the size."""
        value = self._values[("lo", 0)]
        value.ensurePolished()
        key = (value.font().key(), self._letters[("lo", 0)].font().key())
        if key == self._fitted_for:
            return
        self._fitted_for = key
        bold = value.font()
        bold.setWeight(bold.Weight.Bold)
        from PySide6.QtGui import QFontMetrics
        # The spare room trails the value, so it separates channel groups.
        w_val = QFontMetrics(bold).horizontalAdvance(_WIDEST_VALUE) + 12
        letter = self._letters[("lo", 0)]
        letter.ensurePolished()
        lf = letter.font()
        lf.setWeight(lf.Weight.DemiBold)
        w_let = max(QFontMetrics(lf).horizontalAdvance(c) for c in "RGBL") + 2
        for lab in self._values.values():
            lab.setFixedWidth(w_val)
        for lab in self._letters.values():
            lab.setFixedWidth(w_let)
        for lab in self._arrows.values():
            lab.ensurePolished()
            lab.setFixedWidth(lab.fontMetrics().horizontalAdvance("▼") + 2)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._fit_cells()
        super().showEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self._fit_cells()
        super().changeEvent(event)


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
        clip_lay.setSpacing(0)
        self.clip_readout = ClipReadout()
        self.clip_toggle = self.clip_readout.toggle
        clip_lay.addWidget(self.clip_readout)
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
        self.action_slot.setFixedHeight(0)   # 0 until MainWindow sets the real height (Task 5)
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
        # The finishing tools' ring, small, beside what is running (Andreas,
        # 2026-10-04): ONE "working" signal across the app. It spins with no
        # number and fills when a percentage exists; the number itself is the
        # `progress` text on the row below. It replaced a QProgressBar that
        # was simply hidden whenever no percentage came, leaving SPCC, plate
        # solving and saving with nothing that moved at all.
        self.busy_ring = ProgressRing(size="small")
        self.busy_ring.hide()
        busy_line = QHBoxLayout()
        busy_line.setSpacing(6)
        busy_line.addWidget(self.busy_ring, 0, Qt.AlignmentFlag.AlignVCenter)
        busy_line.addWidget(self.busy_label, 1)
        self.progress = QLabel("")
        self.progress.setStyleSheet("color: #9aa0a6;")
        self.progress.hide()
        busy_row = QHBoxLayout()
        busy_row.addWidget(self.progress)
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
        st.addWidget(self.peek_label)
        st.addLayout(busy_line)
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
        # Opt-in, never default: a panel that lays something at its bottom
        # edge (Stretch's SPCC note, directly above Apply) takes the spare
        # height itself; every other panel keeps it below, as before.
        fill = bool(getattr(new, "fill_height", False))
        # By position, not a fixed index: MainWindow inserts the explainer and
        # the help link between the panel and the trailing stretch.
        lay = self.body_layout
        lay.setStretch(lay.indexOf(new), 1 if fill else 0)
        lay.setStretch(lay.count() - 1, 0 if fill else 1)

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

    def set_clipping(self, lo: Sequence[ClipValue] | None,
                     hi: Sequence[ClipValue] | None = None) -> None:
        """None = linear: the message takes the numbers' place and the toggle
        greys. The slot keeps its height either way, so the panel below does
        not jump when the image passes Stretch."""
        if lo is None:
            self.clip_readout.set_linear()
        else:
            self.clip_readout.set_values(lo, hi or [])
