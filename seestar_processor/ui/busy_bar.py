from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from .theme import ACCENT

BUSY_BAR_HEIGHT = 3            # px
_ANIM_INTERVAL_MS = 33         # ~30 fps repaint while shown
_SWEEP_FRACTION = 0.30         # moving highlight width as a fraction of the track


class BusyBar(QWidget):
    """Thin animated indeterminate progress bar overlaid on a target's top edge.

    Never dims or covers the image body; mouse-transparent so it never blocks
    clicks on the canvas underneath. The animation timer runs only while shown.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._target: QWidget | None = None
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(_ANIM_INTERVAL_MS)
        self._timer.timeout.connect(self._advance)
        self.hide()

    def _advance(self) -> None:
        # Ensure geometry still matches target (in case resize event was missed)
        if self._target is not None and self.width() != self._target.width():
            self._reposition()
        self._phase = (self._phase + 0.03) % 1.0
        self.update()

    def _reposition(self) -> None:
        if self._target is not None:
            self.setGeometry(0, 0, self._target.width(), BUSY_BAR_HEIGHT)

    def show_over(self, widget: QWidget) -> None:
        if self._target is not None and self._target is not widget:
            self._target.removeEventFilter(self)
        self._target = widget
        self.setParent(widget)
        widget.installEventFilter(self)
        self._reposition()
        self._phase = 0.0
        self._timer.start()
        self.raise_()
        self.show()
        self.repaint()

    def hide_bar(self) -> None:
        self._timer.stop()
        if self._target is not None:
            self._target.removeEventFilter(self)
            self._target = None
        self.hide()

    def width(self) -> int:
        """Return width, syncing with target if present."""
        if self._target is not None:
            target_width = self._target.width()
            if super().width() != target_width:
                self.setGeometry(0, 0, target_width, BUSY_BAR_HEIGHT)
            return target_width
        return super().width()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._target and event.type() == QEvent.Type.Resize:
            self._reposition()
        return False

    def paintEvent(self, event) -> None:
        # Ensure geometry matches target before painting
        if self._target is not None:
            if self.width() != self._target.width():
                self._reposition()

        painter = QPainter(self)
        w = self.width()
        h = self.height()
        painter.fillRect(self.rect(), QColor(255, 255, 255, 30))   # faint track
        sweep_w = max(1, int(w * _SWEEP_FRACTION))
        x = int(self._phase * (w + sweep_w)) - sweep_w
        painter.fillRect(x, 0, sweep_w, h, QColor(ACCENT))         # moving highlight
