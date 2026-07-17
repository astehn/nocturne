from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from .image_view import ImageView

PLACEHOLDER = "Select a frame\nto preview it"


class FramePreview(QWidget):
    """A pan/zoomable frame preview (ImageView) with a message overlay for
    the empty and error states. Display only — loading/caching is the
    owner's job."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.view = ImageView(self)
        self.overlay = QLabel(PLACEHOLDER, self)
        self.overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.overlay.setObjectName("previewOverlay")
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(self.view, 0, 0)
        grid.addWidget(self.overlay, 0, 0)
        self._has_image = False

    def show_image(self, qimage: QImage) -> None:
        # ImageView deliberately keeps the current zoom/pan transform across
        # same-size images (so blink review compares subs at 1:1) and only
        # re-fits on the first image or a size change.
        self.view.set_image(qimage)
        self.overlay.hide()
        self._has_image = True

    def show_message(self, text: str) -> None:
        self.overlay.setText(text)
        self.overlay.show()

    def clear(self) -> None:
        self.view.set_image(QImage())          # blank the scene
        self._has_image = False
        self.show_message(PLACEHOLDER)

    def has_image(self) -> bool:
        return self._has_image
