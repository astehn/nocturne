"""Trackpad pan/pinch vs mouse-wheel zoom, in both preview widgets.

Every event here is constructed and sent straight to the widget, per CLAUDE.md:
this terminal cannot drive a real trackpad. What these tests prove is the
mapping from event to behaviour; whether it FEELS right is judged on a MacBook.
"""
import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QImage, QInputDevice, QNativeGestureEvent, QPointingDevice, QWheelEvent,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from nocturne.ui.curves_dialog import _ZoomPreview  # noqa: E402
from nocturne.ui.image_view import _MAX_ZOOM, ImageView  # noqa: E402
from nocturne.ui.scroll_input import is_trackpad_scroll  # noqa: E402

_TOUCHPAD = QPointingDevice(
    "test trackpad", 9001, QInputDevice.DeviceType.TouchPad,
    QPointingDevice.PointerType.Finger, QInputDevice.Capability.Position, 5, 0)

_NO_BTN = Qt.MouseButton.NoButton
_NO_MOD = Qt.KeyboardModifier.NoModifier


def _qimage(w=400, h=300):
    rng = np.random.default_rng(0)
    arr = np.ascontiguousarray((rng.random((h, w, 3)) * 255).astype(np.uint8))
    return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def _swipe_event(pos, dx, dy, phase=Qt.ScrollPhase.ScrollUpdate):
    """One event of a two-finger swipe, as macOS sends it: pixel AND angle
    deltas, a phase, and the core pointer as device (Qt on macOS does not
    necessarily tag the trackpad), so the PHASE alone has to identify it."""
    return QWheelEvent(QPointF(pos), QPointF(pos), QPoint(dx, dy),
                       QPoint(dx * 3, dy * 3), _NO_BTN, _NO_MOD, phase, False)


def _wheel_event(pos, angle_y):
    """A classic mouse wheel: no phase, no pixel delta."""
    return QWheelEvent(QPointF(pos), QPointF(pos), QPoint(0, 0),
                       QPoint(0, angle_y), _NO_BTN, _NO_MOD,
                       Qt.ScrollPhase.NoScrollPhase, False)


def _pinch_event(pos, value, kind=Qt.NativeGestureType.ZoomNativeGesture):
    return QNativeGestureEvent(kind, _TOUCHPAD, 2, QPointF(pos), QPointF(pos),
                               QPointF(pos), value, QPointF(), 0)


def _send(widget, event) -> None:
    QApplication.sendEvent(widget, event)


def _swipe(widget, pos, dx, dy, n=40) -> None:
    """A whole gesture: begin, n updates, end — dozens of events, the stream
    that used to fire dozens of zoom steps."""
    _send(widget, _swipe_event(pos, 0, 0, Qt.ScrollPhase.ScrollBegin))
    for _ in range(n):
        _send(widget, _swipe_event(pos, dx, dy))
    _send(widget, _swipe_event(pos, 0, 0, Qt.ScrollPhase.ScrollEnd))


def _view(qtbot, zoom=2.0) -> ImageView:
    view = ImageView()
    qtbot.addWidget(view)
    view.resize(300, 200)
    view.show()
    view.set_image(_qimage())
    view.actual_size()
    view.scale(zoom, zoom)
    view.centerOn(200, 150)
    return view


def _centre_scene(view) -> QPointF:
    return view.mapToScene(view.viewport().rect().center())


# --- classification ----------------------------------------------------------

def test_a_phased_scroll_is_a_trackpad_and_a_detent_wheel_is_not():
    pos = QPointF(10, 10)
    assert is_trackpad_scroll(_swipe_event(pos, 1, 1))
    assert is_trackpad_scroll(_swipe_event(pos, 0, 0, Qt.ScrollPhase.ScrollMomentum))
    assert not is_trackpad_scroll(_wheel_event(pos, 120))


def test_a_touchpad_device_counts_even_without_a_phase():
    e = QWheelEvent(QPointF(1, 1), QPointF(1, 1), QPoint(0, 5), QPoint(0, 15),
                    _NO_BTN, _NO_MOD, Qt.ScrollPhase.NoScrollPhase, False,
                    Qt.MouseEventSource.MouseEventNotSynthesized, _TOUCHPAD)
    assert is_trackpad_scroll(e)


# --- ImageView: two-finger swipe pans ----------------------------------------

