"""QPainter adapter: burns a primitive list from `core.annotation_layout`
straight onto an exported `QImage`, in place. This exists to close PS-07 —
the live overlay drew named stars and the burned PNG export silently did
not, because the export path used to build its own primitives independently.
Now both adapters walk the SAME primitive list from `build_layout_for`; this
file only knows how to turn a Circle/Marker/Label/Leader/GridLine into pixels
on a raster image, mirroring `ui.annotation_overlay`'s Qt-canvas adapter
primitive-for-primitive.

Size mapping is DELIBERATELY different from the live adapter, though. The
live adapter (`annotation_overlay._SIZE_PT`) maps size classes to constant
ON-SCREEN point sizes — correct there because `ItemIgnoresTransformations`
already pins those items to a fixed device-pixel size regardless of the
image's resolution or the current zoom. An export has no "screen" to pin
against: reusing those same constant point sizes verbatim would leave a
6000px export with 15pt text lost in a corner. Instead every size class here
is scaled relative to the EXPORTED IMAGE's own dimensions — specifically its
SMALLER dimension against a nominal 1200px baseline (chosen to match the
live adapter's point sizes at a typical on-screen working resolution) — so
text and glyphs come out proportionally sized at any export resolution, with
a floor (`_MIN_PT`) so they never shrink to nothing on a tiny export.

There is no "screen" in an export, so `screen_fixed` on a `Leader` (the
compass arrow's cosmetic-HUD flag) is not consulted here — every primitive
is drawn in plain image-space, with only its size CLASS (not its position)
going through the export size mapping."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen

from ..core.annotation_layout import Circle, GridLine, Label, Leader, Marker

# Mirrors annotation_overlay._SIZE_PT exactly -- the two must start from the
# same numbers so the export "reads like" the live overlay once scaled.
_SIZE_PT = {"primary": 16.0, "secondary": 14.0, "star": 12.0, "star_bright": 14.0,
            "grid": 11.0, "compass": 17.0}
_DEFAULT_PT = _SIZE_PT["secondary"]
_BOLD_SIZES = {"compass"}
_OUTLINE_COLOUR = "#0a0f18"

_REF_DIM = 1200.0   # baseline the live adapter's constant point sizes read
                     # naturally at; see module docstring
_MIN_PT = 4.0        # floor so text/glyphs never vanish on a tiny export


def _scale_for(shape) -> float:
    h, w = shape
    return max(min(h, w), 1.0) / _REF_DIM


def _pt(size: str, scale: float) -> float:
    return max(_SIZE_PT.get(size, _DEFAULT_PT) * scale, _MIN_PT)


def _paint_circle(painter: QPainter, p: Circle, scale: float) -> None:
    # r is a TRUE image-pixel radius (angular extent / pixel scale) -- already
    # in the right units, so only the stroke width comes from the size scale.
    pen = QPen(QColor(p.colour))
    pen.setWidthF(max(1.6 * scale, 1.0))
    if p.dashed:
        pen.setStyle(Qt.PenStyle.DashLine)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(p.x, p.y), p.r, p.r)


def _star_tick_spans(size: str, scale: float) -> list:
    """Four short ticks flanking the star, never a cross through it — mirrors
    annotation_overlay._star_ticks."""
    pt = _SIZE_PT.get(size, _SIZE_PT["star"]) * scale
    gap, arm = pt * 0.35, pt * 0.55
    return [((gap, 0.0), (gap + arm, 0.0)), ((-gap, 0.0), (-gap - arm, 0.0)),
            ((0.0, -gap), (0.0, -gap - arm)), ((0.0, gap), (0.0, gap + arm))]


def _paint_marker(painter: QPainter, p: Marker, scale: float) -> None:
    pen = QPen(QColor(p.colour))
    if p.kind == "star":
        pen.setWidthF(max(1.5 * scale, 1.0))
        painter.setPen(pen)
        for (x1, y1), (x2, y2) in _star_tick_spans(p.size, scale):
            painter.drawLine(QPointF(p.x + x1, p.y + y1), QPointF(p.x + x2, p.y + y2))
    else:                                            # "compass" (and future non-star kinds)
        r = max(3.0 * scale, 1.5)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(QColor(p.colour))
        painter.drawEllipse(QPointF(p.x, p.y), r, r)
        painter.setBrush(Qt.BrushStyle.NoBrush)


def _paint_text(painter: QPainter, text: str, x: float, y: float, colour: str,
                size: str, scale: float) -> None:
    """(x, y) is the top-left anchor, matching Label's contract with
    place_labels/annotation_overlay (QGraphicsSimpleTextItem.setPos)."""
    font = QFont()
    font.setPointSizeF(_pt(size, scale))
    font.setBold(size in _BOLD_SIZES)
    fm = QFontMetricsF(font)
    path = QPainterPath()
    path.addText(QPointF(x, y + fm.ascent()), font, text)
    pen = QPen(QColor(_OUTLINE_COLOUR))
    pen.setWidthF(max(1.1 * scale, 0.6))
    painter.setPen(pen)
    painter.setBrush(QColor(colour))
    painter.drawPath(path)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _paint_label(painter: QPainter, p: Label, scale: float) -> None:
    _paint_text(painter, p.text, p.x, p.y, p.colour, p.size, scale)


def _paint_leader(painter: QPainter, p: Leader, scale: float) -> None:
    # Endpoints are real image positions regardless of screen_fixed (there is
    # no "screen" in an export); only the stroke width comes from the scale.
    pen = QPen(QColor(p.colour))
    pen.setWidthF(max(1.2 * scale, 1.0))
    painter.setPen(pen)
    painter.drawLine(QPointF(p.x1, p.y1), QPointF(p.x2, p.y2))


def _paint_grid_line(painter: QPainter, p: GridLine, scale: float) -> None:
    if len(p.points) < 2:
        return
    pen = QPen(QColor(p.colour))
    pen.setWidthF(max(1.0 * scale, 1.0))
    painter.setPen(pen)
    path = QPainterPath()
    x0, y0 = p.points[0]
    path.moveTo(x0, y0)
    for x, y in p.points[1:]:
        path.lineTo(x, y)
    painter.drawPath(path)
    if p.label:
        _paint_text(painter, p.label, x0 + 3.0, y0 - 12.0, p.colour, "grid", scale)


def paint_annotations(image: QImage, primitives, shape) -> None:
    """Paints `primitives` (from `core.annotation_layout.build_layout_for`)
    onto `image` in place. `shape` is `(h, w)` and drives the export size
    mapping (see module docstring) -- it is independent of `image`'s own
    size, matching build_layout_for's convention of measuring against the
    frame the primitives were laid out for."""
    if not primitives:
        return
    scale = _scale_for(shape)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    try:
        for p in primitives:
            if isinstance(p, Circle):
                _paint_circle(painter, p, scale)
            elif isinstance(p, Marker):
                _paint_marker(painter, p, scale)
            elif isinstance(p, Label):
                _paint_label(painter, p, scale)
            elif isinstance(p, Leader):
                _paint_leader(painter, p, scale)
            elif isinstance(p, GridLine):
                _paint_grid_line(painter, p, scale)
    finally:
        painter.end()
