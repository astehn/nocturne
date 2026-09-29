import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QImage  # noqa: E402

from nocturne.ui.image_view import ImageView  # noqa: E402
from nocturne.ui.linked_views import copy_view, link_views  # noqa: E402


def _view(qtbot, w=400, h=300):
    v = ImageView()
    qtbot.addWidget(v)
    v.resize(200, 150)
    v.show()
    img = QImage(w, h, QImage.Format.Format_RGB888)
    img.fill(0x202020)
    v.set_image(img)
    return v


def test_zoom_and_pan_follow_both_ways(qtbot):
    a, b = _view(qtbot), _view(qtbot)
    link_views(a, b)
    a.actual_size()
    a.horizontalScrollBar().setValue(60)
    assert b.zoom() == pytest.approx(a.zoom())
    assert b.horizontalScrollBar().value() == 60
    b.zoom_in()
    b.verticalScrollBar().setValue(40)
    assert a.zoom() == pytest.approx(b.zoom())
    assert a.verticalScrollBar().value() == 40


def test_unlink_stops_following(qtbot):
    a, b = _view(qtbot), _view(qtbot)
    unlink = link_views(a, b)
    unlink()
    before = b.zoom()
    a.zoom_in()
    assert b.zoom() == before


def test_linking_twice_after_unlink_moves_once(qtbot):
    """[RF 4] Change crop + Upscale again relinks; one pan must not echo."""
    a, b = _view(qtbot), _view(qtbot)
    link_views(a, b)()
    link_views(a, b)
    a.actual_size()              # fitted, the scroll range is 0 and 30 cannot stick
    seen = []
    b.viewChanged.connect(lambda: seen.append(1))
    a.horizontalScrollBar().setValue(30)
    assert b.horizontalScrollBar().value() == 30
    assert len(seen) <= 2        # one scroll echo at most, not a loop


def test_copy_view_is_one_shot(qtbot):
    a, b = _view(qtbot), _view(qtbot)
    a.actual_size(); a.zoom_in()
    copy_view(a, b)
    assert b.zoom() == pytest.approx(a.zoom())
    a.zoom_in()
    assert b.zoom() != pytest.approx(a.zoom())
