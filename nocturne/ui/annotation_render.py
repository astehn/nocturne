"""QPainter adapter: burns a primitive list from `core.annotation_layout`
straight onto an exported `QImage`, in place — and the ONE place the overlay's
look is defined. The live canvas (`ui.annotation_overlay`) builds its items
from the helpers here (`label_path`, `paint_text_path`, the stroke widths), so
the preview and the export cannot drift apart in style (the 2026-10-15 restyle:
soft halo, two-line major labels, raised h/m, gapped star reticle).

Everything is defined at the 1200 px reference (`LABEL_PT`, the widths below)
and multiplied by a scale: `scale_for(shape)` in the export, 1 on the canvas,
whose items stay a constant screen size. Text is built as a path at the
reference size and then scaled, so its size is exactly linear in the scale —
which is what lets `annotation_overlay.make_measure(ui_scale)` reserve exactly
the box either consumer later paints.

The export's scale must also reach `build_layout_for(ui_scale=...)` (the caller,
`main_window._annotation_primitives`, does that): the layout reserves space at
that scale, so painting bigger than it reserved would make labels collide."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen,
                           QTransform)

from ..core.annotation_layout import LABEL_PT, STAR_RETICLE, Circle, GridLine, Label, Leader, Marker

_REF_DIM = 1200.0   # the reference frame LABEL_PT and the widths below are tuned at

# Text is set in PIXELS. A point size resolves through the screen's logical DPI
# — 72 on macOS, 96 offscreen, on Windows and Linux — so the same LABEL_PT drew
# his Mac's export at 0.75x the approved mockup (rendered offscreen, 96 dpi) and
# every other platform 1.33x the Mac. LABEL_PT x 96/72 keeps the approved look.
LABEL_PX = {k: v * 96.0 / 72.0 for k, v in LABEL_PT.items()}
_MIN_PX = 4.0 * 96.0 / 72.0   # floor so text never vanishes on a tiny export
_BASE_PX = 100      # glyphs are built at this pixel size, then scaled to LABEL_PX

# Requested, not bundled: the approved mockup was drawn in it. Where it is absent
# the list falls through named sans faces (Windows, then everywhere, then
# Linux), and the hint keeps Qt from substituting a serif. Measure and paint
# use the same font, so whichever face lands, the layout holds.
FONT_FAMILY = "Helvetica Neue"
FONT_FAMILIES = [FONT_FAMILY, "Segoe UI", "Arial", "DejaVu Sans"]
_MEDIUM_SIZES = {"major", "major_common"}

# The soft halo: widening faint dark strokes under the fill, widest first
# (reference px, alpha), so small text reads on bright nebula. A dark slate,
# not black, and faint: he found the near-black first version too heavy
# (2026-10-15). Major labels read on their size and weight alone; the two
# whisper strokes they keep only firm the letter edges where M 16's title sits
# on same-red nebula (rendered with none and with these, cocoa, M16.nocturne).
HALO_RGB = (22, 26, 36)
HALO_STROKES = ((6.0, 24), (4.0, 44), (2.4, 76))
MAJOR_HALO_STROKES = ((4.0, 18), (2.2, 34))
HALO_PAD = HALO_STROKES[0][0] / 2 + 1.0   # + the antialias fringe, or it trails on scroll

# Raised runs (the h and m of 2ʰ40ᵐ): set this much smaller and lifted by this
# fraction of the line's ascent, as the mockup drew them.
RAISED_SIZE = 0.66
RAISED_LIFT = 0.42

# Stroke widths, reference px.
RING_WIDTH = 1.1
RING_HALO_WIDTH = 2.6
RING_HALO_ALPHA = 60
RETICLE_WIDTH = 1.4
POINT_RADIUS = 3.75       # an LBN's "about here" ring, reference px: not a star, not LDN's dashes
LEADER_WIDTH = 1.4
GRID_WIDTH = 1.2


def scale_for(shape) -> float:
    """The export `ui_scale`: the image's own smaller dimension against the
    `_REF_DIM` baseline. `main_window` passes the SAME number to
    `build_layout_for`, so what is reserved is what is painted."""
    h, w = shape
    return max(min(h, w), 1.0) / _REF_DIM


def _ref_px(size: str) -> float:
    return LABEL_PX.get(size, LABEL_PX["minor"])


def _eff(size: str, scale: float) -> float:
    """The factor a size class is actually drawn at: `scale`, floored."""
    return max(scale, _MIN_PX / _ref_px(size))


def _font(size: str, factor: float = 1.0) -> QFont:
    """The face at `_BASE_PX` x factor pixels; callers scale to LABEL_PX."""
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setStyleHint(QFont.StyleHint.SansSerif)
    f.setPixelSize(round(_BASE_PX * factor))
    if size in _MEDIUM_SIZES:
        f.setWeight(QFont.Weight.Medium)
    return f


def _line_at_ref(text: str, size: str, parts=()) -> tuple[QPainterPath, float, float]:
    """One line at the reference size, top-left at the origin: (path, w, h)."""
    path, w, h = _line_at_base(text, size, parts)
    k = _ref_px(size) / _BASE_PX
    return QTransform.fromScale(k, k).map(path), w * k, h * k


def _line_at_base(text: str, size: str, parts=()) -> tuple[QPainterPath, float, float]:
    """One line at `_BASE_PX`. The width is the PLAIN text's advance — what the
    measure saw — and a line of raised runs, being a little narrower, is
    centred inside it."""
    f = _font(size)
    fm = QFontMetricsF(f)
    w, h, base = fm.horizontalAdvance(text), fm.height(), fm.ascent()
    path = QPainterPath()
    if not parts:
        path.addText(QPointF(0.0, base), f, text)
        return path, w, h
    small = _font(size, RAISED_SIZE)
    sfm = QFontMetricsF(small)
    kern = 1.0 * _BASE_PX / _ref_px(size)      # the mockup's 1 px, in base px
    runs_w = sum(sfm.horizontalAdvance(r) + kern if raised else fm.horizontalAdvance(r)
                 for r, raised in parts)
    x = max(w - runs_w, 0.0) / 2
    for run, raised in parts:
        if raised:
            path.addText(QPointF(x + kern / 2, base - fm.ascent() * RAISED_LIFT), small, run)
            x += sfm.horizontalAdvance(run) + kern
        else:
            path.addText(QPointF(x, base), f, run)
            x += fm.horizontalAdvance(run)
    return path, w, h


def text_extent(text: str, size: str, scale: float = 1.0) -> tuple[float, float]:
    """(w, h) of one line at `scale` — the measure both consumers lay out with.
    The same numbers `_line_at_base` lays the line out with, from metrics alone:
    building the glyph path just to measure it tripled the canvas relayout."""
    fm = _base_metrics(size)
    k = _ref_px(size) / _BASE_PX * _eff(size, scale)
    return fm.horizontalAdvance(text) * k, fm.height() * k


_METRICS: dict = {}


def _base_metrics(size: str) -> QFontMetricsF:
    fm = _METRICS.get(size)
    if fm is None:
        fm = _METRICS[size] = QFontMetricsF(_font(size))
    return fm


def _scaled_line(text, size, scale, parts=()):
    path, w, h = _line_at_ref(text, size, parts)
    e = _eff(size, scale)
    return QTransform.fromScale(e, e).map(path), w * e, h * e


def label_path(p: Label, scale: float = 1.0) -> QPainterPath:
    """The label's glyphs as one path, its block's top-left at the origin.
    Two lines (`sub`) are each centred in the wider one's width."""
    top, w1, h1 = _scaled_line(p.text, p.size, scale, p.parts)
    if not p.sub:
        return top
    sub, w2, _h2 = _scaled_line(p.sub, p.sub_size or p.size, scale)
    width = max(w1, w2)
    out = QPainterPath()
    out.addPath(top.translated((width - w1) / 2, 0.0))
    out.addPath(sub.translated((width - w2) / 2, h1))
    return out


