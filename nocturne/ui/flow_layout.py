"""Items left to right, wrapping WHOLE items onto the next line.

Qt has no flow layout of its own; this is its documented example, trimmed.
The verdict strip needs it: its labelled facts sit in one row and, on a
narrow window, wrap into labelled lines — never into one run-on paragraph
(spec 2026-09-28 §2.4).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QWidget


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, h_spacing: int = 14,
                 v_spacing: int = 2) -> None:
        super().__init__(parent)
        self._items = []
        self._h, self._v = h_spacing, v_spacing
        self.setContentsMargins(0, 0, 0, 0)

    # --- QLayout ---
    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        """The widest item across, and — like WrappedNote — the WRAPPED
        height at the width the layout has, so a dialog that reads
        minimumSizeHint (StackDialog._settled_minimum_height) sees every line.
        Before the first geometry, one line."""
        widest = QSize(0, 0)
        for item in self._shown():
            widest = widest.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        width = self.geometry().width()
        height = self.heightForWidth(width) if width > 0 else widest.height()
        return QSize(widest.width() + m.left() + m.right(), height)

    # --- the flow ---
    def _shown(self) -> list:
        return [item for item in self._items if not item.isEmpty()]

    def _arrange(self, rect: QRect, apply: bool) -> int:
        """Lay the items out in `rect` (or only measure); returns the height."""
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = area.x(), area.y(), 0
        for item in self._shown():
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.x() + area.width():
                x, y, line_h = area.x(), y + line_h + self._v, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._h
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


class FlowBox(QWidget):
    """A widget holding a FlowLayout that tells its parent layout when its
    width — and so its wrapped height — changed, as WrappedNote does."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.flow = FlowLayout(self)
        self._last_width = -1

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if event.size().width() != self._last_width:
            self._last_width = event.size().width()
            self.updateGeometry()
