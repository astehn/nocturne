"""Qt adapter: walks a primitive list from `core.annotation_layout` and builds
a QGraphicsItemGroup, in image-pixel (scene) coordinates. All the WHAT/WHERE/
colour decisions already happened in `build_layout_for` -- this file only
knows how to turn a Circle/Marker/Label/Leader/GridLine into Qt items.

Every item except a grid line's own path keeps ItemIgnoresTransformations so
it stays a constant, readable size under zoom/pan. A grid line's polyline is
the one exception: it traces the WCS-projected curvature of a constant-RA/Dec
line across the whole frame, so it has to scale and pan with the image the
same way the pixmap underneath it does; its label, though, still gets the
constant-size treatment so it stays readable."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainterPath, QPen
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsItemGroup,
                               QGraphicsLineItem, QGraphicsPathItem, QGraphicsSimpleTextItem)

from ..core.annotation_layout import Circle, GridLine, Label, Leader, Marker

_IGNORE = QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
_SIZE_PT = {"primary": 16.0, "secondary": 14.0, "star": 12.0, "star_bright": 14.0, "grid": 11.0}
_DEFAULT_PT = _SIZE_PT["secondary"]


def _text(s, fill, size=_DEFAULT_PT, bold=False, outline="#0a0f18"):
    """A constant-size text item with a THIN dark outline so the bright fill
    stays legible over both stars and dark sky (a heavy outline reads as black)."""
    t = QGraphicsSimpleTextItem(s)
    f = QFont()
    f.setPointSizeF(size)
    f.setBold(bold)
    t.setFont(f)
    t.setBrush(QColor(fill))                        # the fill is the colour you read
    pen = QPen(QColor(outline))
    pen.setWidthF(1.1)                              # subtle halo, does not swamp the fill
    pen.setCosmetic(True)
    t.setPen(pen)
    t.setFlag(_IGNORE, True)
    return t


def _circle_item(p: Circle) -> QGraphicsEllipseItem:
    r = p.r
    item = QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
    item.setPos(p.x, p.y)
    pen = QPen(QColor(p.colour), 1.6)
    if p.dashed:                                    # 'we don't know how big this is'
        pen.setStyle(Qt.PenStyle.DashLine)
    pen.setCosmetic(True)
    item.setPen(pen)
    item.setBrush(Qt.BrushStyle.NoBrush)
    item.setFlag(_IGNORE, True)
    return item


def _star_ticks(p: Marker) -> list:
    """Four short ticks flanking the star, offset outward with a gap so none
    of them passes through the star's own position -- never a cross."""
    pt = _SIZE_PT.get(p.size, _SIZE_PT["star"])
    gap, arm = pt * 0.35, pt * 0.55
    spans = [((gap, 0.0), (gap + arm, 0.0)), ((-gap, 0.0), (-gap - arm, 0.0)),
             ((0.0, -gap), (0.0, -gap - arm)), ((0.0, gap), (0.0, gap + arm))]
    ticks = []
    for (x1, y1), (x2, y2) in spans:
        tick = QGraphicsLineItem(x1, y1, x2, y2)
        tick.setPos(p.x, p.y)
        pen = QPen(QColor(p.colour), 1.5)
        pen.setCosmetic(True)
        tick.setPen(pen)
        tick.setFlag(_IGNORE, True)
        ticks.append(tick)
    return ticks


def _compass_dot(p: Marker) -> QGraphicsEllipseItem:
    item = QGraphicsEllipseItem(-3, -3, 6, 6)
    item.setPos(p.x, p.y)
    item.setPen(QPen(QColor(p.colour), 1))
    item.setBrush(QColor(p.colour))
    item.setFlag(_IGNORE, True)
    return item


def _leader_item(p: Leader) -> QGraphicsLineItem:
    # Anchor at the FIRST point (setPos) and draw the local line relative to
    # it, rather than embedding both absolute endpoints as local geometry --
    # that keeps the anchor end correctly tracking pan/zoom instead of
    # drifting from the item's implicit (0, 0) scene position.
    item = QGraphicsLineItem(0.0, 0.0, p.x2 - p.x1, p.y2 - p.y1)
    item.setPos(p.x1, p.y1)
    pen = QPen(QColor(p.colour), 1.2)
    pen.setCosmetic(True)
    item.setPen(pen)
    item.setFlag(_IGNORE, True)
    return item


def _grid_line_items(p: GridLine) -> list:
    items = []
    path = QPainterPath()
    x0, y0 = p.points[0]
    path.moveTo(x0, y0)
    for x, y in p.points[1:]:
        path.lineTo(x, y)
    line_item = QGraphicsPathItem(path)
    pen = QPen(QColor(p.colour), 1.0)
    pen.setCosmetic(True)
    line_item.setPen(pen)
    items.append(line_item)
    if p.label:
        label = _text(p.label, p.colour, size=_SIZE_PT["grid"])
        label.setPos(x0 + 3.0, y0 - 12.0)
        items.append(label)
    return items


def build_annotation_group(primitives, shape) -> QGraphicsItemGroup:
    """The Qt adapter: turns a flat primitive list (from
    `core.annotation_layout.build_layout_for`) into a QGraphicsItemGroup ready
    to drop onto the canvas. `shape` is accepted for parity with the export
    adapter and future use; primitive coordinates are already absolute."""
    g = QGraphicsItemGroup()
    for p in primitives:
        if isinstance(p, Circle):
            g.addToGroup(_circle_item(p))
        elif isinstance(p, Marker):
            if p.kind == "star":
                for tick in _star_ticks(p):
                    g.addToGroup(tick)
            else:                                    # "compass" (and any future non-star kind)
                g.addToGroup(_compass_dot(p))
        elif isinstance(p, Label):
            label = _text(p.text, p.colour, size=_SIZE_PT.get(p.size, _DEFAULT_PT))
            label.setPos(p.x, p.y)
            g.addToGroup(label)
        elif isinstance(p, Leader):
            g.addToGroup(_leader_item(p))
        elif isinstance(p, GridLine):
            for item in _grid_line_items(p):
                g.addToGroup(item)
    return g
