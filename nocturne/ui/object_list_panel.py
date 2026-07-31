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

    def _add_heading(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)   # not selectable, never activates
        item.setData(Qt.ItemDataRole.UserRole, None)
        f = item.font()
        f.setBold(True)
        f.setPointSizeF(max(1.0, f.pointSizeF() - 1))
        item.setFont(f)
        self.list.addItem(item)

    def set_contents(self, objects, stars=()) -> None:
        """Fill from the solve: deep-sky objects first, then named stars.

        Both go in because the list answers "what is in my frame", and a star the
        overlay labels but the list omits is a dead end — you can read 57 Cyg off
        the image and have nowhere to click. They stay in separate groups, stars
        last, so a wide field full of Bayer designations can never bury the
        handful of objects that are the actual subject.

        Deep-sky objects keep the overlay's own label ranking, so list and image
        read as one ranking rather than two; stars go brightest first, which is
        the only ordering a magnitude affords.

        Deliberately NOT filtered by density. Density governs how crowded the
        *image* gets, and the objects it drops are exactly the ones worth having
        somewhere clickable. It IS filtered by the layer toggles, which are about
        what you care about rather than about crowding.
        """
        from ..core.annotation_layout import priority_of
        self.list.clear()
        objects = list(objects)
        stars = list(stars)
        grouped = objects and stars     # headings earn their row only when both exist

        if grouped:
            self._add_heading("DEEP SKY")
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

        if grouped:
            self._add_heading("NAMED STARS")
        for s in sorted(stars, key=lambda x: x.mag):
            item = QListWidgetItem(f"{s.name}   mag {s.mag:.1f}")
            item.setData(Qt.ItemDataRole.UserRole, s.name)
            self.list.addItem(item)

        self.title.setText(f"Objects in field ({len(objects) + len(stars)})")

    def count(self) -> int:
        """Selectable rows only — group headings are not objects."""
        return sum(1 for i in range(self.list.count())
                   if self.list.item(i).data(Qt.ItemDataRole.UserRole) is not None)
