import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from nocturne.ui.upscale_navigator import UpscaleNavigator  # noqa: E402


def _nav(qtbot):
    n = UpscaleNavigator()
    qtbot.addWidget(n)
    n.resize(200, 100)
    n.show()
    img = QImage(400, 200, QImage.Format.Format_RGB888)
    img.fill(0)
    n.set_frame(img)
    n.set_crop((50, 150, 100, 300), 2)          # a 200x100 crop -> 400x200 result
    return n


def test_the_crop_is_drawn_where_it_is(qtbot):
    r = _nav(qtbot).crop_rect_on_widget()
    assert (r.left(), r.top(), r.width(), r.height()) == pytest.approx((50, 25, 100, 50))


def test_the_visible_part_sits_inside_the_crop(qtbot):
    n = _nav(qtbot)
    n.set_visible_rect(0, 0, 200, 100)          # the left-top quarter of the result
    r = n.visible_rect_on_widget()
    assert (r.left(), r.top(), r.width(), r.height()) == pytest.approx((50, 25, 50, 25))


def test_a_click_asks_for_that_spot_in_result_pixels(qtbot):
    n = _nav(qtbot)
    got = []
    n.centreRequested.connect(lambda x, y: got.append((x, y)))
    pos = QPointF(100, 50)                      # centre of the crop on the widget
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, pos, n.mapToGlobal(pos.toPoint()),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(n, ev)
    assert got == [pytest.approx((200.0, 100.0))]


def test_no_crop_means_the_whole_frame(qtbot):
    n = _nav(qtbot)
    n.set_crop(None, 2)                          # [RF 1]
    r = n.crop_rect_on_widget()
    assert (r.width(), r.height()) == pytest.approx((200, 100))


def test_a_small_frame_keeps_the_full_frame_geometry(qtbot):
    """[final 8] The navigator draws a reduced copy; its geometry is the frame's."""
    n = UpscaleNavigator()
    qtbot.addWidget(n)
    n.resize(200, 100)
    small = QImage(100, 50, QImage.Format.Format_RGB888)
    small.fill(0)
    n.set_frame(small, full_size=(400, 200))
    n.set_crop((50, 150, 100, 300), 2)
    r = n.crop_rect_on_widget()
    assert (r.left(), r.top(), r.width(), r.height()) == pytest.approx((50, 25, 100, 50))
