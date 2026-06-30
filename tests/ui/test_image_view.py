import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QImage  # noqa: E402
from seestar_processor.ui.image_view import ImageView  # noqa: E402


def _qimage(w=20, h=10):
    arr = (np.random.rand(h, w, 3) * 255).astype(np.uint8)
    arr = np.ascontiguousarray(arr)
    return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def test_set_image_populates_pixmap(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    assert view._item.pixmap().isNull()
    view.set_image(_qimage())
    assert not view._item.pixmap().isNull()
    assert view._item.pixmap().width() == 20


def test_fit_and_actual_size_do_not_raise(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage())
    view.fit()
    view.actual_size()


def test_crop_overlay_roundtrips_bounds(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.set_crop_overlay(True, bounds=(5, 25, 8, 35))
    assert view.crop_bounds() == (5, 25, 8, 35)


def test_crop_overlay_move_updates_bounds(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.set_crop_overlay(True, bounds=(0, 10, 0, 10))
    view._body.setPos(5, 5)  # move the box by (5,5)
    assert view.crop_bounds() == (5, 15, 5, 15)


def test_crop_overlay_disable_clears_box(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.set_crop_overlay(True, bounds=(0, 10, 0, 10))
    view.set_crop_overlay(False)
    assert view._body is None
