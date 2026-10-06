from __future__ import annotations

import os

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from .. import APP_NAME, APP_TAGLINE
from ..history.project_store import read_preview
from .progress_ring import ProgressRing
from .side_panel import _ElidingLabel

# The last few projects, as thumbnail cards in ONE row (Andreas, 2026-10-06:
# "4 larger ones"). The menu keeps up to eight; the start page is a quick way
# back to recent work, not an archive. Four cards of CARD_W fit across the
# smallest window (1120 px) with room to spare, and one row adds the least height.
RECENT_SHOWN = 4
CARD_W, CARD_H = 200, 134          # the picture box; 3:2 like most finished frames
_CARD_BG = QColor("#141519")
_ICON = Path(__file__).resolve().parent.parent / "assets" / "nocturne_icon.svg"


def _card_pixmap(jpeg: bytes | None, dpr: float) -> QPixmap:
    """The picture fitted inside the card box, centred on a dark ground — a
    tall drizzled frame and a wide one get cards of the same size. With no
    preview (a project saved before thumbnails existed), the crescent."""
    w, h = int(CARD_W * dpr), int(CARD_H * dpr)
    out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(_CARD_BG)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    img = QImage.fromData(jpeg) if jpeg else QImage()
    if not img.isNull():
        scaled = img.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        p.drawImage((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
    else:
        side = h * 0.5
        QSvgRenderer(str(_ICON)).render(p, QRectF((w - side) / 2, (h - side) / 2, side, side))
    p.end()
    pm = QPixmap.fromImage(out)
    pm.setDevicePixelRatio(dpr)
    return pm


class _RecentArea(QWidget):
    """Asks for the full row's width but demands none of it. A fixed width
    kept the centred buttons still, and also became the minimum of the stack
    the start page shares with the image view — 1568 px, against a window
    floor of 1120 (test_window_geometry caught it)."""

    def __init__(self) -> None:
        super().__init__()
        self.hint = QSize(0, 0)

    def sizeHint(self) -> QSize:
        return self.hint

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.hint.height())


class WelcomeScreen(QWidget):
    """The start page: every way in — a stack, an image, a saved project, a
    Ha/OIII stack — and the projects you were last working on (Andreas,
    2026-10-05: it offered two ways in where there are four)."""

    def __init__(self, on_open, on_stack, on_open_project=None, on_haoiii=None,
                 on_recent=None, recent=None, locked=None, on_cancel=None,
                 parent=None) -> None:
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

        # The open's sign of life. The panel's busy row lives in the right
        # column, which the start page hides, so an image or project opened
        # from here showed nothing for seconds (review 2026-10-06). Its room
        # is reserved like the update note's: a row appearing would move the
        # centred buttons under the cursor.
        self.busy_row = QWidget()
        self.busy_ring = ProgressRing(size="small")
        self.busy_label = QLabel("")
        self.busy_label.setObjectName("welcomeBusy")
        self.busy_cancel = QPushButton("Cancel")
        self.busy_cancel.clicked.connect(lambda: on_cancel and on_cancel())
        busy = QHBoxLayout(self.busy_row)
        busy.setContentsMargins(0, 0, 0, 0)
        busy.setSpacing(8)
        busy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        busy.addWidget(self.busy_ring, 0, Qt.AlignmentFlag.AlignVCenter)
        busy.addWidget(self.busy_label)
        busy.addWidget(self.busy_cancel)
        self.busy_row.setFixedHeight(self.busy_cancel.sizeHint().height())
        for w in (self.busy_ring, self.busy_label, self.busy_cancel):
            w.hide()
        # The warnings the right column shows, here while it is hidden: a failed
        # open from the start page reported into a hidden label, which is the
        # silent drop ruled out on 2026-10-05. Reserved room, like the rows
        # above; elided, never widening the page.
        self.warning_label = _ElidingLabel("welcomeWarning")
        self.warning_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.warning_label.setFixedHeight(self.warning_label.fontMetrics().lineSpacing() * 2 + 4)
        self.warning_label.hide()

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
        self._recent_area = _RecentArea()
        box = QVBoxLayout(self._recent_area)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)
        box.setAlignment(Qt.AlignmentFlag.AlignTop)
        box.addWidget(self.recent_title)
        self._cards = QHBoxLayout()
        self._cards.setSpacing(16)
        self._cards.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        box.addLayout(self._cards)
        probe = self._make_card("probe", "", parent=None)   # measured, never shown
        # Constant in BOTH directions: the page is centred, so a list that
        # grows or empties must not change its height — nor its width, which
        # moved the buttons a pixel sideways. A hint, not a fixed size (see
        # _RecentArea); the height IS fixed.
        h = self.recent_title.sizeHint().height() + 12 + probe.sizeHint().height() + 4
        self._recent_area.hint = QSize(
            RECENT_SHOWN * probe.sizeHint().width() + (RECENT_SHOWN - 1) * 16, h)
        self._recent_area.setFixedHeight(h)
        probe.deleteLater()
        self.recent_buttons: list[QToolButton] = []

        root.addWidget(title)
        root.addWidget(tagline)
        root.addSpacing(8)
        root.addWidget(hint)
        root.addSpacing(20)
        root.addLayout(buttons)
        root.addSpacing(12)
        root.addWidget(self.busy_row)
        root.addWidget(self.warning_label)
        self._warning_room = QWidget()      # holds the room while no warning shows
        self._warning_room.setFixedHeight(self.warning_label.height())
        root.addWidget(self._warning_room)
        root.addSpacing(4)
        root.addWidget(self.update_note)
        root.addSpacing(12)
        root.addWidget(self._recent_area, 0, Qt.AlignmentFlag.AlignHCenter)
        self.refresh_recent()

    def show_busy(self, text: str) -> None:
        self.busy_label.setText(text)
        for w in (self.busy_ring, self.busy_label, self.busy_cancel):
            w.show()

    def set_busy_text(self, text: str) -> None:
        self.busy_label.setText(text)

    def hide_busy(self) -> None:
        for w in (self.busy_ring, self.busy_label, self.busy_cancel):
            w.hide()
        self.busy_label.setText("")
        self.busy_ring.set_indeterminate()

    def show_warning(self, text: str) -> None:
        self.warning_label.setText(text)
        self._warning_room.hide()
        self.warning_label.show()

    def clear_warning(self) -> None:
        self.warning_label.setText("")
        self.warning_label.hide()
        self._warning_room.show()

    def set_update_note(self, html: str) -> None:
        self.update_note.setText(html)

    def refresh_recent(self) -> None:
        """Re-read the list: projects saved or opened since the page was last
        shown appear, and files that have gone (moved, deleted, a disconnected
        drive) are left out rather than offered and then refused."""
        for b in self.recent_buttons:
            self._cards.removeWidget(b)
            b.hide()            # now: deleteLater lands a pass later, drawn till then
            b.deleteLater()
        self.recent_buttons = []
        paths = [p for p in self._recent() if os.path.isfile(p)][:RECENT_SHOWN]
        for path in paths:
            name = os.path.splitext(os.path.basename(path))[0]
            b = self._make_card(name, path)
            b.setEnabled(not self._locked())
            b.clicked.connect(lambda _=False, p=path: self._on_recent and self._on_recent(p))
            self._cards.addWidget(b)
            b.show()            # a child made after its parent was shown starts hidden
            self.recent_buttons.append(b)
        self.recent_title.setVisible(bool(paths))
        # Now, not on the next pass: a card added while the page is being
        # shown otherwise sits at Qt's default 640x480 for a frame.
        self._recent_area.layout().activate()

    def _make_card(self, name: str, path: str, parent=0) -> QToolButton:
        b = QToolButton(self._recent_area if parent == 0 else parent)
        b.setObjectName("welcomeRecent")
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        b.setIconSize(QSize(CARD_W, CARD_H))
        b.setIcon(QIcon(_card_pixmap(read_preview(path) if path else None,
                                     self.devicePixelRatioF() or 1.0)))
        # The name is elided, not wrapped: a long one must not make one card
        # taller than its neighbours.
        b.setText(b.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, CARD_W))
        b.setToolTip(path)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setAutoRaise(True)
        return b

    def showEvent(self, event) -> None:
        self.refresh_recent()
        super().showEvent(event)
