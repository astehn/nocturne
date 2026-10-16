import pytest

pytest.importorskip("PySide6")
from nocturne.core.annotation_layout import Circle, Label, Leader, Marker  # noqa: E402
from nocturne.ui.annotation_overlay import build_annotation_group  # noqa: E402


def test_group_contains_one_item_per_primitive(qtbot):
    prims = [Circle(10, 10, 20, "#5cff5c", False), Label("NGC 7000", 30, 30, "#5cff5c")]
    g = build_annotation_group(prims, (600, 800))
    assert len(g.childItems()) >= 2


def test_a_dashed_circle_renders_with_a_dashed_pen(qtbot):
    from PySide6.QtCore import Qt
    g = build_annotation_group([Circle(10, 10, 6, "#5cff5c", True)], (600, 800))
    pens = [c.pen().style() for c in g.childItems() if hasattr(c, "pen")]
    assert Qt.PenStyle.DashLine in pens


def test_star_marker_leaves_a_gap_over_the_star(qtbot):
    g = build_annotation_group([Marker(50, 50, "star", "#5cff5c")], (600, 800))
    lines = [c for c in g.childItems() if hasattr(c, "line")]
    assert len(lines) >= 2
    for ln in lines:
        l = ln.line()
        assert not (min(l.x1(), l.x2()) <= 0 <= max(l.x1(), l.x2())
                    and min(l.y1(), l.y2()) <= 0 <= max(l.y1(), l.y2())), \
            "no tick may pass through the star's own position"


def test_measured_geometry_scales_with_the_image_not_the_view(qtbot):
    # Circle (a true angular extent) and a plain Leader (connects two real
    # image positions) must NOT ignore the view transform -- freezing them to
    # a constant device-pixel size would defeat Task 1's true-size geometry.
    from PySide6.QtWidgets import QGraphicsItem
    flag = QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations

    g = build_annotation_group([Circle(10, 10, 20, "#5cff5c", False)], (600, 800))
    assert not (g.childItems()[0].flags() & flag), \
        "a true-size ring must scale with zoom to keep marking the real angular extent"

    g = build_annotation_group([Leader(1, 1, 9, 9, "#5cff5c")], (600, 800))
    assert not (g.childItems()[0].flags() & flag), \
        "a leader connects two real image positions and must scale/pan with the image"


def test_glyphs_stay_a_constant_screen_size(qtbot):
    # Text and point glyphs (labels, star ticks) are annotations, not
    # measurements, so they must stay readable regardless of zoom.
    from PySide6.QtWidgets import QGraphicsItem
    flag = QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
    prims = [Label("X", 30, 30, "#5cff5c"), Marker(5, 5, "star", "#5cff5c")]
    g = build_annotation_group(prims, (600, 800))
    assert g.childItems(), "expected at least the label and star ticks"
    for c in g.childItems():
        assert c.flags() & flag, "labels and star ticks must stay readable at any zoom"


def test_the_compass_arrow_stays_a_constant_screen_size_unlike_a_plain_leader(qtbot):
    # The compass arrow is a cosmetic HUD indicator, not a measured line, so
    # it's the one Leader that opts BACK into ignoring the view transform.
    from PySide6.QtWidgets import QGraphicsItem
    flag = QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
    g = build_annotation_group([Leader(1, 1, 9, 9, "#5cff5c", screen_fixed=True)], (600, 800))
    assert g.childItems()[0].flags() & flag


def test_circle_item_rect_matches_its_true_radius_in_scene_units(qtbot):
    # Pins the actual consequence of dropping _IGNORE: if a future change
    # reintroduces device-pixel-constant sizing, this must fail loudly.
    g = build_annotation_group([Circle(10, 10, 37.5, "#5cff5c", False)], (600, 800))
    rect = g.childItems()[0].rect()
    assert rect.width() == pytest.approx(75.0)
    assert rect.height() == pytest.approx(75.0)


