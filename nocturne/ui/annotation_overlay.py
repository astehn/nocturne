"""Builds the annotation overlay (DSO labels + compass + scale bar) as a
QGraphicsItemGroup in image-pixel (scene) coordinates. Child items ignore the
view transform so they stay constant size under zoom/pan."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsItemGroup, QGraphicsLineItem,
                               QGraphicsSimpleTextItem)

_IGNORE = QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations


def _text(s, color):
    t = QGraphicsSimpleTextItem(s)
    t.setBrush(QColor(color))
    f = QFont(); f.setPointSizeF(10.0); t.setFont(f)
    t.setFlag(_IGNORE, True)
    return t


def build_annotation_group(objects, north_angle, scale_len_px, scale_label,
                           shape, theme="dark") -> QGraphicsItemGroup:
    color = "#e7ebf3" if theme == "dark" else "#161c27"
    accent = "#5b9cf0"
    g = QGraphicsItemGroup()
    h, w = shape

    for o in objects:
        label = _text(f"{o.name}" + (f"  {o.common}" if o.common else ""), color)
        label.setPos(o.x + 6, o.y + 6)                 # anchored on the object
        g.addToGroup(label)
        dot = QGraphicsLineItem(o.x, o.y, o.x, o.y)    # a marker point
        dot.setPen(QPen(QColor(accent), 3)); dot.setFlag(_IGNORE, True)
        g.addToGroup(dot)

    # compass: a short N line from a fixed corner anchor
    ax, ay = w - 90, 90
    rad = math.radians(north_angle)
    n = QGraphicsLineItem(ax, ay, ax + 40 * math.cos(rad), ay + 40 * math.sin(rad))
    n.setPen(QPen(QColor(accent), 2)); n.setFlag(_IGNORE, True)
    g.addToGroup(n)
    nlab = _text("N", accent); nlab.setPos(ax + 44 * math.cos(rad), ay + 44 * math.sin(rad))
    g.addToGroup(nlab)

    # scale bar near the bottom-left
    bx, by = 80, h - 80
    bar = QGraphicsLineItem(bx, by, bx + scale_len_px, by)
    bar.setPen(QPen(QColor(color), 2)); bar.setFlag(_IGNORE, True)
    g.addToGroup(bar)
    slab = _text(scale_label, color); slab.setPos(bx, by - 20)
    g.addToGroup(slab)
    return g
