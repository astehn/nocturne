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


def test_every_item_ignores_the_view_transform(qtbot):
    from PySide6.QtWidgets import QGraphicsItem
    prims = [Circle(10, 10, 20, "#5cff5c", False), Label("X", 30, 30, "#5cff5c"),
             Leader(1, 1, 9, 9, "#5cff5c"), Marker(5, 5, "star", "#5cff5c")]
    g = build_annotation_group(prims, (600, 800))
    flag = QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
    for c in g.childItems():
        assert c.flags() & flag, "labels must stay readable at any zoom"


def test_an_empty_primitive_list_yields_an_empty_group(qtbot):
    assert build_annotation_group([], (600, 800)).childItems() == []
