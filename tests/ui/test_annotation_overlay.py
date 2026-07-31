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


def test_compass_label_renders_bold(qtbot):
    g = build_annotation_group([Label("N", 10, 10, "#6aa8f2", "compass")], (600, 800))
    assert g.childItems()[0].font().bold()


def test_an_empty_primitive_list_yields_an_empty_group(qtbot):
    assert build_annotation_group([], (600, 800)).childItems() == []