def test_a_label_is_one_item_painted_by_the_export_painter(qtbot):
    """The canvas label is not a Qt text item with its own idea of the look: it
    holds the export's label path and paints it with the export's halo."""
    from nocturne.ui import annotation_render as R
    from nocturne.ui.annotation_overlay import LabelItem
    p = Label("IC 1805", 10, 10, "#f4877c", "major", sub="Heart Nebula", sub_size="major_common")
    g = build_annotation_group([p], (600, 800))
    (item,) = g.childItems()
    assert isinstance(item, LabelItem)
    assert item.path == R.label_path(p, 1.0)
    assert (item.pos().x(), item.pos().y()) == (10, 10)


def test_rings_draw_a_faint_dark_ring_under_a_thin_tier_coloured_one(qtbot):
    from nocturne.ui import annotation_render as R
    g = build_annotation_group([Circle(10, 10, 20, "#c8f4877c", False, "major")], (600, 800))
    halo, ring = g.childItems()
    assert halo.pen().widthF() == R.RING_HALO_WIDTH and halo.pen().color().alpha() == R.RING_HALO_ALPHA
    assert ring.pen().widthF() == R.RING_WIDTH
    assert ring.pen().color().alpha() == 0xc8, "the tier colour's own alpha survives"
    assert halo.pen().isCosmetic() and ring.pen().isCosmetic()


def test_the_canvas_reticle_has_the_star_reticle_gap(qtbot):
    import math
    from nocturne.core.annotation_layout import STAR_RETICLE
    gap, arm = STAR_RETICLE["star"]
    g = build_annotation_group([Marker(50, 50, "star", "#ebffd447")], (600, 800))
    arms = g.childItems()
    assert len(arms) == 4
    for a in arms:
        ln = a.line()
        near = min(math.hypot(ln.x1(), ln.y1()), math.hypot(ln.x2(), ln.y2()))
        far = max(math.hypot(ln.x1(), ln.y1()), math.hypot(ln.x2(), ln.y2()))
        assert near == pytest.approx(gap) and far == pytest.approx(gap + arm)


def test_an_empty_primitive_list_yields_an_empty_group(qtbot):
    assert build_annotation_group([], (600, 800)).childItems() == []


def test_a_label_is_cached_so_a_repaint_does_not_restroke_its_halo(qtbot):
    from PySide6.QtWidgets import QGraphicsItem
    g = build_annotation_group([Label("NGC 7000", 10, 10, "#f4877c", "major")], (600, 800))
    (item,) = g.childItems()
    assert item.cacheMode() == QGraphicsItem.CacheMode.DeviceCoordinateCache


def test_a_labels_box_covers_its_widest_halo_and_the_antialias_fringe(qtbot):
    from nocturne.ui import annotation_render as R
    g = build_annotation_group([Label("NGC 7000", 10, 10, "#f4877c", "major")], (600, 800))
    (item,) = g.childItems()
    ink, box = item.path.boundingRect(), item.boundingRect()
    reach = R.HALO_STROKES[0][0] / 2 + 1.0
    assert ink.left() - box.left() >= reach and box.right() - ink.right() >= reach
    assert ink.top() - box.top() >= reach and box.bottom() - ink.bottom() >= reach


def test_an_lbn_point_is_a_screen_fixed_hollow_ring_on_the_canvas(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QGraphicsItem
    from nocturne.core.annotation_layout import Circle
    from nocturne.ui import annotation_render as R
    p = Marker(50, 60, "point", "#94eef1f6", "point")
    g = build_annotation_group([p], (600, 800))
    items = g.childItems()
    want = R.ring_pens(Circle(0, 0, R.POINT_RADIUS, p.colour), 1.0)   # the rings' own pair
    assert len(items) == len(want) == 2
    for item, pen in zip(items, want):
        assert item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
        assert (item.pos().x(), item.pos().y()) == (50, 60)
        assert item.rect().width() == pytest.approx(2 * R.POINT_RADIUS)
        assert item.brush().style() == Qt.BrushStyle.NoBrush          # hollow
        assert item.pen().style() == Qt.PenStyle.SolidLine            # not LDN's dashes
        assert item.pen().color() == pen.color() and item.pen().widthF() == pen.widthF()
    assert items[1].pen().color() == QColor("#94eef1f6")
