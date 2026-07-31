from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout,
)


class ObjectListPanel(QFrame):
    """The solved field's objects, listed on the canvas rather than in the right
    column.

    It lived in the solve panel first and was unusable there: the right column is
    narrow, already shared with the histogram, clipping controls, step panel and
    help, and it scrolls — so a list of even a dozen objects became a two-row
    peephole. This is a navigation surface. It wants height, and it wants to sit
    beside the image so that picking a row and seeing where it went are one
    glance rather than two. The canvas has the room; the column never will.

    Anchored under the Annotations pill because it belongs to the same idea:
    what the overlay is showing you.
    """

    objectActivated = Signal(str)      # catalogue name of the picked row
    closeRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("objectListPanel")
        self.setFrameShape(QFrame.Shape.NoFrame)

        self.title = QLabel("Objects in field")
        self.title.setObjectName("objectListTitle")
        close_btn = QPushButton("✕")
        close_btn.setObjectName("objectListClose")
        close_btn.setFixedSize(22, 20)
        close_btn.setFlat(True)
        close_btn.setToolTip("Hide the object list")
        close_btn.clicked.connect(self.closeRequested)

        head = QHBoxLayout()
        head.setContentsMargins(10, 6, 6, 2)
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(close_btn)

        self.list = QListWidget()
        self.list.setObjectName("objectList")
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.itemClicked.connect(self._picked)
        self.list.itemActivated.connect(self._picked)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(2)
        lay.addLayout(head)
        lay.addWidget(self.list)
        self.hide()

    def _picked(self, item) -> None:
        name = item.data(Qt.ItemDataRole.UserRole)
        if name:
            self.objectActivated.emit(name)

    def set_objects(self, objects) -> None:
        """Fill from the solve's catalogue objects, ordered the way the overlay
        ranks labels — so the list and the image read as one ranking, not two."""
        from ..core.annotation_layout import priority_of
        self.list.clear()
        for o in sorted(objects, key=lambda x: (priority_of(x), x.major_arcmin),
                        reverse=True):
            label = f"{o.name}  {o.common}".strip() if o.common else o.name
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, o.name)
            if o.major_arcmin:
                item.setToolTip(f"{o.major_arcmin:.0f}′ across")
            if not o.centered:
                item.setToolTip((item.toolTip() + " · " if item.toolTip() else "")
                                + "centre lies outside the frame")
            self.list.addItem(item)
        self.title.setText(f"Objects in field ({len(objects)})")

    def count(self) -> int:
        return self.list.count()
