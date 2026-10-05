from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .. import APP_NAME, APP_TAGLINE

# How many recent projects the start page lists. The menu keeps up to eight;
# the start page is a quick way back to the last few, not an archive.
RECENT_SHOWN = 5


class WelcomeScreen(QWidget):
    """The start page: every way in — a stack, an image, a saved project, a
    Ha/OIII stack — and the projects you were last working on (Andreas,
    2026-10-05: it offered two ways in where there are four)."""

    def __init__(self, on_open, on_stack, on_open_project=None, on_haoiii=None,
                 on_recent=None, recent=None, locked=None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("welcome")
        self._on_recent = on_recent
        self._recent = recent or (lambda: [])
        # Is the app busy? A button made while work runs must start locked,
        # like the ones the main window locked when the work began.
        self._locked = locked or (lambda: False)
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel(APP_NAME)
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline = QLabel(APP_TAGLINE)
        tagline.setObjectName("welcomeTag")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("Stack a night's frames, or open an image or a saved project")
        hint.setObjectName("welcomeHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.open_btn = QPushButton("Open Image")
        self.open_btn.clicked.connect(lambda: on_open())
        self.open_project_btn = QPushButton("Open Project…")
        self.open_project_btn.clicked.connect(lambda: on_open_project and on_open_project())
        self.haoiii_btn = QPushButton("Ha/OIII…")
        self.haoiii_btn.setToolTip("Stack a dual-band (Ha/OIII) session")
        self.haoiii_btn.clicked.connect(lambda: on_haoiii and on_haoiii())
        # Stack stays the one green button, where it always was: most nights
        # start there, and the others are the quieter ways in.
        self.stack_btn = QPushButton("Stack…")
        self.stack_btn.setObjectName("primary")
        self.stack_btn.clicked.connect(lambda: on_stack())
        buttons = QHBoxLayout()
        buttons.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for b in (self.open_btn, self.open_project_btn, self.haoiii_btn, self.stack_btn):
            buttons.addWidget(b)

        # A new release, announced once (Andreas, 2026-09-26: no pop-up). Its
        # room is reserved from the start: the check lands seconds after launch,
        # and an appearing line would lift the centred buttons under the cursor.
        self.update_note = QLabel("")
        self.update_note.setObjectName("welcomeUpdate")
        self.update_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.update_note.setOpenExternalLinks(True)
        self.update_note.setWordWrap(True)      # a narrow window wraps into the reserved second line
        self.update_note.setFixedHeight(self.update_note.fontMetrics().lineSpacing() * 2)

        # Below everything else, in room reserved for the longest list: the page
        # is centred, so a list that grew or emptied would move the buttons.
        self.recent_title = QLabel("Recent projects")
        self.recent_title.setObjectName("welcomeRecentTitle")
        self.recent_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._recent_area = QWidget()
        self._recent_box = QVBoxLayout(self._recent_area)
        self._recent_box.setContentsMargins(0, 0, 0, 0)
        self._recent_box.setSpacing(2)
        self._recent_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._recent_box.addWidget(self.recent_title)
        row = QPushButton("x").sizeHint().height()
        self._recent_area.setFixedHeight(
            self.recent_title.sizeHint().height() + (row + 2) * RECENT_SHOWN + 4)
        self.recent_buttons: list[QPushButton] = []

        root.addWidget(title)
        root.addWidget(tagline)
        root.addSpacing(8)
        root.addWidget(hint)
        root.addSpacing(20)
        root.addLayout(buttons)
        root.addSpacing(16)
        root.addWidget(self.update_note)
        root.addSpacing(12)
        root.addWidget(self._recent_area)
        self.refresh_recent()

    def set_update_note(self, html: str) -> None:
        self.update_note.setText(html)

    def refresh_recent(self) -> None:
        """Re-read the list: projects saved or opened since the page was last
        shown appear, and files that have gone (moved, deleted, a disconnected
        drive) are left out rather than offered and then refused."""
        for b in self.recent_buttons:
            self._recent_box.removeWidget(b)
            b.deleteLater()
        self.recent_buttons = []
        paths = [p for p in self._recent() if os.path.isfile(p)][:RECENT_SHOWN]
        for path in paths:
            name = os.path.splitext(os.path.basename(path))[0]
            b = QPushButton(name)
            b.setObjectName("welcomeRecent")
            b.setToolTip(path)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFlat(True)
            b.setEnabled(not self._locked())
            b.clicked.connect(lambda _=False, p=path: self._on_recent and self._on_recent(p))
            self._recent_box.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
            self.recent_buttons.append(b)
        self.recent_title.setVisible(bool(paths))

    def showEvent(self, event) -> None:
        self.refresh_recent()
        super().showEvent(event)
