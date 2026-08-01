from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget


class AnnotationPill(QWidget):
    """Floating show/hide toggle for the plate-solve overlay.

    The overlay is a VIEW state, not part of the Plate Solve tool: you solve
    once, then keep working through the pipeline with the annotations up. So
    it needs a control that outlives the tool panel — hence a pill on the
    canvas rather than a checkbox inside the panel, which would force the tool
    open again just to hide a label.

    Hidden entirely until a solution exists; there is nothing to toggle before
    that."""

    def __init__(self, on_toggled, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("zoomPill")          # reuses the existing pill styling
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(2)
        self.button = QPushButton("Annotations")
        self.button.setCheckable(True)
        self.button.setChecked(True)
        self.button.setFlat(True)
        self.button.setToolTip("Show or hide the plate-solve overlay")
        self.button.toggled.connect(on_toggled)
        lay.addWidget(self.button)
        self.hide()

    def set_shown(self, shown: bool) -> None:
        """Reflect overlay state without re-emitting (callers drive both ways)."""
        was = self.button.blockSignals(True)
        self.button.setChecked(shown)
        self.button.blockSignals(was)

    def is_shown(self) -> bool:
        """Whether the overlay is currently on. Read by anything that follows the
        overlay rather than duplicating its switch — the object list does."""
        return self.button.isChecked()
