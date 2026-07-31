import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QImage  # noqa: E402
from nocturne.core.annotation_layout import Circle, Label, Marker  # noqa: E402
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


def test_export_and_live_consume_the_same_primitive_list(qtbot):
    from nocturne.ui.annotation_overlay import build_annotation_group
    prims = [Circle(50, 50, 20, "#5cff5c", False), Marker(80, 80, "star", "#5cff5c"),
             Label("Deneb", 90, 90, "#5cff5c")]
    group = build_annotation_group(prims, (300, 400))
    im = _blank()
    paint_annotations(im, prims, (300, 400))
    assert len(group.childItems()) >= 3 and im != _blank(), \
        "one primitive list must drive both renderers"
