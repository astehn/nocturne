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


def _send_move(view, pos):
    """Deliver a mouse-move to the viewport deterministically.

    qtbot.mouseMove is unreliable in this suite (see CLAUDE.md): whether the
    synthetic event arrives depends on exposure and on test ordering. Building
    the QMouseEvent and sending it removes both variables. The 4th argument is
    the button that CAUSED the event, the 5th is what is HELD."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    local = QPointF(pos)
    glob = QPointF(view.viewport().mapToGlobal(pos))
    ev = QMouseEvent(QEvent.Type.MouseMove, local, glob,
                     Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(view.viewport(), ev)


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
    # Built and sent directly, not via qtbot.mouseMove: that only delivered the
    # synthetic move under one particular full-suite ordering, so this test and
    # its sibling below passed or failed depending on what ran before them.
    # Adding an unrelated test file was enough to flip both.
    _send_move(view, view.viewport().rect().center())
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
    _send_move(view, QPoint(2, 2))
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
    # This is the whole guarantee for every surface that embeds ImageView without
    # opting into the gate — a crosshair there would promise a pixel reading that
    # does not exist, so the cursor must be left untouched, not merely "not a
    # crosshair": a future change could write some other shape over it and a
    # `!= CrossCursor` assertion would stay green. Capture the pre-hover shape and
    # assert it is unchanged, mirroring the fix to test_crop_mode_leaves_the_cursor_alone
    # in f1e3aa3.
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    before = view.viewport().cursor().shape()
    view._emit_hover_at_scene_pos(QPointF(5.0, 5.0))
    assert view.viewport().cursor().shape() == before


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
    # Crop mode's cursor (arrow/handles) must be untouched; if someone later
    # deleted the self._crop_mode guard from _apply_hover_cursor, thinking
    # _image_pixel_at already covers it, this test must fail by catching an
    # unwanted cursor write. Weak assertion (shape != CrossCursor) would pass
    # if the write changed it to OpenHandCursor instead.
    view = ImageView()
    qtbot.addWidget(view)
    view.set_pixel_cursor(True)
    view.set_image(_qimage(40, 30))
    view.set_crop_overlay(True)
    before = view.viewport().cursor().shape()
    view._emit_hover_at_scene_pos(QPointF(5.0, 5.0))
    assert view.viewport().cursor().shape() == before


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


def test_move_event_wiring_keeps_the_closed_hand_while_panning(qtbot):
    # test_panning_keeps_the_closed_hand calls _emit_hover_at_scene_pos(panning=True)
    # directly, which bypasses mouseMoveEvent's own `panning=bool(event.buttons())`
    # wiring entirely — a change to that call (e.g. narrowing it to
    # `== Qt.MouseButton.LeftButton`, or dropping the argument) would leave that
    # test green while every real pan flickered to a crosshair. Drive the real
    # mouseMoveEvent with a real button mask instead. Deliberately NOT
    # qtbot.mouseMove: the two tests above that use it are known-flaky (pass only
    # in full-suite ordering) — constructing and sending the event ourselves is
    # reliable.
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    view = ImageView()
    qtbot.addWidget(view)
    view.set_pixel_cursor(True)
    view.set_image(_qimage(40, 30))
    view.resize(400, 300)
    view.show()
    qtbot.waitExposed(view)

    pt = view.viewport().rect().center()
    assert view._image_pixel_at(view.mapToScene(pt)) is not None, (
        "test point must be over image pixels, not the letterbox margin")

    def send_move(buttons_held):
        ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(pt),
                         view.viewport().mapToGlobal(pt),
                         Qt.MouseButton.NoButton, buttons_held,
                         Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(view.viewport(), ev)

    # Stand in for Qt's own press handler, which sets this on button-down.
    view.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)

    send_move(Qt.MouseButton.LeftButton)  # move during a drag
    assert view.viewport().cursor().shape() == Qt.CursorShape.ClosedHandCursor

    # Proves the setup above is capable of changing the cursor at all, so the
    # ClosedHandCursor assertion isn't passing vacuously.
    send_move(Qt.MouseButton.NoButton)  # move with nothing held
    assert view.viewport().cursor().shape() == Qt.CursorShape.CrossCursor


def test_release_over_the_image_restores_the_crosshair(qtbot):
    # Qt's release handler sets OpenHandCursor; without the override the user is
    # left on an open hand over the image until they nudge the mouse.
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


def test_crosshair_shows_exactly_when_the_readout_pill_does(qtbot):
    # The invariant the design rests on: the crosshair means "there is a value for
    # this pixel", so it must appear precisely when the pill is showing one.
    view = ImageView()
    qtbot.addWidget(view)
    view.set_pixel_cursor(True)
    view.set_image(_qimage(40, 30))

    def hovering(scene_pos):
        """Hover, mirroring what main_window does with the signals."""
        shown = []
        view.hovered.connect(lambda x, y, side: shown.append(True))
        view.hoverLeft.connect(lambda: shown.append(False))
        view._emit_hover_at_scene_pos(scene_pos)
        view.hovered.disconnect()
        view.hoverLeft.disconnect()
        assert shown, f"no hover signal at {scene_pos}"
        if shown[-1]:
            view.readout_pill.show_text("5, 5")
        else:
            view.readout_pill.hide()
        crosshair = view.viewport().cursor().shape() == Qt.CursorShape.CrossCursor
        return not view.readout_pill.isHidden(), crosshair

    for pos in (QPointF(5.0, 5.0), QPointF(-20.0, -20.0), QPointF(39.9, 29.9),
                QPointF(40.0, 5.0), QPointF(-0.4, 5.0)):
        pill_visible, crosshair = hovering(pos)
        assert pill_visible == crosshair, f"disagreement at {pos}"


def test_object_list_panel_is_hidden_until_asked_for(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    assert view.object_panel.isHidden()
    view.show_object_list(True)
    assert not view.object_panel.isHidden()
    view.show_object_list(False)
    assert view.object_panel.isHidden()


def test_object_list_panel_is_tall_enough_to_be_useful(qtbot):
    """It moved out of the right column precisely because 180 px there showed
    two rows. On the canvas it must actually use the height available."""
    view = ImageView()
    qtbot.addWidget(view)
    view.resize(1200, 900)
    view.show_object_list(True)
    assert view.object_panel.height() >= 400, view.object_panel.height()
    # anchored top-right, below the Annotations pill
    assert view.object_panel.x() + view.object_panel.width() <= 1200
    assert view.object_panel.y() >= view.annotation_pill.y()


def test_object_list_rows_carry_the_catalogue_name(qtbot):
    from nocturne.core.catalog import CatalogObject
    view = ImageView()
    qtbot.addWidget(view)
    view.object_panel.set_contents(
        [CatalogObject("NGC 7000", "North America", 0, 0, 120.0, 1, 1),
         CatalogObject("LDN 935", "", 0, 0, 0.0, 2, 2)])
    assert view.object_panel.count() == 2
    assert "(2)" in view.object_panel.title.text()
    seen = []
    view.object_panel.objectActivated.connect(seen.append)
    view.object_panel._picked(view.object_panel.list.item(0))
    assert seen == ["NGC 7000"], "rows must carry the catalogue name, not display text"


def _star(name, mag, x=5.0, y=6.0):
    from nocturne.core.catalog import NamedStar
    return NamedStar(name, 0.0, 0.0, mag, x, y)


def test_named_stars_are_listed_after_the_deep_sky_objects(qtbot):
    """A star the overlay labels but the list omits is a dead end: you can read
    57 Cyg off the image and have nowhere to click."""
    from nocturne.core.catalog import CatalogObject
    view = ImageView()
    qtbot.addWidget(view)
    view.object_panel.set_contents(
        [CatalogObject("NGC 7000", "North America", 0, 0, 120.0, 1, 1)],
        [_star("56 Cyg", 5.1), _star("57 Cyg", 4.8)])

    rows = [view.object_panel.list.item(i).text()
            for i in range(view.object_panel.list.count())]
    names = [view.object_panel.list.item(i).data(Qt.ItemDataRole.UserRole)
             for i in range(view.object_panel.list.count())]
    assert "NGC 7000" in names and "56 Cyg" in names and "57 Cyg" in names
    # deep sky first, stars last -- a wide field of Bayer designations must never
    # bury the handful of objects that are the actual subject
    assert names.index("NGC 7000") < names.index("57 Cyg")
    # brightest star first (lower magnitude), not catalogue order
    assert names.index("57 Cyg") < names.index("56 Cyg")
    assert any("mag 4.8" in r for r in rows), rows
    assert "(3)" in view.object_panel.title.text()


def test_group_headings_are_not_clickable_rows(qtbot):
    from nocturne.core.catalog import CatalogObject
    view = ImageView()
    qtbot.addWidget(view)
    view.object_panel.set_contents(
        [CatalogObject("NGC 7000", "North America", 0, 0, 120.0, 1, 1)],
        [_star("56 Cyg", 5.1)])
    assert view.object_panel.list.count() == 4      # 2 headings + 2 objects
    assert view.object_panel.count() == 2, "headings are not objects"
    headings = [view.object_panel.list.item(i)
                for i in range(view.object_panel.list.count())
                if view.object_panel.list.item(i).data(Qt.ItemDataRole.UserRole) is None]
    assert len(headings) == 2
    for h in headings:
        assert h.flags() == Qt.ItemFlag.NoItemFlags, "a heading must not be selectable"
    # ...and picking one emits nothing rather than an empty name
    seen = []
    view.object_panel.objectActivated.connect(seen.append)
    view.object_panel._picked(headings[0])
    assert seen == []


def test_no_headings_when_only_one_group_is_present(qtbot):
    """Headings earn their row only when they separate something."""
    from nocturne.core.catalog import CatalogObject
    view = ImageView()
    qtbot.addWidget(view)
    view.object_panel.set_contents(
        [CatalogObject("NGC 7000", "North America", 0, 0, 120.0, 1, 1)], [])
    assert view.object_panel.list.count() == 1

    view.object_panel.set_contents([], [_star("56 Cyg", 5.1)])
    assert view.object_panel.list.count() == 1
    assert view.object_panel.count() == 1


# --- staying fitted across a resize ------------------------------------------
# fit() ran only from set_image(), so any dialog that set its image during
# __init__ locked in a fit measured against the pre-layout viewport.

def test_a_fitted_view_refits_when_the_widget_resizes(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.resize(200, 150)
    view.show()
    qtbot.waitExposed(view)
    view.set_image(_qimage(400, 300))
    small = view.transform().m11()

    view.resize(800, 600)                      # the dialog gets its real size
    qtbot.waitUntil(lambda: view.transform().m11() != small, timeout=1000)
    assert view.transform().m11() > small, "a bigger viewport must show a bigger image"
    assert view._fitted


def test_a_deliberate_zoom_survives_a_resize(qtbot):
    """The whole reason this is gated. Resizing the window while zoomed to 100%
    must not yank the user back out to fit."""
    view = ImageView()
    qtbot.addWidget(view)
    view.resize(400, 300)
    view.show()
    qtbot.waitExposed(view)
    view.set_image(_qimage(40, 30))

    view.zoom_in()
    assert not view._fitted
    zoomed = view.transform().m11()

    view.resize(700, 500)
    qtbot.wait(50)
    # The requirement is "the zoom was not thrown away", not "the float is
    # bit-identical". Exact equality on a transform after a resize made this
    # order-dependent in the full suite; re-fitting a 40x30 image into a 700x500
    # viewport would land near 12x, nowhere near this tolerance.
    assert view.transform().m11() == pytest.approx(zoomed, rel=0.02), \
        "the resize threw away the user's zoom"


def test_actual_size_and_zoom_out_also_clear_the_fitted_flag(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(40, 30))
    assert view._fitted
    view.actual_size()
    assert not view._fitted

    view.fit()
    assert view._fitted
    view.zoom_out()
    assert not view._fitted


def test_focus_on_clears_fitted_only_when_it_actually_zooms(qtbot):
    """focus_on centres, and zooms only if below min_scale. Centring alone is not
    a deliberate zoom, so it must not disable staying-fitted."""
    view = ImageView()
    qtbot.addWidget(view)
    view.resize(400, 300)
    view.show()
    qtbot.waitExposed(view)
    view.set_image(_qimage(40, 30))
    view.fit()

    view.focus_on(20, 15, min_scale=0.0)       # no zoom needed
    assert view._fitted, "centring without zooming must leave the view fitted"

    view.focus_on(20, 15, min_scale=999.0)     # forces a zoom
    assert not view._fitted


def test_resizing_without_an_image_does_not_raise(qtbot):
    """_fitted is read in resizeEvent, which Qt delivers during construction —
    before any image exists."""
    view = ImageView()
    qtbot.addWidget(view)
    view.resize(500, 400)
    view.show()
    qtbot.waitExposed(view)
    view.resize(600, 500)                      # must not raise
