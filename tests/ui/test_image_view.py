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


def test_crop_overlay_has_eight_handles(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.set_crop_overlay(True, bounds=(0, 20, 0, 20))
    assert len(view._handles) == 8


def test_apply_aspect_reshapes_box_to_ratio(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(100, 100))
    view.set_crop_overlay(True, bounds=(0, 80, 0, 80))  # 80x80 square box
    view.apply_aspect(2.0)  # width:height = 2:1
    top, bottom, left, right = view.crop_bounds()
    w, h = right - left, bottom - top
    assert abs(w / h - 2.0) < 0.05


def test_compare_mode_sets_and_clears(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.set_compare(_qimage(40, 30))
    assert view.compare_active() is True
    view.set_compare(None)
    assert view.compare_active() is False


def test_compare_divider_clamps_split(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.set_compare(_qimage(40, 30))
    view._on_divider(10.0)
    assert view._split_x == 10.0


def test_set_image_refits_when_size_changes(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.scale(4, 4)  # zoom in
    before = view.transform().m11()
    view.set_image(_qimage(20, 15))  # different size -> should re-fit
    after = view.transform().m11()
    assert after != before
