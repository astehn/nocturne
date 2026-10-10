"""A circular progress ring for the finishing tools' waits.

Their only sign of life was a line of text ("Separating stars… — 46%"), which
Andreas found cheap-looking in an otherwise polished app (2026-10-04). One
painted ring, three sizes, the look approved from a mock-up: a grey track, the
accent arc filling clockwise from 12 o'clock with the percentage in the
centre, or a rotating quarter arc when no honest percentage exists.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from . import theme

_SIZES = {"large": (68, 6.0), "medium": (34, 3.0), "small": (18, 2.5)}
_SPIN_MS = 16           # ~60 fps while visible, nothing while hidden
_SPIN_STEP = 6          # degrees per tick: one turn a second
_SPIN_SPAN = 90         # the indeterminate arc: a quarter


class ProgressRing(QWidget):
    def __init__(self, parent=None, *, size: str = "large") -> None:
        super().__init__(parent)
        self._diameter, self._stroke = _SIZES[size]
        self._numbered = size == "large"
        self._fraction: float | None = None
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(_SPIN_MS)
        self._timer.timeout.connect(self._advance)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(self.sizeHint())

    def sizeHint(self) -> QSize:  # noqa: N802
        side = int(self._diameter + 2)
        return QSize(side, side)

    def diameter(self) -> int:
        return self._diameter

    def stroke(self) -> float:
        return self._stroke

    def fraction(self) -> float | None:
        return self._fraction

    def is_spinning(self) -> bool:
        return self._timer.isActive()

    def centre_text(self) -> str:
        if not self._numbered or self._fraction is None:
            return ""
        return f"{round(self._fraction * 100)}%"

    def set_progress(self, done: int, total: int) -> None:
        if total is None or total <= 0:
            self.set_indeterminate()
            return
        self._fraction = min(max(done / total, 0.0), 1.0)
        self._sync_timer()
        self.update()

    def set_indeterminate(self) -> None:
        self._fraction = None
        self._sync_timer()
        self.update()

    # --- timer only while it can be seen ---
    def _sync_timer(self) -> None:
        want = self._fraction is None and self.isVisible()
        if want and not self._timer.isActive():
            self._timer.start()
        elif not want and self._timer.isActive():
            self._timer.stop()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._timer.stop()

    def _advance(self) -> None:
        self._angle = (self._angle + _SPIN_STEP) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = self._stroke / 2 + 1
        side = self.width()
        rect = QRectF(inset, inset, side - 2 * inset, side - 2 * inset)
        track = QPen(QColor(255, 255, 255, 38), self._stroke)
        p.setPen(track)
        p.drawEllipse(rect)
        arc = QPen(QColor(theme.ACCENT), self._stroke)
        arc.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(arc)
        # Qt angles: 1/16 degree, 0 at 3 o'clock, positive counter-clockwise.
        if self._fraction is None:
            p.drawArc(rect, int((90 - self._angle) * 16), int(-_SPIN_SPAN * 16))
        elif self._fraction > 0:
            p.drawArc(rect, 90 * 16, int(-360 * self._fraction * 16))
        text = self.centre_text()
        if text:
            f = QFont(self.font())
            f.setPixelSize(17)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(theme.TEXT))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        p.end()


class WaitingBlock(QWidget):
    """A large ring above a centred line of text: what a tool shows while there
    is no picture yet to put anything over."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.ring = ProgressRing(self)
        self.label = QLabel("", self)
        self.label.setObjectName("previewOverlay")
        self.label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.label.setWordWrap(True)
        # The global `QWidget { background: BG_1 }` rule otherwise boxes the
        # text in a dark rectangle over the preview. Set here, not as a global
        # QLabel#previewOverlay rule, which would change FramePreview's own
        # placeholder too. Measured under build_stylesheet() in
        # tests/ui/test_progress_ring.py; WA_TranslucentBackground passes the
        # same test, this is the one that reads as what it means.
        self.label.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        lay.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(14)
        lay.addWidget(self.label, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)

    def set_text(self, text: str) -> None:
        self.label.setText(text)

    def text(self) -> str:
        return self.label.text()

    def set_progress(self, done: int, total: int) -> None:
        self.ring.set_progress(done, total)

    def set_indeterminate(self) -> None:
        self.ring.set_indeterminate()
