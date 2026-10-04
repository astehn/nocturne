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
        self._waiting = None            # a WaitingBlock, built on first use only

    def show_waiting(self, text: str, done: int | None = None,
                     total: int | None = None) -> None:
        """A ring above the text while there is no picture yet. Opt-in: only
        the finishing tools call it; show_message() is unchanged for the rest."""
        if self._waiting is None:
            from .progress_ring import WaitingBlock
            self._waiting = WaitingBlock(self)
            self.layout().addWidget(self._waiting, 0, 0)
        self._waiting.set_text(text)
        if done is None or total is None:
            self._waiting.set_indeterminate()
        else:
            self._waiting.set_progress(done, total)
        self.overlay.hide()
        self._waiting.show()
        self._waiting.raise_()

    def set_waiting_progress(self, done: int, total: int) -> None:
        if self._waiting is not None:
            self._waiting.set_progress(done, total)

    def waiting_block(self):
        return self._waiting

    def is_waiting(self) -> bool:
        return self._waiting is not None and not self._waiting.isHidden()

    def _end_wait(self) -> None:
        if self._waiting is not None:
            self._waiting.hide()

    def show_image(self, qimage: QImage) -> None:
        # ImageView deliberately keeps the current zoom/pan transform across
        # same-size images (so blink review compares subs at 1:1) and only
        # re-fits on the first image or a size change.
        self._end_wait()
        self.view.set_image(qimage)
        self.overlay.hide()
        self._has_image = True

    def show_message(self, text: str) -> None:
        self._end_wait()
        self.overlay.setText(text)
        self.overlay.show()

    def message_text(self) -> str:
        """What the overlay currently says — so a caller can update it in place
        (a star split counting up) and a test can read it back."""
        if self.is_waiting():
            return self._waiting.text()
        return self.overlay.text()

    def clear(self) -> None:
        self.view.set_image(QImage())          # blank the scene
        self._has_image = False
        self.show_message(PLACEHOLDER)

    def has_image(self) -> bool:
        return self._has_image
