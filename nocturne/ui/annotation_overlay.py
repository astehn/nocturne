"""Builds the annotation overlay (DSO labels + compass + scale bar) as a
QGraphicsItemGroup in image-pixel (scene) coordinates. Child items ignore the
view transform so they stay a constant, readable size under zoom/pan."""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsItemGroup,
                               QGraphicsLineItem, QGraphicsSimpleTextItem)

_IGNORE = QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
_LABEL_PT = 13.0        # DSO label size (constant on-screen px)
_COMPASS_PT = 16.0      # the "N"


def _text(s, fill, size=_LABEL_PT, bold=False, outline="#0a0f18"):
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


def build_annotation_group(objects, north_angle, scale_len_px, scale_label,
                           shape, theme="dark") -> QGraphicsItemGroup:
    label_color = "#5fe3d0"                         # readable teal (blue/green)
    accent = "#6aa8f2"                              # bright blue for the compass
    scale_color = "#e7ecf4" if theme == "dark" else "#111722"
    g = QGraphicsItemGroup()
    h, w = shape

    for o in objects:
        if getattr(o, "centered", True):                # ring only when the centre is in-frame
            marker = QGraphicsEllipseItem(-5, -5, 10, 10)   # small ring on the object
            marker.setPos(o.x, o.y)
            marker.setPen(QPen(QColor(label_color), 2))
            marker.setBrush(Qt.BrushStyle.NoBrush)
            marker.setFlag(_IGNORE, True)
            g.addToGroup(marker)
        label = _text(f"{o.name}" + (f"  {o.common}" if o.common else ""), label_color)
        label.setPos(o.x + 9, o.y + 7)                  # anchored beside the object
        g.addToGroup(label)

    # compass: an arrow toward celestial North from a fixed top-right anchor.
    ax, ay = w - 120, 120
    rad = math.radians(north_angle)
    tx, ty = ax + 60 * math.cos(rad), ay + 60 * math.sin(rad)
    origin = QGraphicsEllipseItem(-3, -3, 6, 6)
    origin.setPos(ax, ay)
    origin.setPen(QPen(QColor(accent), 1))
    origin.setBrush(QColor(accent))
    origin.setFlag(_IGNORE, True)
    g.addToGroup(origin)
    n = QGraphicsLineItem(ax, ay, tx, ty)
    n.setPen(QPen(QColor(accent), 3))
    n.setFlag(_IGNORE, True)
    g.addToGroup(n)
    nlab = _text("N", accent, size=_COMPASS_PT, bold=True)
    nlab.setPos(ax + 70 * math.cos(rad) - 6, ay + 70 * math.sin(rad) - 10)
    g.addToGroup(nlab)

    # scale bar near the bottom-left, with end ticks.
    bx, by = 90, h - 90
    bar = QGraphicsLineItem(bx, by, bx + scale_len_px, by)
    bar.setPen(QPen(QColor(scale_color), 3))
    bar.setFlag(_IGNORE, True)
    g.addToGroup(bar)
    slab = _text(scale_label, scale_color)
    slab.setPos(bx, by - 26)
    g.addToGroup(slab)
    return g