def test_a_swipe_does_not_zoom(qtbot):
    """The defect: one swipe fired a x1.25 step per event. Now it must leave
    the zoom exactly where it was."""
    view = _view(qtbot)
    before = view.zoom()
    _swipe(view.viewport(), QPoint(150, 100), 0, -3)
    assert view.zoom() == before


def test_a_swipe_pans_with_the_fingers(qtbot):
    """Fingers move up (negative pixel delta) -> the picture moves up -> the
    view now shows content further DOWN the image. Horizontal likewise."""
    view = _view(qtbot)
    start = _centre_scene(view)
    _swipe(view.viewport(), QPoint(150, 100), 0, -2, n=10)
    moved = _centre_scene(view)
    # 20 screen px at 2x zoom = 10 image px
    assert moved.y() == pytest.approx(start.y() + 10, abs=0.6)
    assert moved.x() == pytest.approx(start.x(), abs=0.6)

    _swipe(view.viewport(), QPoint(150, 100), -2, 0, n=10)
    assert _centre_scene(view).x() == pytest.approx(start.x() + 10, abs=0.6)


def test_momentum_events_keep_panning(qtbot):
    """After the fingers lift macOS sends momentum-phase events; they are part
    of the same pan, not a wheel."""
    view = _view(qtbot)
    before_zoom = view.zoom()
    start = _centre_scene(view)
    for _ in range(5):
        _send(view.viewport(), _swipe_event(QPoint(150, 100), 0, -2,
                                            Qt.ScrollPhase.ScrollMomentum))
    assert view.zoom() == before_zoom
    assert _centre_scene(view).y() > start.y()


def test_a_swipe_in_crop_mode_pans_and_leaves_the_box_alone(qtbot):
    """Two-finger scroll uses no mouse button, so it cannot fight the crop
    box's drag. Capture the bounds first and assert they are UNCHANGED."""
    view = _view(qtbot)
    view.set_crop_overlay(True, content_bounds=(20, 280, 30, 370))
    view.show_crop_box()
    bounds = view.crop_bounds()
    start = _centre_scene(view)
    _swipe(view.viewport(), QPoint(150, 100), 0, -2, n=10)
    assert view.crop_bounds() == bounds
    assert _centre_scene(view).y() > start.y()


# --- ImageView: the mouse wheel still zooms, by how far it turned -------------

def test_one_wheel_detent_is_still_one_x1_25_step(qtbot):
    """Desktop behaviour must not change: one click, x1.25, as before."""
    view = _view(qtbot, zoom=1.0)
    _send(view.viewport(), _wheel_event(QPoint(150, 100), 120))
    assert view.zoom() == pytest.approx(1.25)
    _send(view.viewport(), _wheel_event(QPoint(150, 100), -120))
    assert view.zoom() == pytest.approx(1.0)


def test_a_fine_wheel_turns_a_fraction_of_a_step(qtbot):
    """The old handler read only the sign, so a high-resolution wheel's 1/4
    detent zoomed a full step. Now it zooms a quarter of one."""
    view = _view(qtbot, zoom=1.0)
    _send(view.viewport(), _wheel_event(QPoint(150, 100), 30))
    assert view.zoom() == pytest.approx(1.25 ** 0.25)


def test_the_wheel_stops_at_the_ceiling(qtbot):
    view = _view(qtbot, zoom=1.0)
    for _ in range(40):
        _send(view.viewport(), _wheel_event(QPoint(150, 100), 120))
    assert view.zoom() == pytest.approx(_MAX_ZOOM)


# --- ImageView: pinch zooms about the fingers --------------------------------

def test_pinch_zooms_by_the_gesture_value(qtbot):
    view = _view(qtbot, zoom=1.0)
    _send(view.viewport(), _pinch_event(QPoint(150, 100), 0.1))
    assert view.zoom() == pytest.approx(1.1)
    _send(view.viewport(), _pinch_event(QPoint(150, 100), -0.1))
    assert view.zoom() == pytest.approx(1.1 * 0.9)


def test_pinch_keeps_the_point_under_the_fingers_still(qtbot):
    """Zoom about the CURSOR, not the view centre: the image pixel under the
    fingers stays under them. Off-centre on purpose, where the two differ."""
    view = _view(qtbot, zoom=1.0)
    at = QPoint(60, 40)
    anchor = view.mapToScene(at)
    for _ in range(5):
        _send(view.viewport(), _pinch_event(at, 0.2))
    assert view.zoom() > 2.0
    after = view.mapToScene(at)
    assert after.x() == pytest.approx(anchor.x(), abs=1.0)
    assert after.y() == pytest.approx(anchor.y(), abs=1.0)


