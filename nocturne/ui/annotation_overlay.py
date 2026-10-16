"""Qt adapter: walks a primitive list from `core.annotation_layout` and builds
a QGraphicsItemGroup in image-pixel (scene) coordinates. The look itself —
fonts, halo, ring and reticle strokes — comes from `ui.annotation_render`, the
export painter, so the canvas and the burned export are drawn by the same code
at different scales: the export at `scale_for(shape)`, the canvas at 1 with
its glyphs held at a constant screen size.

ItemIgnoresTransformations pins an item to a constant device-pixel size at any
zoom. That is right for text and the star reticle, wrong for anything that
marks a measured size or position:

  - Scale WITH the image (no flag): Circle (a true angular extent), a Leader
    (the compass arrow and the scale bar, laid out in image px through
    ui_scale = 1/zoom and re-laid out per zoom), and a GridLine's path.
  - Constant screen size (flag set): every Label and the star reticle. A
    Leader marked `screen_fixed` (old callers only) also opts in.
Strokes are cosmetic, so a 1.1 px ring stays 1.1 px on screen at any zoom."""
from __future__ import annotations

import html

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QToolTip, QGraphicsEllipseItem, QGraphicsItem, QGraphicsItemGroup,
                               QGraphicsLineItem, QGraphicsPathItem)

from ..core.annotation_layout import Circle, GridLine, Label, Leader, Marker
from . import annotation_render as R

_IGNORE = QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
_AA = QPainter.RenderHint.Antialiasing


# The export paints antialiased; the ImageView does not turn it on for its
# scene (it is shared by six surfaces — opt-in, not a default), so every
# overlay item asks for it itself. Without it a 1.1 px ring is a staircase.
class _Ellipse(QGraphicsEllipseItem):
    def paint(self, painter, option, widget=None):
        painter.setRenderHint(_AA, True)
        super().paint(painter, option, widget)


class _Line(QGraphicsLineItem):
    def paint(self, painter, option, widget=None):
        painter.setRenderHint(_AA, True)
        super().paint(painter, option, widget)


class _Path(QGraphicsPathItem):
    def paint(self, painter, option, widget=None):
        painter.setRenderHint(_AA, True)
        super().paint(painter, option, widget)


def make_measure(ui_scale: float = 1.0):
    """A real `measure(text, size)` for `build_layout_for`, in image px at
    `ui_scale` — the SAME value the caller hands to `build_layout_for` (1/zoom
    on the canvas, `annotation_render.scale_for(shape)` for the export).

    It measures with the renderer's own `text_extent`, which is exactly
    linear in the scale, so the box reserved is the box either consumer paints:
    reserving narrower than what is drawn is the PS-07 class of bug one level
    up. One line at a time; the layout stacks two-line labels itself."""
    cache: dict[tuple[str, str], tuple[float, float]] = {}

    def measure(text: str, size: str) -> tuple[float, float]:
        key = (text, size)
        if key not in cache:
            cache[key] = R.text_extent(text, size, ui_scale)
        return cache[key]

    return measure


# Characters per line of a wrapped tip. Qt's own wrap heuristic gave 144–174
# px on macOS — about 30 characters, six or seven lines for the scale bar's
# tip (measured with a cocoa render, 2026-10-15); this is a reading measure.
_TIP_CHARS = 60


def _rich_tip(tip: str) -> str:
    """Qt word-wraps a rich-text tooltip and never a plain one: the scale bar's
    176-character tip showed as one line across the screen (2026-10-14). A
    fixed-width table sets the measure, since Qt honours a table's width and
    not a div's. The core's texts stay plain; only the item gets the markup,
    escaped so the words read exactly as written."""
    if not tip:
        return ""
    text = html.escape(tip, quote=False)
    if len(tip) <= _TIP_CHARS:
        return f"<qt>{text}</qt>"            # one line already: no padded box
    width = round(QFontMetricsF(QToolTip.font()).averageCharWidth() * _TIP_CHARS)
    return f'<table width="{width}"><tr><td>{text}</td></tr></table>'


