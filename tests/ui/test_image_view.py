import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from nocturne.ui.image_view import ImageView  # noqa: E402


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


def test_crop_box_hidden_until_shown(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(200, 100))
    view.set_crop_overlay(True, content_bounds=(10, 90, 20, 180))
    assert view.crop_box_visible() is False   # crop mode on, box not drawn
    view.show_crop_box()
    assert view.crop_box_visible() is True
    assert view.crop_bounds() == (10, 90, 20, 180)   # shown at stored content bounds
    view.hide_crop_box()
    assert view.crop_box_visible() is False
    assert view._crop_mode is True            # still in crop mode after hiding


def test_crop_box_modified_tracks_user_changes(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(200, 100))
    view.set_crop_overlay(True, content_bounds=(10, 90, 20, 180))
    view.show_crop_box()
    assert view.crop_box_modified() is False   # fresh box at content edges
    view._geometry_changed()                   # simulate a user move/resize
    assert view.crop_box_modified() is True
    view.hide_crop_box()
    view.show_crop_box()                        # re-showing resets it
    assert view.crop_box_modified() is False


def test_dismiss_requested_on_escape_when_box_visible(qtbot):
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent, Qt
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(200, 100))
    view.set_crop_overlay(True, content_bounds=(10, 90, 20, 180))
    view.show_crop_box()
    with qtbot.waitSignal(view.cropDismissRequested, timeout=500):
        view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                     Qt.KeyboardModifier.NoModifier))


def test_show_crop_box_emits_signal(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(200, 100))
    view.set_crop_overlay(True, content_bounds=(10, 90, 20, 180))
    with qtbot.waitSignal(view.cropBoxShown, timeout=500):
        view.show_crop_box()


def test_show_crop_box_is_idempotent(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(200, 100))
    view.set_crop_overlay(True, content_bounds=(10, 90, 20, 180))
    view.show_crop_box()
    body = view._body
    view.show_crop_box()  # second call is a no-op, does not rebuild the box
    assert view._body is body
    assert len(view._handles) == 8


def test_show_crop_box_falls_back_to_full_pixmap(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(200, 100))
    view.set_crop_overlay(True)  # no content bounds
    view.show_crop_box()
    assert view.crop_bounds() == (0, 100, 0, 200)


