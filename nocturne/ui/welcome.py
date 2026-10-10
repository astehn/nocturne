from __future__ import annotations

import math
import os
import time
from datetime import date
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from .. import APP_NAME, APP_TAGLINE
from ..core.fits_io import format_integration, resolve_integration
from ..history.project_store import read_card
from . import theme
from .progress_ring import ProgressRing
from .side_panel import _ElidingLabel

# Six recent projects, three across in two rows (Andreas approved the mock-up
# 2026-10-10); one row of three when the window is too short for two. The menu
# keeps eight; the start page is a quick way back to recent work, not an archive.
RECENT_SHOWN = 6
COLUMNS = 3
CARD_W, CARD_H = 312, 190          # the picture box, filled: a crop, never a letterbox
SAMPLE_URL = "https://nocturneastro.com/sample-data.html"
_CARD_BG = QColor("#141519")       # under the crescent of a project with no thumbnail
_CARD_BODY = QColor(theme.BG_0)
_CARD_EDGE = QColor("#2a2c31")
_RADIUS = 10.0
_PAD = 8                           # room round each card for the hover lift and shadow
_LIFT = 3
_TITLE_GAP = 22
_BUSY_GAP = 2
_CANCEL_TEXTS = ("Cancel", "Finishing…")     # what MainWindow._sync_cancel shows
_GAP = 24                          # between the cards themselves, as in the mock-up
_META_TOP, _META_GAP, _META_BOTTOM = 9, 3, 10
# Locked while the window works: the card dims, keeping its colours. A disabled
# QToolButton drew its icon greyed out, so every thumbnail went grey during an
# open (his "nasty grey", 2026-10-10). 0.55 is the mock-up's value.
LOCKED_OPACITY = 0.55
_ICON = Path(__file__).resolve().parent.parent / "assets" / "nocturne_icon.svg"


def when_text(mtime: float, now: float | None = None) -> str:
    """When the project was last saved, in calendar days: a file saved at
    23:50 was "yesterday" ten minutes later, as people say it."""
    saved = date.fromtimestamp(mtime)
    today = date.fromtimestamp(time.time() if now is None else now)
    days = (today - saved).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    short = f"{saved.day} {saved.strftime('%b')}"
    return short if saved.year == today.year else f"{short} {saved.year}"


def _card_integration(total_s: float) -> str:
    """Whole minutes on a card: "54m", "3h 25m". Seconds are noise at a glance
    (the approved mockup read "54 m"); the info strip keeps format_integration."""
    s = int(round(total_s))
    if s < 60:
        return f"{s}s"
    minutes = int(round(s / 60))
    if minutes < 60:
        return f"{minutes}m"
    return format_integration(minutes * 60)


def card_info(meta: dict, mtime: float | None, now: float | None = None) -> str:
    """"NGC 7000 · 54m · today", read the way the info strip reads it.
    A part that is not known is left out, never shown as an empty slot."""
    parts: list[str] = []
    target = str(meta.get("target") or meta.get("target_solved") or "").strip()
    if target:
        parts.append(target)
    integ = resolve_integration(meta)
    # A header's EXPTIME of "NaN" reaches here as nan, and int(round(nan))
    # raised out of the start page and stopped the app launching (review I-1).
    total = integ.total_s if integ is not None else None
    if isinstance(total, (int, float)) and math.isfinite(total) and total > 0:
        parts.append(_card_integration(total))
    if mtime is not None:
        parts.append(when_text(mtime, now))
    return " · ".join(parts)


