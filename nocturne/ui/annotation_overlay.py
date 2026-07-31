"""Qt adapter: walks a primitive list from `core.annotation_layout` and builds
a QGraphicsItemGroup, in image-pixel (scene) coordinates. All the WHAT/WHERE/
colour decisions already happened in `build_layout_for` -- this file only
knows how to turn a Circle/Marker/Label/Leader/GridLine into Qt items.

ItemIgnoresTransformations makes an item render at a CONSTANT DEVICE-PIXEL
size regardless of zoom. That's correct for text and point glyphs, but wrong
for anything that represents a measured size or position in the image -- a
true-size ring frozen to a fixed device size no longer marks the object's
real angular extent once you zoom. The split:

  - Scale WITH the image (no flag): Circle (a true angular extent), a plain
    Leader (connects two real image positions -- a label back to its object,
    or the scale bar's line, whose length encodes the value on its label),
    and a GridLine's path (traces real WCS curvature across the frame).
  - Stay a CONSTANT screen size (flag set): every Label (including grid,
    compass and scale-bar captions), star tick marks (a star is a point
    source -- the glyph is an annotation, not a measurement), the compass
    dot, and the compass arrow specifically (`Leader.screen_fixed=True`) --
    it's a cosmetic HUD indicator, not a measured line."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainterPath, QPen
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsItemGroup,
                               QGraphicsLineItem, QGraphicsPathItem, QGraphicsSimpleTextItem)

from ..core.annotation_layout import Circle, GridLine, Label, Leader, Marker

_IGNORE = QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
_SIZE_PT = {"primary": 22.0, "secondary": 18.0, "star": 15.0, "star_bright": 17.0,
            "grid": 13.0, "compass": 20.0}
_DEFAULT_PT = _SIZE_PT["secondary"]
_BOLD_SIZES = {"compass"}          # the "N" is the only bold label; a dedicated size
                                    # class keeps Label's schema unchanged (no bold field)
_MIN_MEASURE_PT = 4.0              # mirrors annotation_render._MIN_PT -- the export's
                                    # painted floor, so a tiny export's reserved label
                                    # boxes match what it actually draws (see make_measure)


def make_measure(ui_scale: float = 1.0):
    """Builds a real QFontMetricsF-based `measure(text, size)` callable for
    `core.annotation_layout.build_layout_for`/`place_labels`, replacing the
    character-count approximation (`_default_measure`) with the font metrics
    an adapter actually renders with -- label collision avoidance is only as
    good as what it measures against.

    `ui_scale` must be the SAME value the caller hands to `build_layout_for`:
    1.0 (the default) for the live overlay, which renders at
    `annotation_overlay._SIZE_PT`'s constant on-screen sizes, or
    `annotation_render.scale_for(shape)` for the burned export, which scales
    those same point sizes to the exported image's resolution. This function
    mirrors both call sites' point-size table (`_SIZE_PT`/`_BOLD_SIZES`
    above, identical to `annotation_render`'s) AND `annotation_render`'s
    `_MIN_PT` floor, so a measure built for the export ui_scale reserves
    exactly the box that export will later paint into -- getting this out of
    sync is exactly the PS-07 class of bug (reserved space narrower than
    what gets drawn) one level up, at label-placement time rather than
    paint time.

    One QFontMetricsF per size class, built lazily and cached for the
    lifetime of the returned callable -- constructing a QFontMetricsF isn't
    free, and a single layout pass measures many labels."""
    cache: dict[str, QFontMetricsF] = {}

    def measure(text: str, size: str) -> tuple[float, float]:
        fm = cache.get(size)
        if fm is None:
            font = QFont()
            font.setPointSizeF(max(_SIZE_PT.get(size, _DEFAULT_PT) * ui_scale, _MIN_MEASURE_PT))
            font.setBold(size in _BOLD_SIZES)
            fm = QFontMetricsF(font)
            cache[size] = fm
        rect = fm.boundingRect(text)
        return float(rect.width()), float(fm.height())

    return measure


def _text(s, fill, size=_DEFAULT_PT, bold=False, outline="#0a0f18"):
    """Constant-size text with a TRUE halo: two stacked items, a wide dark one
    behind and the coloured fill in front.

    One item with pen+brush strokes the outline CENTRED on the glyph, so half
    the stroke eats into the letterform — which is why a thin outline was the
    only workable option before, and why labels vanished against bright
    nebulosity. Stacking keeps the letter intact at any halo width."""
    group = QGraphicsItemGroup()
    f = QFont()
    f.setPointSizeF(size)
    f.setBold(bold)
    for is_halo in (True, False):
        t = QGraphicsSimpleTextItem(s)
        t.setFont(f)
        if is_halo:
            pen = QPen(QColor(outline))
            pen.setWidthF(3.0)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCosmetic(True)
            t.setPen(pen)
            t.setBrush(QColor(outline))
        else:
            t.setPen(QPen(Qt.PenStyle.NoPen))
            t.setBrush(QColor(fill))                # the fill is the colour you read
        t.setFlag(_IGNORE, True)
        group.addToGroup(t)
    group.setFlag(_IGNORE, True)
    return group


def _circle_item(p: Circle) -> QGraphicsEllipseItem:
    # No _IGNORE: this is a TRUE-size ring (angular extent / pixel scale), so
    # its radius must scale with the image under zoom like the pixels it
    # marks. Only the stroke stays a legible constant width (setCosmetic).
    r = p.r
    item = QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
    item.setPos(p.x, p.y)
    pen = QPen(QColor(p.colour), 1.6)
    if p.dashed:                                    # 'we don't know how big this is'
        pen.setStyle(Qt.PenStyle.DashLine)
    pen.setCosmetic(True)
    item.setPen(pen)
    item.setBrush(Qt.BrushStyle.NoBrush)
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
    # that keeps the anchor end correctly tracking pan/zoom regardless of
    # whether the item itself also scales with the view.
    #
    # No _IGNORE by default: a leader connects two REAL image positions (a
    # label back to its object, or the scale bar's true angular length) and
    # must scale/pan with the image. `screen_fixed` is the one exception --
    # the compass arrow is a cosmetic HUD indicator, not a measurement.
    item = QGraphicsLineItem(0.0, 0.0, p.x2 - p.x1, p.y2 - p.y1)
    item.setPos(p.x1, p.y1)
    pen = QPen(QColor(p.colour), 1.2)
    pen.setCosmetic(True)
    item.setPen(pen)
    if p.screen_fixed:
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
            label = _text(p.text, p.colour, size=_SIZE_PT.get(p.size, _DEFAULT_PT),
                         bold=p.size in _BOLD_SIZES)
            label.setPos(p.x, p.y)
            g.addToGroup(label)
        elif isinstance(p, Leader):
            g.addToGroup(_leader_item(p))
        elif isinstance(p, GridLine):
            for item in _grid_line_items(p):
                g.addToGroup(item)
    return g
