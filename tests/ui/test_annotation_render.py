import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QImage  # noqa: E402
from nocturne.core.annotation_layout import Circle, GridLine, Label, Leader, Marker  # noqa: E402
from nocturne.ui.annotation_render import paint_annotations  # noqa: E402


def _blank(w=400, h=300):
    im = QImage(w, h, QImage.Format.Format_RGB888)
    im.fill(0)
    return im


def test_painting_changes_pixels():
    im = _blank()
    before = im.copy()
    paint_annotations(im, [Circle(200, 150, 40, "#5cff5c", False)], (300, 400))
    assert im != before


def test_nothing_painted_for_an_empty_list():
    im = _blank()
    before = im.copy()
    paint_annotations(im, [], (300, 400))
    assert im == before


def test_star_markers_reach_the_exported_image():
    # PS-07: the live overlay drew named stars, the burned export did not.
    im = _blank()
    paint_annotations(im, [Marker(200, 150, "star", "#5cff5c")], (300, 400))
    assert im != _blank()


def test_dashed_circle_reaches_the_exported_image():
    # The grid layer defaults off, so nothing else exercises the dashed
    # ("unknown size") ring style through paint_annotations -- a silent skip
    # here (e.g. an unhandled Qt.PenStyle branch) would go uncaught until a
    # real export with an unsized object.
    im = _blank()
    paint_annotations(im, [Circle(200, 150, 40, "#5cff5c", True)], (300, 400))
    assert im != _blank()


def test_leader_reaches_the_exported_image():
    im = _blank()
    paint_annotations(im, [Leader(50, 50, 250, 200, "#e7ecf4")], (300, 400))
    assert im != _blank()


def test_grid_line_and_its_label_both_reach_the_exported_image(qtbot):
    # The grid layer defaults off (Task 7 gives it a real toggle), so this is
    # currently the ONLY place GridLine goes through paint_annotations --
    # without it a silent skip in _paint_grid_line wouldn't be caught by any
    # other test. qtbot: this exercises _paint_text (QFontMetricsF/addText),
    # which needs a live QApplication -- unlike the other tests here, which
    # only draw shapes/lines and happen to work without one.
    im = _blank()
    paint_annotations(im, [GridLine([(20.0, 20.0), (120.0, 40.0), (200.0, 90.0)],
                                     "#6a7688", "+44°")], (300, 400))
    assert im != _blank()


def test_grid_line_without_a_label_still_paints():
    im = _blank()
    paint_annotations(im, [GridLine([(20.0, 20.0), (280.0, 280.0)], "#6a7688")], (300, 400))
    assert im != _blank()


def test_export_and_live_consume_the_same_primitive_list(qtbot):
    from nocturne.ui.annotation_overlay import build_annotation_group
    prims = [Circle(50, 50, 20, "#5cff5c", False), Marker(80, 80, "star", "#5cff5c"),
             Label("Deneb", 90, 90, "#5cff5c")]
    group = build_annotation_group(prims, (300, 400))
    im = _blank()
    paint_annotations(im, prims, (300, 400))
    assert len(group.childItems()) >= 3 and im != _blank(), \
        "one primitive list must drive both renderers"


# --- the 2026-10-15 restyle: one look, defined here, drawn by both adapters ---

from nocturne.core.annotation_layout import LABEL_PT, STAR_RETICLE  # noqa: E402
from nocturne.ui import annotation_render as R  # noqa: E402


class _RecordingPainter:
    """Stands in for QPainter to see the order of strokes and fills."""
    def __init__(self):
        self.calls, self.pen, self.brush = [], None, None

    def setPen(self, pen):
        self.pen = pen

    def setBrush(self, brush):
        self.brush = brush

    def drawPath(self, path):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QPen
        pen = self.pen if isinstance(self.pen, QPen) else None
        fill = self.brush if isinstance(self.brush, QColor) else None
        self.calls.append((pen.widthF() if pen else None, pen.color().alpha() if pen else None,
                           fill.name() if fill else None,
                           self.pen == Qt.PenStyle.NoPen))


def test_text_gets_a_soft_halo_of_widening_faint_strokes_then_a_clean_fill(qtbot):
    from PySide6.QtGui import QPainterPath
    rec = _RecordingPainter()
    R.paint_text_path(rec, QPainterPath(), "#f4877c", 2.0)
    strokes, fill = rec.calls[:-1], rec.calls[-1]
    assert len(strokes) == len(R.HALO_STROKES) >= 3
    widths = [w for w, _a, _f, _n in strokes]
    assert widths == sorted(widths, reverse=True), "widest first, so the inner strokes sit on top"
    assert widths == [w * 2.0 for w, _a in R.HALO_STROKES], "halo scales with the text"
    assert all(a < 255 for _w, a, _f, _n in strokes), "faint, not a hard outline"
    assert all(f is None for _w, _a, f, _n in strokes), "halo strokes never fill"
    assert fill[2] == "#f4877c" and fill[3], "the fill is the colour, never stroked"