def halo_strokes(tier: str) -> tuple:
    return MAJOR_HALO_STROKES if tier == "major" else HALO_STROKES


def halo_pens(scale: float, tier: str = "") -> list:
    pens = []
    for width, alpha in halo_strokes(tier):
        pen = QPen(QColor(*HALO_RGB, alpha))
        pen.setWidthF(width * scale)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pens.append(pen)
    return pens


def paint_text_path(painter: QPainter, path: QPainterPath, colour: str, scale: float,
                    tier: str = "") -> None:
    """Halo strokes (by tier), widest first, then the fill. The fill is never
    stroked: a centred stroke would eat into the letterform."""
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for pen in halo_pens(scale, tier):
        painter.setPen(pen)
        painter.drawPath(path)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(colour))
    painter.drawPath(path)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def ring_pens(p: Circle, scale: float) -> list:
    """A faint dark ring under the thin coloured one, so it reads on nebula."""
    halo = QPen(QColor(*HALO_RGB, RING_HALO_ALPHA))
    halo.setWidthF(RING_HALO_WIDTH * scale)
    ring = QPen(QColor(p.colour))
    ring.setWidthF(RING_WIDTH * scale)
    if p.dashed:                                    # 'we don't know how big this is'
        halo.setStyle(Qt.PenStyle.DashLine)
        ring.setStyle(Qt.PenStyle.DashLine)
    return [halo, ring]


