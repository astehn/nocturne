"""Shape buttons: the one way Crop, Trim, Share and Upscale Crop pick a frame.

Four places chose an aspect ratio two different ways — a dropdown in Crop and
Trim, a row of text buttons in Share and Upscale — with two different lists. A
beginner does not know 4:5 from 5:4, so each button DRAWS its shape, and the
list is landscape only with an Orientation switch beside it: one set of
proportions, turned on demand, instead of eleven names to read (Andreas chose
this layout, "variant B", on 2026-10-10).

The outlines are painted rather than SVGs so that turning Portrait can redraw
them, and so they stay crisp at any device-pixel ratio.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from ..core.crop import (
    FREE, LEGACY_FREE, PICTURE, RATIO_SHAPES, shape_name, shape_ratio, split_shape,
)
from . import theme

# Plain words on hover, keyed by the name the button shows. A ratio is a number
# to someone who has never cropped for a feed; what it is FOR is not.
TIPS = {
    FREE: "Drag any shape you like",
    PICTURE: "Keep the picture's own proportions",
    "1:1": "Square",
    "5:4": "Close to square, like a print",
    "4:5": "Portrait, as Instagram crops it",
    "4:3": "Close to square, like a print",
    "3:4": "Close to square, like an upright print",
    "3:2": "The classic camera frame",
    "2:3": "The classic camera frame, upright",
    "16:9": "Widescreen",
    "9:16": "Tall, for phone screens and Stories",
}

# Why Orientation is greyed, per shape — a disabled control that does not say
# why reads as broken.
_NO_TURN = {
    FREE: "Free has no fixed shape to turn",
    PICTURE: "Original keeps the picture's own orientation",
    "1:1": "A square is the same either way",
}

# Variant B's look (crop_mock.html), made lower: on a MacBook the Crop step's
# scrolling zone is ~208 px tall (review I1, 2026-10-10), and the mock-up's
# 62 px buttons put Rotate/Flip and Guides wholly below it.
_BTN_H = 42
_ICON_BOX = 18          # the outline's longer side, px
_ICON_TOP = 5
_ICON_AREA_H = 20
_BTN_BORDER = "#3a3d43"
_OUTLINE = "#c9ced6"
_ON_FILL = QColor(74, 144, 226, 46)    # ACCENT at .18
_DEFAULT_PICTURE = 26 / 16              # until the caller says what the picture is

TURN_TIP = ("Turn the shape to portrait: 3:2 becomes 2:3. "
            "Free, Original and 1:1 have no orientation.")


def section_label(text: str) -> QLabel:
    """SHAPE / ROTATE / FLIP / … — the small caps headings of the mock-up."""
    lbl = QLabel(text.upper())
    lbl.setObjectName("panelSectionLabel")
    return lbl


class ShapeButton(QAbstractButton):
    """One shape: its outline in proportion, the name under it."""

    def __init__(self, key: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key                   # FREE, PICTURE or a landscape ratio name
        self.ratio: float | None = None  # what the outline draws; None = Free's
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(_BTN_H)
        self.setMinimumWidth(44)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(56, _BTN_H)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(44, _BTN_H)

    def looks_on(self) -> bool:
        """Drawn as chosen. A shape stays lit while a busy gate greys it — it
        is still the shape in force."""
        return self.isChecked()

    def outline_size(self) -> tuple[float, float]:
        """(w, h) of the drawn outline: the longer side _ICON_BOX."""
        r = self.ratio if self.ratio else 26 / 17
        if r >= 1.0:
            return float(_ICON_BOX), _ICON_BOX / r
        return _ICON_BOX * r, float(_ICON_BOX)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on, enabled = self.looks_on(), self.isEnabled()
        if not enabled:
            p.setOpacity(theme.DISABLED_OPACITY)
        body = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.hasFocus() and enabled:
            border = QColor(theme.ACCENT_HI)       # keyboard focus, visible (review M4)
        elif on:
            border = QColor(theme.ACCENT)
        else:
            border = QColor(theme.TEXT_FAINT if self.underMouse() and enabled else _BTN_BORDER)
        p.setPen(QPen(border, 2 if self.hasFocus() and enabled else 1))
        p.setBrush(_ON_FILL if on else QColor(theme.BG_3))
        p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5) if self.hasFocus() else body, 6, 6)

        w, h = self.outline_size()
        cx = self.width() / 2
        cy = _ICON_TOP + _ICON_AREA_H / 2
        pen = QPen(QColor("#ffffff" if on else _OUTLINE), 1.5)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        if self.key == FREE:
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setDashPattern([2.0, 1.6])
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(cx - w / 2, cy - h / 2, w, h), 1.5, 1.5)
        self._paint_extra(p, cx, cy, w, h, on)

        f = QFont(self.font())
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(0, 0, self.width(), self.height() - 4),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, self.text())
        p.end()

    def _paint_extra(self, p, cx, cy, w, h, on) -> None:
        pass


class OrientationToggle(ShapeButton):
    """The grid's last cell: checked = Portrait. A tall outline with a turn
    arrow beside it, so it reads as "turn" and not as a ninth shape."""

    def __init__(self, parent=None) -> None:
        super().__init__("turn", parent)
        self.ratio = 2 / 3
        self.setText("Portrait")
        self.setToolTip(TURN_TIP)

    def looks_on(self) -> bool:
        """Greyed (Free, Original, 1:1) it draws OFF even while it remembers
        Portrait for the next ratio: a greyed control that looks on reads as
        if it still applied (review M3)."""
        return self.isChecked() and self.isEnabled()

    def _paint_extra(self, p, cx, cy, w, h, on) -> None:
        pen = QPen(QColor("#ffffff" if on else _OUTLINE), 1.3)
        p.setPen(pen)
        r = QRectF(cx + w / 2 + 2, cy - h / 2, 8, 8)
        p.drawArc(r, 0 * 16, 270 * 16)              # a quarter-short circle: turn
        tip = r.center().x() + 4, r.center().y()
        p.drawLine(QPointF(*tip), QPointF(tip[0] - 2, tip[1] - 2.5))
        p.drawLine(QPointF(*tip), QPointF(tip[0] + 2, tip[1] - 2.5))


class SegmentRow(QWidget):
    """Buttons side by side in the mock-up's segment style. `checkable` makes
    them one exclusive choice (Guides, Orientation); otherwise each is an
    action (Rotate / Flip)."""

    currentTextChanged = Signal(str)

    def __init__(self, labels, *, checkable: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._labels = list(labels)
        self._buttons: list[QPushButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for i, label in enumerate(self._labels):
            b = QPushButton(label)
            b.setObjectName("shapeSeg")
            b.setCheckable(checkable)
            if checkable:
                self._group.addButton(b, i)
            row.addWidget(b, 1)
            self._buttons.append(b)
        if checkable and self._buttons:
            self._buttons[0].setChecked(True)
        self._group.idToggled.connect(self._on_toggled)

    def buttons(self) -> list[QPushButton]:
        return list(self._buttons)

    def count(self) -> int:
        return len(self._labels)

    def itemText(self, i: int) -> str:  # noqa: N802
        return self._labels[i]

    def currentText(self) -> str:  # noqa: N802
        i = self._group.checkedId()
        return self._labels[i] if 0 <= i < len(self._labels) else ""

    def setCurrentText(self, text: str) -> None:  # noqa: N802
        if text in self._labels:
            self._buttons[self._labels.index(text)].setChecked(True)

    def _on_toggled(self, i: int, checked: bool) -> None:
        if checked:
            self.currentTextChanged.emit(self._labels[i])


class ShapePicker(QWidget):
    """Shape grid with the Portrait toggle in its last cell. `shape()` is the STORED name — "Free",
    "Picture", or the ratio as made ("2:3" for a portrait 3:2) — and
    `shapeChanged` carries it.

    `offer_free=False` is Share and Upscale Crop: they fit the picture to a
    shape, and their "Original" is the picture as it is.
    """

    shapeChanged = Signal(str)

    def __init__(self, *, offer_free: bool = True, title: str | None = "Shape",
                 make_label=section_label, parent=None) -> None:
        """`title` None leaves the heading to the caller; `make_label` builds
        it, so a dialog with its own label style keeps it."""
        super().__init__(parent)
        self._offer_free = offer_free
        self._picture = _DEFAULT_PICTURE
        keys = ([FREE] if offer_free else []) + [PICTURE] + [n for n, _ in RATIO_SHAPES]
        self._buttons: dict[str, ShapeButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        for i, key in enumerate(keys):
            b = ShapeButton(key, self)
            b.clicked.connect(lambda _c=False: self._changed())
            self._group.addButton(b)
            grid.addWidget(b, i // 4, i % 4)
            self._buttons[key] = b
        # Orientation is the next free cell, not a row of its own: one row of
        # buttons and a note cost ~60 px the MacBook's Crop card does not have.
        self.orientation = OrientationToggle(self)
        self.orientation.toggled.connect(lambda _on: self._turned())
        n = len(keys)
        grid.addWidget(self.orientation, n // 4, n % 4)
        for c in range(4):
            grid.setColumnStretch(c, 1)

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        if title:
            col.addWidget(make_label(title))
        col.addLayout(grid)

        self._buttons[keys[0]].setChecked(True)
        self._relabel()

    # --- reading -----------------------------------------------------------
    def buttons(self) -> list[ShapeButton]:
        """In grid order."""
        return list(self._buttons.values())

    def button(self, key: str) -> ShapeButton:
        return self._buttons[key]

    def labels(self) -> list[str]:
        return [b.text() for b in self.buttons()]

    def portrait(self) -> bool:
        """Remembered while greyed: Free then 3:2 comes back as 2:3."""
        return self.orientation.isChecked()

    def _base(self) -> str:
        b = self._group.checkedButton()
        return b.key if b is not None else PICTURE

    def shape(self) -> str:
        return shape_name(self._base(), self.portrait())

    def label(self) -> str:
        """What the selected button says — Share names its file with it."""
        return self._buttons[self._base()].text()

    def ratio(self, picture_ratio: float | None = None) -> float | None:
        """Width / height to lock to; None is Free. The picture's own ratio
        defaults to the one given to `set_picture_ratio`."""
        return shape_ratio(self.shape(), picture_ratio if picture_ratio is not None
                           else self._picture)

    # --- writing -----------------------------------------------------------
    def set_picture_ratio(self, ratio: float) -> None:
        """Draw Original's outline in the picture's own proportions."""
        if ratio and ratio > 0:
            self._picture = float(ratio)
            self._relabel()

    def set_shape(self, name: str) -> None:
        """Select a STORED name, without emitting. A legacy "Original" means
        Free where Free is offered (that is what it did), and the picture as it
        is where it is not."""
        if name == LEGACY_FREE:
            name = FREE if self._offer_free else PICTURE
        base, portrait = split_shape(name)
        if base not in self._buttons:
            base = next(iter(self._buttons))
        blocked = self.orientation.blockSignals(True)
        self.orientation.setChecked(portrait)
        self.orientation.blockSignals(blocked)
        self._buttons[base].setChecked(True)
        self._relabel()

    # --- internals ---------------------------------------------------------
    def _changed(self) -> None:
        self._relabel()
        self.shapeChanged.emit(self.shape())

    def _turned(self) -> None:
        self._relabel()
        if self._base() not in _NO_TURN:
            self.shapeChanged.emit(self.shape())

    def _relabel(self) -> None:
        portrait = self.portrait()
        for key, b in self._buttons.items():
            name = shape_name(key, portrait)
            b.setText("Original" if key == PICTURE else name)
            b.ratio = (None if key == FREE else
                       self._picture if key == PICTURE else shape_ratio(name))
            b.setToolTip(TIPS.get(name, ""))
            b.update()
        base = self._base()
        turnable = base not in _NO_TURN
        self.orientation.setEnabled(turnable)
        self.orientation.setToolTip(TURN_TIP if turnable
                                    else f"{_NO_TURN[base]}. {TURN_TIP}")
        self.orientation.update()