def test_the_measure_reads_label_pt_and_is_linear_in_the_scale(qtbot):
    from nocturne.ui.annotation_overlay import make_measure
    m1, m3 = make_measure(1.0), make_measure(3.0)
    for size in LABEL_PT:
        w1, h1 = m1("IC 1805", size)
        w3, h3 = m3("IC 1805", size)
        assert (w3, h3) == pytest.approx((3 * w1, 3 * h1)), size
    assert m1("IC 1805", "major")[1] / m1("IC 1805", "minor")[1] == pytest.approx(
        LABEL_PT["major"] / LABEL_PT["minor"], rel=0.05)


def test_the_measure_is_exactly_the_painted_box(qtbot):
    """What the layout reserves is what is drawn: a label's ink sits inside the
    measured block (bar a sliver of side bearing), at any scale."""
    from nocturne.ui.annotation_overlay import make_measure
    for scale in (0.5, 1.0, 3.2):
        m = make_measure(scale)
        w, h = m("NGC 7000", "major")
        ink = R.label_path(Label("NGC 7000", 0, 0, "#fff", "major"), scale).boundingRect()
        assert ink.left() >= -0.05 * w and ink.right() <= w * 1.05, scale
        assert ink.top() >= 0 and ink.bottom() <= h, scale


def _ink_regions(path, split_y):
    from PySide6.QtCore import QRectF
    above, below = QRectF(), QRectF()
    for poly in path.toFillPolygons():
        r = poly.boundingRect()
        if r.center().y() < split_y:
            above = above.united(r)
        else:
            below = below.united(r)
    return above, below


@pytest.mark.parametrize("top, sub", [("IC 1805", "Heart Nebula"),          # sub wider
                                        ("M 16 · IC 4703", "Eagle")])         # top wider
def test_a_two_line_label_centres_each_line_in_the_block(qtbot, top, sub):
    from nocturne.ui.annotation_overlay import make_measure
    m = make_measure(1.0)
    w1, h1 = m(top, "major")
    w2, _h2 = m(sub, "major_common")
    width = max(w1, w2)
    p = Label(top, 0, 0, "#f4877c", "major", sub=sub, sub_size="major_common")
    top_ink, sub_ink = _ink_regions(R.label_path(p, 1.0), h1)
    assert abs(w1 - w2) > 20, "the lines must differ in width, or centring shows nothing"
    assert top_ink.center().x() == pytest.approx(width / 2, abs=1.5)
    assert sub_ink.center().x() == pytest.approx(width / 2, abs=1.5)
    assert sub_ink.top() >= h1 - 1, "the common name sits under the designation"
    assert sub_ink.height() < top_ink.height(), "and is set smaller"


def test_raised_runs_sit_above_the_baseline_and_smaller(qtbot):
    from PySide6.QtGui import QFontMetricsF
    k = R.LABEL_PX["grid"] / R._BASE_PX         # glyphs are built at _BASE_PX, then scaled
    fm = QFontMetricsF(R._font("grid"))
    base, adv2, asc = fm.ascent() * k, fm.horizontalAdvance("2") * k, fm.ascent() * k
    parts = (("2", False), ("h", True))
    raised = Label("2h", 0, 0, "#fff", "grid", parts=parts)
    plain = Label("2h", 0, 0, "#fff", "grid")
    shift = k * (fm.horizontalAdvance("2h") - (fm.horizontalAdvance("2") + QFontMetricsF(
        R._font("grid", R.RAISED_SIZE)).horizontalAdvance("h") + 1.0 / k)) / 2
    _l, h_raised = _ink_regions_x(R.label_path(raised, 1.0), shift + adv2)
    _l, h_plain = _ink_regions_x(R.label_path(plain, 1.0), adv2)
    assert h_raised.bottom() < base - 0.3 * asc, "lifted clear of the baseline"
    assert h_raised.height() < 0.8 * h_plain.height(), "set small"


def _ink_regions_x(path, split_x):
    from PySide6.QtCore import QRectF
    left, right = QRectF(), QRectF()
    for poly in path.toFillPolygons():
        r = poly.boundingRect()
        if r.center().x() < split_x:
            left = left.united(r)
        else:
            right = right.united(r)
    return left, right