def test_crop_overlay_roundtrips_bounds(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.set_crop_overlay(True, content_bounds=(5, 25, 8, 35))
    view.show_crop_box()
    assert view.crop_bounds() == (5, 25, 8, 35)


def test_crop_overlay_move_updates_bounds(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.set_crop_overlay(True, content_bounds=(0, 10, 0, 10))
    view.show_crop_box()
    view._body.setPos(5, 5)  # move the box by (5,5)
    assert view.crop_bounds() == (5, 15, 5, 15)


def test_crop_overlay_disable_clears_box(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.set_crop_overlay(True, content_bounds=(0, 10, 0, 10))
    view.show_crop_box()
    view.set_crop_overlay(False)
    assert view._body is None


def test_crop_overlay_has_eight_handles(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.set_crop_overlay(True, content_bounds=(0, 20, 0, 20))
    view.show_crop_box()
    assert len(view._handles) == 8


def test_apply_aspect_reshapes_box_to_ratio(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(100, 100))
    view.set_crop_overlay(True, content_bounds=(0, 80, 0, 80))  # 80x80 square box
    view.show_crop_box()
    view.apply_aspect(2.0)  # width:height = 2:1
    top, bottom, left, right = view.crop_bounds()
    w, h = right - left, bottom - top
    assert abs(w / h - 2.0) < 0.05


def test_set_guides_and_draw(qtbot):
    from PySide6.QtGui import QImage, QPainter
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(200, 100))
    view.set_crop_overlay(True, content_bounds=(0, 100, 0, 200))
    view.show_crop_box()
    for kind in ("none", "thirds", "center"):
        view.set_guides(kind)
        assert view._guides == kind
        img = QImage(50, 50, QImage.Format.Format_ARGB32)
        p = QPainter(img)
        view.drawForeground(p, view.sceneRect())  # must not raise
        p.end()


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


def test_zoom_in_out_change_scale(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.resize(300, 200)
    view.set_image(_qimage())
    before = view.transform().m11()
    view.zoom_in()
    assert view.transform().m11() > before
    mid = view.transform().m11()
    view.zoom_out()
    assert view.transform().m11() < mid


def test_zoom_noop_without_image(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    # no image -> zoom does nothing, no crash
    view.zoom_in()
    view.zoom_out()


def test_zoom_pill_hidden_during_crop(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.set_crop_overlay(True)
    # isHidden() tracks the explicit hide flag (isVisible needs a shown parent)
    assert view._zoom_pill.isHidden() is True    # hidden so it can't block a crop handle
    view.set_crop_overlay(False)
    assert view._zoom_pill.isHidden() is False    # restored when cropping ends


def _cropped_view(qtbot, w=200, h=100, bounds=(10, 90, 20, 180)):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(w, h))
    view.set_crop_overlay(True, content_bounds=bounds)
    view.show_crop_box()
    return view


def _in_bounds(r, W, H, eps=0.01):
    return (r.left() >= -eps and r.top() >= -eps
            and r.right() <= W + eps and r.bottom() <= H + eps)


def test_resize_clamps_free_crop_inside_image(qtbot):
    view = _cropped_view(qtbot)
    view._resize_to("br", QPointF(500, 500))     # drag bottom-right far outside
    assert _in_bounds(view._scene_rect(), 200, 100)


def test_resize_clamps_top_left_past_origin(qtbot):
    view = _cropped_view(qtbot)
    view._resize_to("tl", QPointF(-300, -300))   # drag top-left past (0,0)
    assert _in_bounds(view._scene_rect(), 200, 100)


def test_resize_aspect_stays_in_bounds_and_keeps_ratio(qtbot):
    view = _cropped_view(qtbot)
    view.set_aspect(2.0)                           # width = 2 x height
    view._resize_to("br", QPointF(500, 500))
    r = view._scene_rect()
    assert _in_bounds(r, 200, 100)
    assert abs(r.width() / r.height() - 2.0) < 0.05   # ratio preserved


def test_resize_inside_is_unaffected(qtbot):
    view = _cropped_view(qtbot)
    view._resize_to("br", QPointF(150, 80))        # fully inside
    r = view._scene_rect()
    assert abs(r.left() - 20) < 0.01 and abs(r.top() - 10) < 0.01
    assert abs(r.right() - 150) < 0.01 and abs(r.bottom() - 80) < 0.01


def test_resize_aspect_top_left_anchors_bottom_right(qtbot):
    # A top-left aspect drag must keep the OPPOSITE corner (bottom-right) fixed,
    # stay in bounds, and preserve the ratio. (Old code re-derived the bottom edge
    # from the dragged top-y and could even leave the image; new code anchors right.)
    view = _cropped_view(qtbot)
    view.set_aspect(2.0)
    r0 = view._scene_rect()
    br = (r0.right(), r0.bottom())
    view._resize_to("tl", QPointF(60, 40))
    r = view._scene_rect()
    assert _in_bounds(r, 200, 100)
    assert abs(r.width() / r.height() - 2.0) < 0.05
    assert abs(r.right() - br[0]) < 0.01 and abs(r.bottom() - br[1]) < 0.01


def test_resize_aspect_top_right_anchors_bottom_left(qtbot):
    view = _cropped_view(qtbot)
    view.set_aspect(2.0)
    r0 = view._scene_rect()
    bl = (r0.left(), r0.bottom())
    view._resize_to("tr", QPointF(140, 40))
    r = view._scene_rect()
    assert _in_bounds(r, 200, 100)
    assert abs(r.width() / r.height() - 2.0) < 0.05
    assert abs(r.left() - bl[0]) < 0.01 and abs(r.bottom() - bl[1]) < 0.01


def test_move_clamps_box_inside_keeping_size(qtbot):
    view = _cropped_view(qtbot, bounds=(10, 60, 20, 120))   # box 100 wide x 50 tall
    before = view._scene_rect()
    view._body.setPos(QPointF(500, 500))                    # shove it far out
    after = view._scene_rect()
    assert _in_bounds(after, 200, 100)
    assert abs(after.width() - before.width()) < 0.01       # slid, not shrunk
    assert abs(after.height() - before.height()) < 0.01


def test_move_inside_is_unaffected(qtbot):
    view = _cropped_view(qtbot, bounds=(10, 60, 20, 120))
    view._body.setPos(QPointF(15, 5))                       # small in-bounds nudge
    r = view._scene_rect()
    assert abs(r.left() - 35) < 0.01 and abs(r.top() - 15) < 0.01   # 20+15, 10+5


def test_mouse_move_emits_image_pixel_coordinates(qtbot):
    from PySide6.QtCore import QPoint
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.resize(400, 300)
    view.show()
    qtbot.waitExposed(view)
    seen = []
    view.hovered.connect(lambda x, y, side: seen.append((x, y, side)))
    centre = view.viewport().rect().center()
    qtbot.mouseMove(view.viewport(), centre)
    assert seen, "moving over the image should emit hovered"
    x, y, side = seen[-1]
    assert 0 <= x < 40 and 0 <= y < 30
    assert side == "main"


def test_mouse_move_outside_the_image_emits_hover_left(qtbot):
    from PySide6.QtCore import QPoint
    view = ImageView()
    qtbot.addWidget(view)
    # Resize/show/expose *before* set_image: fit() reads the viewport's current
    # size, and QAbstractScrollArea only applies a resize() to the viewport
    # lazily once the widget is actually shown — calling set_image() first would
    # fit against the stale pre-show viewport size and defeat the letterboxing
    # this test relies on.
    view.resize(400, 300)
    view.show()
    qtbot.waitExposed(view)
    view.set_image(_qimage(10, 10))
    left = []
    view.hoverLeft.connect(lambda: left.append(True))
    # With the corrected order above, fit() sizes the 10x10 image to the real
    # 400x300 viewport, leaving a genuine letterboxed margin outside it —
    # (2, 2) falls in that margin (off-image).
    qtbot.mouseMove(view.viewport(), QPoint(2, 2))
    assert left


def test_hover_reports_the_compare_side_left_of_the_divider(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.set_compare(_qimage(40, 30))
    sides = []
    view.hovered.connect(lambda x, y, side: sides.append(side))
    # The divider defaults to the horizontal midpoint (x = 20).
    view._emit_hover_at_scene_pos(QPointF(5.0, 5.0))
    view._emit_hover_at_scene_pos(QPointF(35.0, 5.0))
    assert sides == ["compare", "main"]


def test_hover_side_is_main_when_compare_is_off(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    sides = []
    view.hovered.connect(lambda x, y, side: sides.append(side))
    view._emit_hover_at_scene_pos(QPointF(5.0, 5.0))
    assert sides == ["main"]


def test_hover_sub_pixel_negative_band_emits_hover_left(qtbot):
    # int() truncates toward zero, so scene coordinates in (-1, 0) would
    # falsely floor to pixel 0 instead of being treated as off-image. A true
    # floor is required: (-0.5, 5.0) is left of the image, (5.0, -0.5) is
    # above it — both must report hoverLeft, never a clamped hovered(0, ...).
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    seen = []
    left = []
    view.hovered.connect(lambda x, y, side: seen.append((x, y, side)))
    view.hoverLeft.connect(lambda: left.append(True))
    view._emit_hover_at_scene_pos(QPointF(-0.5, 5.0))
    view._emit_hover_at_scene_pos(QPointF(5.0, -0.5))
    assert left == [True, True]
    assert seen == []


def test_view_owns_a_readout_pill_hidden_by_default(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    assert view.readout_pill.isHidden()


def test_readout_pill_hides_when_crop_mode_turns_on(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.readout_pill.show_text("something")
    view.set_crop_overlay(True)
    assert view.readout_pill.isHidden()


def test_image_pixel_at_returns_the_pixel_under_a_scene_position(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    assert view._image_pixel_at(QPointF(5.7, 9.2)) == (5, 9)


def test_image_pixel_at_floors_rather_than_truncating(qtbot):
    # int() truncates toward zero, so a scene x in (-1, 0) would become pixel 0 —
    # reporting a value for a position that is off the image. See commit 6e97aa3.
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    assert view._image_pixel_at(QPointF(-0.4, 5.0)) is None
    assert view._image_pixel_at(QPointF(5.0, -0.4)) is None


def test_image_pixel_at_is_none_outside_the_image(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    assert view._image_pixel_at(QPointF(40.0, 5.0)) is None
    assert view._image_pixel_at(QPointF(5.0, 30.0)) is None
    assert view._image_pixel_at(QPointF(39.9, 29.9)) == (39, 29)


def test_image_pixel_at_is_none_with_no_image(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    assert view._image_pixel_at(QPointF(1.0, 1.0)) is None


def test_image_pixel_at_is_none_in_crop_mode(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view.set_crop_overlay(True)
    assert view._image_pixel_at(QPointF(5.0, 5.0)) is None


def test_pixel_cursor_is_off_by_default(qtbot):
    # The Share/Upscale/Star-Spikes previews embed ImageView but wire up no
    # readout, so a crosshair there would promise a reading that does not exist.
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    view._emit_hover_at_scene_pos(QPointF(5.0, 5.0))
    assert view.viewport().cursor().shape() != Qt.CursorShape.CrossCursor


def test_crosshair_shows_over_image_pixels(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_pixel_cursor(True)
    view.set_image(_qimage(40, 30))
    view._emit_hover_at_scene_pos(QPointF(5.0, 5.0))
    assert view.viewport().cursor().shape() == Qt.CursorShape.CrossCursor


def test_open_hand_shows_over_the_letterbox_margin(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_pixel_cursor(True)
    view.set_image(_qimage(40, 30))
    view._emit_hover_at_scene_pos(QPointF(5.0, 5.0))       # on the image first
    view._emit_hover_at_scene_pos(QPointF(-20.0, -20.0))   # then the margin
    assert view.viewport().cursor().shape() == Qt.CursorShape.OpenHandCursor


def test_crop_mode_leaves_the_cursor_alone(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_pixel_cursor(True)
    view.set_image(_qimage(40, 30))
    view.set_crop_overlay(True)
    view._emit_hover_at_scene_pos(QPointF(5.0, 5.0))
    assert view.viewport().cursor().shape() != Qt.CursorShape.CrossCursor


def test_panning_keeps_the_closed_hand(qtbot):
    # Qt sets ClosedHandCursor on press; a crosshair applied mid-drag would wipe
    # out the only feedback that a pan is in progress.
    view = ImageView()
    qtbot.addWidget(view)
    view.set_pixel_cursor(True)
    view.set_image(_qimage(40, 30))
    view.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
    view._emit_hover_at_scene_pos(QPointF(5.0, 5.0), panning=True)
    assert view.viewport().cursor().shape() == Qt.CursorShape.ClosedHandCursor


def test_release_over_the_image_restores_the_crosshair(qtbot):
    # Qt's release handler sets OpenHandCursor; without the override the user is
    # left on an open hand over the image until they nudge the mouse.
    from PySide6.QtCore import QPoint
    view = ImageView()
    qtbot.addWidget(view)
    view.set_pixel_cursor(True)
    view.set_image(_qimage(40, 30))
    view.resize(400, 300)
    view.show()
    qtbot.waitExposed(view)
    centre = view.viewport().rect().center()
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=centre)
    assert view.viewport().cursor().shape() == Qt.CursorShape.CrossCursor


def test_redundant_cursor_writes_are_skipped(qtbot):
    # _apply_hover_cursor runs on every mouse-move event; setting an unchanged
    # shape thousands of times a second is pure waste.
    view = ImageView()
    qtbot.addWidget(view)
    view.set_pixel_cursor(True)
    view.set_image(_qimage(40, 30))
    calls = []
    original = view.viewport().setCursor
    view.viewport().setCursor = lambda shape: (calls.append(shape), original(shape))[1]
    view._emit_hover_at_scene_pos(QPointF(5.0, 5.0))
    view._emit_hover_at_scene_pos(QPointF(6.0, 6.0))
    view._emit_hover_at_scene_pos(QPointF(7.0, 7.0))
    view.viewport().setCursor = original
    assert len(calls) == 1