class LabelItem(QGraphicsItem):
    """A label, painted by the export's own `paint_text_path` at scale 1 and
    held at a constant screen size. Its shape is its whole box, halo included,
    so a tooltip answers anywhere over the words, not only on the glyph ink."""

    def __init__(self, p: Label):
        super().__init__()
        self.text = p.text
        self.sub = p.sub
        self.colour = p.colour
        self.tier = p.tier
        self.path = R.label_path(p, 1.0)
        pad = R.HALO_PAD
        self._rect = self.path.boundingRect().adjusted(-pad, -pad, pad, pad)
        self.setFlag(_IGNORE, True)
        # Three wide antialiased halo strokes per label per repaint made a dense
        # field's canvas repaint 4x slower (NGC 7000 at fit, cocoa: 19 -> 86 ms);
        # cached, it is 13 ms. The label never changes, so the cache never goes stale.
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setPos(p.x, p.y)
        tip = _rich_tip(p.tip)
        if tip:
            self.setToolTip(tip)

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter, option, widget=None) -> None:
        painter.setRenderHint(_AA, True)
        R.paint_text_path(painter, self.path, self.colour, 1.0, self.tier)


def _cosmetic(pen: QPen) -> QPen:
    pen.setCosmetic(True)
    return pen


def _circle_items(p: Circle) -> list:
    # True size: no _IGNORE, so the ring keeps marking the real angular extent
    # under zoom; only the strokes stay a constant width (cosmetic).
    items = []
    for pen in R.ring_pens(p, 1.0):
        item = _Ellipse(-p.r, -p.r, 2 * p.r, 2 * p.r)
        item.setPos(p.x, p.y)
        item.setPen(_cosmetic(pen))
        items.append(item)
    return items


def _point_items(p: Marker) -> list:
    # Screen-fixed like the reticle; the same radius and fill the export paints.
    r = R.POINT_RADIUS
    dot = _Ellipse(-r, -r, 2 * r, 2 * r)
    dot.setPos(p.x, p.y)
    dot.setPen(QPen(Qt.PenStyle.NoPen))
    dot.setBrush(QColor(p.colour))
    dot.setFlag(_IGNORE, True)
    return [dot]


def _reticle_items(p: Marker) -> list:
    arms = []
    for (x1, y1), (x2, y2) in R.reticle_spans(p, 1.0):
        arm = _Line(x1, y1, x2, y2)
        arm.setPos(p.x, p.y)
        arm.setPen(_cosmetic(R.line_pen(p.colour, R.RETICLE_WIDTH)))
        arm.setFlag(_IGNORE, True)
        arms.append(arm)
    return arms


def _leader_item(p: Leader) -> QGraphicsLineItem:
    # Anchored at the first point so that end tracks pan/zoom exactly.
    item = _Line(0.0, 0.0, p.x2 - p.x1, p.y2 - p.y1)
    item.setPos(p.x1, p.y1)
    item.setPen(_cosmetic(R.line_pen(p.colour, R.LEADER_WIDTH)))
    if p.screen_fixed:
        item.setFlag(_IGNORE, True)
    return item


def _grid_line_items(p: GridLine) -> list:
    if len(p.points) < 2:
        return []
    path = QPainterPath()
    path.moveTo(*p.points[0])
    for x, y in p.points[1:]:
        path.lineTo(x, y)
    line_item = _Path(path)
    line_item.setPen(_cosmetic(R.line_pen(p.colour, R.grid_width(1.0))))
    items = [line_item]
    if p.label:     # build_layout_for sends the text as its own Label; old callers did not
        x0, y0 = p.points[0]
        items.append(LabelItem(Label(p.label, x0 + 3.0, y0 - 12.0, p.colour, "grid",
                                     tip=p.tip, parts=p.parts)))
    return items


def build_annotation_group(primitives, shape) -> QGraphicsItemGroup:
    """Turns a flat primitive list (from `build_layout_for`) into a
    QGraphicsItemGroup for the canvas. `shape` is accepted for parity with the
    export adapter; primitive coordinates are already absolute."""
    g = QGraphicsItemGroup()
    for p in primitives:
        if isinstance(p, Circle):
            items = _circle_items(p)
        elif isinstance(p, Marker):
            items = _point_items(p) if p.kind == "point" else _reticle_items(p)
        elif isinstance(p, Label):
            items = [LabelItem(p)]
        elif isinstance(p, Leader):
            items = [_leader_item(p)]
        elif isinstance(p, GridLine):
            items = _grid_line_items(p)
        else:
            items = []
        for item in items:
            g.addToGroup(item)
    return g