def test_a_raised_line_is_centred_in_the_box_its_plain_text_reserved(qtbot):
    """The measure sees '2h40m'; the raised runs are narrower, so they are
    centred in that box — a grid label stays centred ON its line."""
    from nocturne.core.annotation_layout import ra_parts
    from nocturne.ui.annotation_overlay import make_measure
    parts = ra_parts(40.0)
    text = "".join(r for r, _ in parts)
    w, _h = make_measure(1.0)(text, "grid")
    ink = R.label_path(Label(text, 0, 0, "#fff", "grid", parts=parts), 1.0).boundingRect()
    assert ink.center().x() == pytest.approx(w / 2, abs=1.5)
    assert ink.width() < w - 2, "narrower than plain, or the test proves nothing"


def test_the_export_reticle_has_the_gap_at_the_export_scale():
    import math
    gap, arm = STAR_RETICLE["star"]
    for (x1, y1), (x2, y2) in R.reticle_spans(Marker(0, 0, "star", "#fff"), 2.5):
        assert min(math.hypot(x1, y1), math.hypot(x2, y2)) == pytest.approx(gap * 2.5)
        assert max(math.hypot(x1, y1), math.hypot(x2, y2)) == pytest.approx((gap + arm) * 2.5)


def test_canvas_and_export_draw_the_same_pixels_at_the_reference_scale(qtbot):
    """At a 1200 px frame the export scale is 1, which is the canvas's own
    scale at zoom 1: the two adapters must then produce the same picture."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QGraphicsScene
    from nocturne.ui.annotation_overlay import build_annotation_group
    shape = (1200, 1200)
    assert R.scale_for(shape) == 1.0
    prims = [Circle(300, 300, 80, "#c8f4877c", False, "major"),
             Marker(700, 300, "star", "#ebffd447"),
             Leader(100, 1100, 400, 1100, "#d2eef1f6"),
             GridLine([(0.0, 600.0), (1200.0, 650.0)], "#46ebf0f8"),
             Label("IC 1805", 250, 400, "#f4877c", "major", sub="Heart Nebula",
                   sub_size="major_common"),
             Label("2h40m", 600, 800, "#e6e6ebf2", "grid",
                   parts=(("2", False), ("h", True), ("40", False), ("m", True)))]
    export = QImage(1200, 1200, QImage.Format.Format_ARGB32_Premultiplied)
    export.fill(0xff101010)
    paint_annotations(export, prims, shape)

    canvas = QImage(1200, 1200, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(0xff101010)
    scene = QGraphicsScene(0, 0, 1200, 1200)
    scene.setBackgroundBrush(QColor(0x10, 0x10, 0x10))
    scene.addItem(build_annotation_group(prims, shape))
    p = QPainter(canvas)
    scene.render(p, QRectF(0, 0, 1200, 1200), QRectF(0, 0, 1200, 1200))
    p.end()

    import numpy as np
    def arr(im):
        b = im.constBits()
        return np.frombuffer(b, np.uint8).reshape(1200, 1200, 4).astype(int)
    a, b = arr(export), arr(canvas)
    assert (a != 0x10).any(), "something must have been drawn"
    diff = np.abs(a - b)
    assert diff.max() <= 8 and (diff > 2).mean() < 0.001, (diff.max(), (diff > 2).mean())


from PySide6.QtGui import QColor  # noqa: E402


def test_text_size_is_fixed_in_pixels_whatever_the_platform_dpi(qtbot):
    """Point sizes resolve through the screen's logical DPI: 72 on cocoa, 96
    offscreen/Windows/Linux, so his Mac exported text at 0.75x the approved
    mockup (rendered offscreen). Text is set in pixels: LABEL_PX = LABEL_PT x 96/72.
    Run under QT_QPA_PLATFORM=cocoa as well as the default offscreen."""
    for size in ("major", "minor", "grid"):
        px = R.LABEL_PX[size]
        assert px == pytest.approx(LABEL_PT[size] * 96 / 72)
        _w, h = R.text_extent("H", size, 1.0)
        # Wide enough for any sans a fallback brings (line height 1.1-1.4 em).
        assert 1.05 * px <= h <= 1.5 * px, (size, h, px)
        # And the glyphs themselves: a capital H stands 0.6-0.8 of the pixel size
        # in every sans, whatever the line metrics say.
        cap = R.label_path(Label("H", 0, 0, "#ffffff", size)).boundingRect().height()
        assert 0.6 * px <= cap <= 0.8 * px, (size, cap, px)


def test_font_falls_back_through_sans_faces_not_the_system_serif():
    """Helvetica Neue is not bundled: Windows and Linux must land on a sans
    (Segoe UI, Arial, DejaVu Sans), never whatever Qt's default happens to be."""
    from PySide6.QtGui import QFont
    f = R._font("minor")
    assert f.families()[:4] == ["Helvetica Neue", "Segoe UI", "Arial", "DejaVu Sans"]
    assert f.styleHint() == QFont.StyleHint.SansSerif
