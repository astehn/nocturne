"""Export's format tiles: Crop's shape-button idiom with an icon and a sub-label.

Andreas, 2026-10-14: dropdowns have been replaced by buttons almost everywhere
else in the app, so Export follows. A tile shows what the format is FOR in its
small second line ("16-bit", "data"), which a dropdown entry could only say by
growing a longer name.

`TileRow` reads and writes the VALUE (today's EXPORT_FORMATS strings), never
the short label, so `on_export` and everything downstream is unchanged.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QGridLayout, QWidget

from . import theme
from .icons import load_icon
from .shape_picker import _BTN_BORDER, _ON_FILL, _OUTLINE

# Icon 18 + label 13 + sub-label 12 + padding. Crop's tiles are 42 with one
# line; the second line costs 14.
_TILE_H = 56
_ICON = 18
_ICON_TOP = 6


class IconTile(QAbstractButton):
    """One choice: an icon, its name, and a small line under it."""

    def __init__(self, label: str, sub: str, icon: str, parent=None) -> None:
        super().__init__(parent)
        self.setText(label)
        self.sub = sub
        self.icon_name = icon
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(_TILE_H)
        self.setMinimumWidth(52)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(76, _TILE_H)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(52, _TILE_H)

    @staticmethod
    def sub_font(base: QFont) -> QFont:
        f = QFont(base)
        f.setPixelSize(10)
        return f

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on, enabled = self.isChecked(), self.isEnabled()
        if not enabled:
            p.setOpacity(theme.DISABLED_OPACITY)
        body = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        focus = self.hasFocus() and enabled
        if focus:
            border = QColor(theme.ACCENT_HI)
        elif on:
            border = QColor(theme.ACCENT)
        else:
            border = QColor(theme.TEXT_FAINT if self.underMouse() and enabled else _BTN_BORDER)
        p.setPen(QPen(border, 2 if focus else 1))
        p.setBrush(_ON_FILL if on else QColor(theme.BG_3))
        p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5) if focus else body, 6, 6)

        icon = load_icon(self.icon_name, "#ffffff" if on else _OUTLINE)
        x = int((self.width() - _ICON) / 2)
        icon.paint(p, x, _ICON_TOP, _ICON, _ICON)

        f = QFont(self.font())
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(0, _ICON_TOP + _ICON + 1, self.width(), 15),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, self.text())
        p.setFont(self.sub_font(self.font()))
        p.setPen(QColor(theme.TEXT_DIM))
        p.drawText(QRectF(2, _ICON_TOP + _ICON + 16, self.width() - 4, 13),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, self.sub)
        p.end()


class TileRow(QWidget):
    """One exclusive choice of tiles in a row, read like a combo box:
    `currentText()` is the chosen tile's VALUE."""

    currentTextChanged = Signal(str)

    def __init__(self, tiles, *, weights=None, parent=None) -> None:
        """`tiles`: (value, label, sub-label, icon name) per tile. `weights`
        shares the row's width out unevenly, for a tile whose second line is
        longer than the others'."""
        super().__init__(parent)
        self._values = [t[0] for t in tiles]
        self._buttons: list[IconTile] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        for i, (_value, label, sub, icon) in enumerate(tiles):
            b = IconTile(label, sub, icon, self)
            self._group.addButton(b, i)
            grid.addWidget(b, 0, i)
            grid.setColumnStretch(i, weights[i] if weights else 1)
            self._buttons.append(b)
        if self._buttons:
            self._buttons[0].setChecked(True)
        self._group.idToggled.connect(self._on_toggled)

    def buttons(self) -> list[IconTile]:
        return list(self._buttons)

    def count(self) -> int:
        return len(self._values)

    def itemText(self, i: int) -> str:  # noqa: N802
        return self._values[i]

    def currentText(self) -> str:  # noqa: N802
        i = self._group.checkedId()
        return self._values[i] if 0 <= i < len(self._values) else ""

    def setCurrentText(self, value: str) -> None:  # noqa: N802
        if value in self._values:
            self._buttons[self._values.index(value)].setChecked(True)

    def _on_toggled(self, i: int, checked: bool) -> None:
        if checked:
            self.currentTextChanged.emit(self._values[i])