def point_pens(p: Marker, scale: float) -> list:
    """An LBN point is a ring in miniature: the same faint dark under-stroke
    and thin solid stroke as the object rings, so it reads on bright nebula."""
    return ring_pens(Circle(p.x, p.y, POINT_RADIUS, p.colour), scale)


def reticle_spans(p: Marker, scale: float = 1.0) -> list:
    """Four arms from `gap` to `gap + arm` out from the star — a hole over the
    star itself, so the star stays visible."""
    gap, arm = STAR_RETICLE.get(p.size, STAR_RETICLE["star"])
    gap, end = gap * scale, (gap + arm) * scale
    return [((gap, 0.0), (end, 0.0)), ((-gap, 0.0), (-end, 0.0)),
            ((0.0, -gap), (0.0, -end)), ((0.0, gap), (0.0, end))]


def line_pen(colour: str, width: float) -> QPen:
    pen = QPen(QColor(colour))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


def grid_width(scale: float) -> float:
    return max(GRID_WIDTH * scale, 1.0)


def _paint_circle(painter: QPainter, p: Circle, scale: float) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for pen in ring_pens(p, scale):
        painter.setPen(pen)
        painter.drawEllipse(QPointF(p.x, p.y), p.r, p.r)


def _paint_marker(painter: QPainter, p: Marker, scale: float) -> None:
    if p.kind == "point":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for pen in point_pens(p, scale):
            painter.setPen(pen)
            painter.drawEllipse(QPointF(p.x, p.y), POINT_RADIUS * scale, POINT_RADIUS * scale)
        return
    painter.setPen(line_pen(p.colour, RETICLE_WIDTH * scale))
    for (x1, y1), (x2, y2) in reticle_spans(p, scale):
        painter.drawLine(QPointF(p.x + x1, p.y + y1), QPointF(p.x + x2, p.y + y2))


def _paint_label(painter: QPainter, p: Label, scale: float) -> None:
    paint_text_path(painter, label_path(p, scale).translated(p.x, p.y), p.colour, scale, p.tier)


def _paint_leader(painter: QPainter, p: Leader, scale: float) -> None:
    painter.setPen(line_pen(p.colour, LEADER_WIDTH * scale))
    painter.drawLine(QPointF(p.x1, p.y1), QPointF(p.x2, p.y2))


def _paint_grid_line(painter: QPainter, p: GridLine, scale: float) -> None:
    if len(p.points) < 2:
        return
    painter.setPen(line_pen(p.colour, grid_width(scale)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(*p.points[0])
    for x, y in p.points[1:]:
        path.lineTo(x, y)
    painter.drawPath(path)
    if p.label:     # build_layout_for sends the text as its own Label; old callers did not
        x0, y0 = p.points[0]
        _paint_label(painter, Label(p.label, x0 + 3.0 * scale, y0 - 12.0 * scale, p.colour,
                                    "grid", parts=p.parts), scale)


def paint_annotations(image: QImage, primitives, shape) -> None:
    """Paints `primitives` (from `build_layout_for`) onto `image` in place.
    `shape` is `(h, w)` of the frame they were laid out for and sets the scale."""
    if not primitives:
        return
    scale = scale_for(shape)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
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
