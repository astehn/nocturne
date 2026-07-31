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