def test_pinch_stops_at_the_ceiling_and_the_floor(qtbot):
    view = _view(qtbot, zoom=1.0)
    for _ in range(200):
        _send(view.viewport(), _pinch_event(QPoint(150, 100), 0.5))
    assert view.zoom() == pytest.approx(_MAX_ZOOM)
    view.fit()
    fitted = view.zoom()
    for _ in range(200):
        _send(view.viewport(), _pinch_event(QPoint(150, 100), -0.5))
    # fitInView leaves Qt's small margin, so 'half the fit' is approximate
    assert view.zoom() == pytest.approx(fitted * 0.5, rel=0.05)
    assert view.zoom() > 0


def test_pinch_is_a_deliberate_zoom_that_survives_a_resize(qtbot):
    view = _view(qtbot, zoom=1.0)
    view.fit()
    _send(view.viewport(), _pinch_event(QPoint(150, 100), 0.3))
    assert view._fitted is False


def test_smart_zoom_toggles_fit_and_actual_size(qtbot):
    view = _view(qtbot, zoom=1.0)
    view.fit()
    assert view.zoom() != pytest.approx(1.0)       # the fixture is not 1:1 at fit
    smart = Qt.NativeGestureType.SmartZoomNativeGesture
    _send(view.viewport(), _pinch_event(QPoint(150, 100), 0.0, smart))
    assert view.zoom() == pytest.approx(1.0)
    _send(view.viewport(), _pinch_event(QPoint(150, 100), 0.0, smart))
    assert view._fitted is True


def test_gestures_without_an_image_do_nothing(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.resize(300, 200)
    before = view.transform()
    _send(view.viewport(), _pinch_event(QPoint(150, 100), 0.3))
    _send(view.viewport(), _wheel_event(QPoint(150, 100), 120))
    _swipe(view.viewport(), QPoint(150, 100), 0, -3)
    assert view.transform() == before


# --- _ZoomPreview (Curves, and every side-by-side compare) --------------------

def _preview(qtbot) -> _ZoomPreview:
    p = _ZoomPreview()
    qtbot.addWidget(p)
    p.resize(300, 200)
    p.set_zoom(4.0)
    return p


def test_preview_swipe_pans_and_does_not_zoom(qtbot):
    """Its wheel handler did scale by the delta, so a swipe was not the
    runaway zoom — but it still zoomed where a Mac user expects a pan."""
    p = _preview(qtbot)
    start = list(p._centre)
    _swipe(p, QPoint(150, 100), 0, -3, n=10)
    assert p.zoom_level() == 4.0
    assert p._centre[1] > start[1]            # fingers up -> see further down
    assert p._centre[0] == pytest.approx(start[0])


def test_preview_swipe_moves_the_same_distance_as_a_drag(qtbot):
    """One screen pixel of swipe and one of drag are one screen pixel of
    picture: the swipe reuses the drag's scaling, so the two agree."""
    p = _preview(qtbot)
    start = p._centre[1]
    _swipe(p, QPoint(150, 100), 0, -1, n=20)          # 20 px up
    assert p._centre[1] - start == pytest.approx(20 / 200 / 4.0)


def test_preview_wheel_still_zooms(qtbot):
    p = _preview(qtbot)
    _send(p, _wheel_event(QPoint(150, 100), 120))
    assert p.zoom_level() > 4.0


def test_preview_pinch_zooms(qtbot):
    p = _preview(qtbot)
    _send(p, _pinch_event(QPoint(150, 100), 0.25))
    assert p.zoom_level() == pytest.approx(5.0)


def test_pinch_on_one_side_by_side_pane_moves_the_other(qtbot):
    """The compare view's one hard requirement — one shared pan/zoom — has to
    hold for the new inputs too, not only for the wheel it was built with."""
    from nocturne.ui.compare_view import CompareView
    w = CompareView()
    qtbot.addWidget(w)
    w.resize(800, 400)
    w.set_mode("side")
    img = _qimage(60, 40)
    w.set_images(img, img)
    _send(w._before_pane, _pinch_event(QPoint(50, 50), 0.5))
    assert w._before_pane.zoom_level() == pytest.approx(1.5)
    assert w._after_pane.zoom_level() == pytest.approx(1.5)
    _swipe(w._before_pane, QPoint(50, 50), 0, -3, n=10)
    assert w._after_pane._centre == pytest.approx(w._before_pane._centre)