def _card_pixmap(jpeg: bytes | None, dpr: float) -> QPixmap:
    """The picture cropped to fill the card box, centred, so six cards make a
    clean grid whatever each frame's shape. With no preview (a project saved
    before thumbnails existed), the crescent."""
    w, h = int(CARD_W * dpr), int(CARD_H * dpr)
    out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(_CARD_BG)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    img = QImage.fromData(jpeg) if jpeg else QImage()
    if not img.isNull():
        scaled = img.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
        p.drawImage((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
    else:
        # The crescent alone, as in the mock-up: the whole icon brought its
        # dark rounded square with it (review M-6).
        svg = QSvgRenderer(str(_ICON))
        bounds = svg.boundsOnElement("crescent")
        side = h * 0.28
        scale = side / max(bounds.width(), bounds.height())
        cw, ch = bounds.width() * scale, bounds.height() * scale
        svg.render(p, "crescent", QRectF((w - cw) / 2, (h - ch) / 2, cw, ch))
    p.end()
    pm = QPixmap.fromImage(out)
    pm.setDevicePixelRatio(dpr)
    return pm


def _font(base: QFont, px: int, weight=QFont.Weight.Normal) -> QFont:
    f = QFont(base)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def _line_h(font: QFont) -> float:
    return QFontMetricsF(font).height()


class _Card(QAbstractButton):
    """One recent project, painted: a stylesheet cannot lift a card or draw
    its shadow, and a disabled QToolButton greys its icon."""

    def __init__(self, name: str, path: str, info: str, picture: QPixmap, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("welcomeRecent")
        self.setText(name)
        self.setToolTip(path)
        self.path, self.info, self.picture = path, info, picture
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._name_font = _font(self.font(), 14, QFont.Weight.DemiBold)
        self._info_font = _font(self.font(), 12)
        self.setFixedSize(self.card_size(self.font()))
        self._hover = False
        self._opening = False
        self.ring = ProgressRing(self, size="medium")
        self.ring.move(int(_PAD + (CARD_W - self.ring.width()) / 2),
                       int(_PAD + (CARD_H - self.ring.height()) / 2))
        self.ring.hide()

    @staticmethod
    def card_size(font: QFont) -> QSize:
        name = _line_h(_font(font, 14, QFont.Weight.DemiBold))
        info = _line_h(_font(font, 12))
        meta = _META_TOP + name + _META_GAP + info + _META_BOTTOM
        return QSize(CARD_W + 2 * _PAD, int(CARD_H + meta) + 2 * _PAD)

    def is_opening(self) -> bool:
        return self._opening

    def set_opening(self, on: bool) -> None:
        self._opening = on
        self.ring.setVisible(on)
        self.update()

    def is_lifted(self) -> bool:
        return self._hover and self.isEnabled() and not self._opening

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        lifted = self.is_lifted()
        if not self.isEnabled() and not self._opening:
            p.setOpacity(LOCKED_OPACITY)
        body = QRectF(_PAD, _PAD, CARD_W, self.height() - 2 * _PAD)
        if lifted:
            body.translate(0, -_LIFT)
            # A soft shadow: a few widening rounds of faint black, drawn only
            # on hover — nothing runs while the page sits idle.
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(1, _PAD + 1):
                p.setBrush(QColor(0, 0, 0, 34 - 4 * i if i < 8 else 4))
                p.drawRoundedRect(body.adjusted(-i, -i + 4, i, i + 4), _RADIUS + i, _RADIUS + i)
        shape = QPainterPath()
        shape.addRoundedRect(body, _RADIUS, _RADIUS)
        p.fillPath(shape, _CARD_BODY)
        p.save()
        p.setClipPath(shape)
        p.drawPixmap(QRectF(body.left(), body.top(), CARD_W, CARD_H), self.picture,
                     QRectF(self.picture.rect()))
        p.restore()
        if self._opening:
            centre = QPointF(body.left() + CARD_W / 2, body.top() + CARD_H / 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 140))
            p.drawEllipse(centre, 27, 27)
        x, w = body.left() + 12, CARD_W - 24
        name_h = _line_h(self._name_font)
        y = body.top() + CARD_H + _META_TOP
        p.setFont(self._name_font)
        p.setPen(QColor("#ffffff") if lifted else QColor(theme.TEXT))
        fm = p.fontMetrics()
        p.drawText(QRectF(x, y, w, name_h), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(self.text(), Qt.TextElideMode.ElideRight, int(w)))
        y += name_h + _META_GAP
        p.setFont(self._info_font)
        p.setPen(QColor(theme.TEXT_DIM))
        fm = p.fontMetrics()
        p.drawText(QRectF(x, y, w, _line_h(self._info_font)),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(self.info, Qt.TextElideMode.ElideRight, int(w)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self._opening or lifted:
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.drawRoundedRect(body.adjusted(1, 1, -1, -1), _RADIUS - 1, _RADIUS - 1)
        else:
            p.setPen(QPen(_CARD_EDGE, 1))
            p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), _RADIUS, _RADIUS)
        p.end()


class _Reserved(QWidget):
    """Asks for the full block's width but demands none of it, and holds the
    height of the tallest thing it may show. A fixed width became the minimum
    of the stack the start page shares with the image view (test_window_geometry
    caught it); a fixed height in the two-row mode would stop the window being
    made short enough to switch back to one row."""

    def __init__(self) -> None:
        super().__init__()
        self.hint = QSize(0, 0)
        self.floor = 0
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.hint

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self.floor)


class _DropZone(QFrame):
    """An invitation, not a target: it accepts no drops itself, so a file let
    go over it travels up to the window's own drop handling, like anywhere else."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("welcomeDrop")
        self.setAcceptDrops(False)
        self.setFixedSize(330, 190)
        main = QLabel("↓ Drop a FITS or TIFF here")
        main.setObjectName("welcomeDropMain")
        sub = QLabel("or use the buttons below")
        sub.setObjectName("welcomeDropSub")
        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        lay.addStretch(1)
        for lab in (main, sub):
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(lab)
        lay.addStretch(1)


class WelcomeScreen(QWidget):
    """The start page: every way in — a stack, an image, a saved project, a
    Ha/OIII stack — and the projects you were last working on (Andreas,
    2026-10-05: it offered two ways in where there are four). With no projects
    yet, how to begin."""

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
        self._opening_path: str | None = None
        self._rows = 2
        self._now = None            # tests pin the clock; None is the real one

        # One title line: the name, and the tagline sharing its baseline.
        self.title = QLabel(APP_NAME)
        self.title.setObjectName("welcomeTitle")
        self.tagline = QLabel(APP_TAGLINE)
        self.tagline.setObjectName("welcomeTag")
        title_row = QHBoxLayout()
        title_row.setSpacing(14)
        title_row.addStretch(1)
        title_row.addWidget(self.title, 0, Qt.AlignmentFlag.AlignBottom)
        title_row.addWidget(self.tagline, 0, Qt.AlignmentFlag.AlignBottom)
        title_row.addStretch(1)

        self.recent_title = QLabel("RECENT PROJECTS")
        self.recent_title.setObjectName("welcomeRecentTitle")
        self.recent_title.setContentsMargins(_PAD, 0, 0, 0)    # flush with the card edges

        self._grid_box = QWidget()
        self._grid = QGridLayout(self._grid_box)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(_GAP - 2 * _PAD)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.recent_buttons: list[_Card] = []

        self.empty_panel = self._build_empty_panel()

        self._head = _Reserved()
        head = QVBoxLayout(self._head)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(0)
        # The block is reserved at its tallest; what it lacks goes ABOVE the
        # title, so the title always sits just over the cards or the panel.
        head.addStretch(1)
        head.addLayout(title_row)
        head.addSpacing(_TITLE_GAP)
        head.addWidget(self.recent_title)
        head.addSpacing(12 - _PAD)
        head.addWidget(self._grid_box)
        head.addWidget(self.empty_panel, 0, Qt.AlignmentFlag.AlignHCenter)

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
        buttons.setSpacing(10)
        buttons.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for b in (self.open_btn, self.open_project_btn, self.haoiii_btn, self.stack_btn):
            buttons.addWidget(b)

        # Hidden with no projects, where the drop box says it; its room stays.
        self.drop_hint = QLabel("…or drop a FITS or TIFF anywhere on this window")
        self.drop_hint.setObjectName("welcomeHint")
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        keep = self.drop_hint.sizePolicy()
        keep.setRetainSizeWhenHidden(True)
        self.drop_hint.setSizePolicy(keep)

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
        self.busy_cancel.setObjectName("welcomeCancel")     # a link, as in mock-up B
        self.busy_cancel.clicked.connect(lambda: on_cancel and on_cancel())
        # Cancel on a line of its own (Andreas, 2026-10-10): beside the label,
        # the ticking dots changed the label's width and walked the button
        # sideways. The label is held at its widest too, so the ring and the
        # text stay still as well.
        self._busy_line = QHBoxLayout()
        self._busy_line.setSpacing(8)
        self._busy_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._busy_line.addWidget(self.busy_ring, 0, Qt.AlignmentFlag.AlignVCenter)
        self._busy_line.addWidget(self.busy_label, 0, Qt.AlignmentFlag.AlignVCenter)
        busy = QVBoxLayout(self.busy_row)
        busy.setContentsMargins(0, 0, 0, 0)
        busy.setSpacing(_BUSY_GAP)
        busy.addLayout(self._busy_line)
        busy.addWidget(self.busy_cancel, 0, Qt.AlignmentFlag.AlignHCenter)
        self._size_busy_row()
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

        root = QVBoxLayout(self)
        # Spacing is tight on purpose: two rows of cards and every reserved
        # row fit a 1440 x 900 window (788 px of page offscreen; measure it
        # again after changing any height here).
        root.setContentsMargins(16, 0, 16, 0)
        root.setSpacing(0)
        root.addStretch(1)
        root.addWidget(self._head, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addSpacing(24 - _PAD)          # 24 from the card edge, past its shadow room
        root.addLayout(buttons)
        root.addSpacing(10)
        root.addWidget(self.drop_hint)
        root.addSpacing(4)                  # 4, not 6: pays for Cancel's own line
        root.addWidget(self.busy_row)
        root.addWidget(self.warning_label)
        self._warning_room = QWidget()      # holds the room while no warning shows
        self._warning_room.setFixedHeight(self.warning_label.height())
        root.addWidget(self._warning_room)
        root.addWidget(self.update_note)
        root.addStretch(1)
        self.refresh_recent()

    # --- the empty state ---------------------------------------------------
    def _build_empty_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("welcomeEmpty")
        heading = QLabel("Your first picture")
        heading.setObjectName("welcomeEmptyTitle")
        steps = QLabel(
            "<ol style='margin-left:-20px'>"
            "<li style='line-height:150%%'><b style='color:%(t)s'>Stack…</b> a night of Seestar frames — "
            "point it at the folder of subs.</li>"
            "<li style='line-height:150%%'>Or <b style='color:%(t)s'>Open Image</b> if you already have a "
            "stacked FITS or TIFF.</li>"
            "<li style='line-height:150%%'>Follow the steps on the left, top to bottom. Each one explains itself.</li>"
            "</ol>" % {"t": theme.TEXT})
        steps.setObjectName("welcomeSteps")
        self.sample_link = QLabel(
            f"No data of your own yet? <a href='{SAMPLE_URL}' style='color:{theme.ACCENT};"
            f"text-decoration:none'>Download a sample stack ↗</a>")
        self.sample_link.setObjectName("welcomeSample")
        self.sample_link.setOpenExternalLinks(True)
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addStretch(1)
        left.addWidget(heading)
        left.addWidget(steps)
        left.addSpacing(6)
        left.addWidget(self.sample_link)
        left.addStretch(1)
        self.drop_zone = _DropZone()
        lay = QHBoxLayout(panel)
        lay.setContentsMargins(40, 38, 40, 38)
        lay.setSpacing(40)
        lay.addLayout(left, 1)
        lay.addWidget(self.drop_zone, 0, Qt.AlignmentFlag.AlignVCenter)
        panel.setFixedWidth(COLUMNS * CARD_W + (COLUMNS - 1) * _GAP)
        return panel

    # --- status rows -------------------------------------------------------
    def _size_busy_row(self) -> None:
        """Fixed sizes for the busy row: its room is reserved, and nothing in
        it may change width while it shows."""
        self.busy_label.ensurePolished()
        self.busy_cancel.ensurePolished()
        text = self.busy_cancel.text()
        widths = []
        for t in _CANCEL_TEXTS:
            self.busy_cancel.setText(t)
            widths.append(self.busy_cancel.sizeHint().width())
        self.busy_cancel.setText(text)
        self.busy_cancel.setFixedWidth(max(widths))
        line = max(self.busy_ring.height(), self.busy_label.fontMetrics().height())
        self.busy_label.setFixedHeight(line)
        self.busy_row.setFixedHeight(line + _BUSY_GAP + self.busy_cancel.sizeHint().height())

    def _fit_busy_label(self, text: str, grow_only: bool) -> None:
        """As wide as the text plus the three dots the window ticks onto it."""
        need = self.busy_label.fontMetrics().horizontalAdvance(text + "...") + 2
        if grow_only:
            need = max(need, self.busy_label.width())
        if need != self.busy_label.width():
            self.busy_label.setFixedWidth(need)

    def show_busy(self, text: str) -> None:
        self.busy_label.ensurePolished()
        self._fit_busy_label(text, grow_only=False)
        self.busy_label.setText(text)
        for w in (self.busy_ring, self.busy_label, self.busy_cancel):
            w.show()

    def set_busy_text(self, text: str) -> None:
        # Never narrower mid-run: the dots come and go on the same base text.
        self._fit_busy_label(text.rstrip("."), grow_only=True)
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

    # --- the cards ---------------------------------------------------------
    def visible_cards(self) -> list[_Card]:
        return self.recent_buttons[:self._rows * COLUMNS]

    def rows(self) -> int:
        return self._rows

    def refresh_recent(self) -> None:
        """Re-read the list: projects saved or opened since the page was last
        shown appear, and files that have gone (moved, deleted, a disconnected
        drive) are left out rather than offered and then refused."""
        for b in self.recent_buttons:
            self._grid.removeWidget(b)
            b.hide()            # now: deleteLater lands a pass later, drawn till then
            b.deleteLater()
        self.recent_buttons = []
        # An open in flight keeps its card marked through a rebuild; once the
        # window is idle again, the open has finished or failed.
        if not self._locked():
            self._opening_path = None
        paths = [p for p in self._recent() if os.path.isfile(p)][:RECENT_SHOWN]
        dpr = self.devicePixelRatioF() or 1.0
        for path in paths:
            name = os.path.splitext(os.path.basename(path))[0]
            # One odd bundle must never take the page, or the app's launch,
            # down with it (review I-1): the card falls back to its name.
            try:
                jpeg, meta = read_card(path)
                info = card_info(meta, os.path.getmtime(path), self._now)
            except Exception:
                jpeg, info = None, ""
            try:
                picture = _card_pixmap(jpeg, dpr)
            except Exception:
                picture = _card_pixmap(None, dpr)
            b = _Card(name, path, info, picture, self._grid_box)
            b.setEnabled(not self._locked())
            b.set_opening(path == self._opening_path)
            b.clicked.connect(lambda _=False, c=b: self._card_clicked(c))
            self.recent_buttons.append(b)
        self._place_cards()

    def _card_clicked(self, card: _Card) -> None:
        self._opening_path = card.path
        card.set_opening(True)
        try:
            if self._on_recent:
                self._on_recent(card.path)
        finally:
            # Nothing started (a question answered No, an open refused or
            # raising at once): nothing is opening, so nothing stays marked.
            if not self._locked() and self._opening_path == card.path:
                self._clear_opening()

    def _clear_opening(self) -> None:
        self._opening_path = None
        for b in self.recent_buttons:
            b.set_opening(False)

    def _place_cards(self) -> None:
        shown = self.visible_cards()
        for i, b in enumerate(self.recent_buttons):
            self._grid.removeWidget(b)
            if b in shown:
                self._grid.addWidget(b, i // COLUMNS, i % COLUMNS)
                b.show()        # a child made after its parent was shown starts hidden
            else:
                b.hide()
        has = bool(self.recent_buttons)
        self.recent_title.setText("RECENT PROJECTS" if has else "GET STARTED")
        self._grid_box.setVisible(has)
        self.empty_panel.setVisible(not has)
        self.drop_hint.setVisible(has)
        self._reserve()
        # Now, not on the next pass: a card added while the page is being
        # shown otherwise sits at Qt's default 640x480 for a frame, and a
        # change of rows would leave the buttons where they were for one.
        self.layout().activate()
        self._head.layout().activate()

    # --- sizes -------------------------------------------------------------
    def _card_size(self) -> QSize:
        return _Card.card_size(self.font())

    def _grid_height(self, rows: int) -> int:
        return rows * self._card_size().height() + (rows - 1) * self._grid.spacing()

    def _head_height(self, rows: int, empty: bool = False) -> int:
        """The block's height in a mode, whatever the list holds: the page is
        centred, so a list that grew or shrank would move the buttons. Not
        with no projects: that list cannot fill while the page is on screen
        (saving one needs an image open), so the first page every new user
        sees is centred on its own height, not held low (review I-3)."""
        self.ensurePolished()
        for w in (self.title, self.tagline, self.recent_title):
            w.ensurePolished()
        title = max(self.title.sizeHint().height(), self.tagline.sizeHint().height())
        panel = self.empty_panel.sizeHint().height()
        content = panel if empty else max(self._grid_height(rows), panel)
        return title + _TITLE_GAP + self.recent_title.sizeHint().height() + (12 - _PAD) + content

    def _reserve(self) -> None:
        self._align_tagline()
        card = self._card_size()
        width = COLUMNS * card.width() + (COLUMNS - 1) * self._grid.spacing()
        empty = not self.recent_buttons
        self._head.hint = QSize(width, self._head_height(self._rows, empty))
        self._head.floor = self._head_height(1, empty)
        self._size_busy_row()
        self._head.updateGeometry()
        self.layout().invalidate()

    def _align_tagline(self) -> None:
        """The tagline sits on the title's baseline, as in the mock-up."""
        drop = self.title.fontMetrics().descent() - self.tagline.fontMetrics().descent()
        self.tagline.setContentsMargins(0, 0, 0, max(0, drop))

    def page_height(self, rows: int) -> int:
        """What the whole page needs with `rows` rows of cards."""
        root = self.layout()
        rest = root.sizeHint().height() - self._head.sizeHint().height()
        return rest + self._head_height(rows)

    def _fit_rows(self) -> None:
        """Two rows when the page has the height for them, else one: the floor
        is a 1280 x 800 screen (the MacBook Air work, 2026-09)."""
        rows = 2 if self.height() >= self.page_height(2) else 1
        if rows != self._rows:
            self._rows = rows
            self._place_cards()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_rows()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() in (event.Type.StyleChange, event.Type.FontChange) and hasattr(self, "_head"):
            self._reserve()

    def hideEvent(self, event) -> None:  # noqa: N802
        # A successful open hides the page before the window goes idle, so the
        # idle rebuild that would clear the mark never runs (review M-2).
        if not event.spontaneous():         # not a minimise mid-open
            self._clear_opening()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        self.refresh_recent()
        super().showEvent(event)
        self._fit_rows()
