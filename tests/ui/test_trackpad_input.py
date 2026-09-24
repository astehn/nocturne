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


def _pinch_event(pos, value, kind=Qt.NativeGestureType.ZoomNativeGesture,
                 on=None):
    """A pinch at `pos` in `on`'s coordinates, with the matching GLOBAL
    position, as a real event carries: the view anchors on the global one."""
    glob = QPointF(on.mapToGlobal(pos)) if on is not None else QPointF(pos)
    return QNativeGestureEvent(kind, _TOUCHPAD, 2, QPointF(pos), QPointF(pos),
                               glob, value, QPointF(), 0)


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


def _desktop_mouse_event(pos, pixel_y):
    """Andreas' desktop mouse wheel exactly as Qt delivered it on 2026-09-24,
    copied from the input trace: tagged TouchPad, synthesized by the system,
    pixel deltas, angle = 2 x pixel — and NO phase. The first version trusted
    the device type and turned this wheel into a pan."""
    return QWheelEvent(QPointF(pos), QPointF(pos), QPoint(0, pixel_y),
                       QPoint(0, 2 * pixel_y), _NO_BTN, _NO_MOD,
                       Qt.ScrollPhase.NoScrollPhase, False,
                       Qt.MouseEventSource.MouseEventSynthesizedBySystem, _TOUCHPAD)


def test_the_desktop_mouse_is_not_a_trackpad_whatever_its_device_says():
    for py in (12, 13, 56, 103, 205, -12, -103):
        assert not is_trackpad_scroll(_desktop_mouse_event(QPointF(1, 1), py))


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


# --- ImageView: the mouse wheel is exactly what it was -----------------------

def _old_wheel(view, angle_y) -> None:
    """The pre-2026-09-24 wheelEvent, verbatim, as the reference."""
    if angle_y > 0:
        view.zoom_in()
    else:
        view.zoom_out()


@pytest.mark.parametrize("pixels", [
    [103, 103, 102, 12, 13],          # a real burst from the trace, zooming in
    [-103, -103, -12, -13, -70],      # and out
    [12, -13, 205, -19, 56, 103],     # direction changes mid-stream
])
def test_the_desktop_mouse_zooms_exactly_as_before(qtbot, pixels):
    """Replay his real wheel events into one view and the OLD handler into an
    identical one: every transform must match, event by event. Anything that
    changes his wheel — a pan, a different step, a delta-scaled step — fails."""
    new, ref = _view(qtbot, zoom=1.0), _view(qtbot, zoom=1.0)
    for py in pixels:
        _send(new.viewport(), _desktop_mouse_event(QPoint(150, 100), py))
        _old_wheel(ref, 2 * py)
        assert new.transform() == ref.transform()
        assert _centre_scene(new) == _centre_scene(ref)


def test_a_classic_detent_wheel_zooms_exactly_as_before(qtbot):
    new, ref = _view(qtbot, zoom=1.0), _view(qtbot, zoom=1.0)
    for a in (120, 120, -120, 120, -120, -120, -120):
        _send(new.viewport(), _wheel_event(QPoint(150, 100), a))
        _old_wheel(ref, a)
        assert new.transform() == ref.transform()


# --- ImageView: pinch zooms about the fingers --------------------------------

def test_pinch_zooms_by_the_gesture_value(qtbot):
    view = _view(qtbot, zoom=1.0)
    _send(view.viewport(), _pinch_event(QPoint(150, 100), 0.1, on=view.viewport()))
    assert view.zoom() == pytest.approx(1.1)
    _send(view.viewport(), _pinch_event(QPoint(150, 100), -0.1, on=view.viewport()))
    assert view.zoom() == pytest.approx(1.1 * 0.9)


def test_pinch_keeps_the_point_under_the_fingers_still(qtbot):
    """Zoom about the CURSOR, not the view centre: the image pixel under the
    fingers stays under them. Off-centre on purpose, where the two differ."""
    view = _view(qtbot, zoom=1.0)
    at = QPoint(60, 40)
    anchor = view.mapToScene(at)
    for _ in range(5):
        _send(view.viewport(), _pinch_event(at, 0.2, on=view.viewport()))
    assert view.zoom() > 2.0
    after = view.mapToScene(at)
    assert after.x() == pytest.approx(anchor.x(), abs=1.0)
    assert after.y() == pytest.approx(anchor.y(), abs=1.0)


def test_pinch_stops_at_the_ceiling_and_the_floor(qtbot):
    view = _view(qtbot, zoom=1.0)
    for _ in range(200):
        _send(view.viewport(), _pinch_event(QPoint(150, 100), 0.5, on=view.viewport()))
    assert view.zoom() == pytest.approx(_MAX_ZOOM)
    view.fit()
    fitted = view.zoom()
    for _ in range(200):
        _send(view.viewport(), _pinch_event(QPoint(150, 100), -0.5, on=view.viewport()))
    # fitInView leaves Qt's small margin, so 'half the fit' is approximate
    assert view.zoom() == pytest.approx(fitted * 0.5, rel=0.05)
    assert view.zoom() > 0


def test_pinch_is_a_deliberate_zoom_that_survives_a_resize(qtbot):
    view = _view(qtbot, zoom=1.0)
    view.fit()
    _send(view.viewport(), _pinch_event(QPoint(150, 100), 0.3, on=view.viewport()))
    assert view._fitted is False


def test_smart_zoom_toggles_fit_and_actual_size(qtbot):
    view = _view(qtbot, zoom=1.0)
    view.fit()
    assert view.zoom() != pytest.approx(1.0)       # the fixture is not 1:1 at fit
    smart = Qt.NativeGestureType.SmartZoomNativeGesture
    _send(view.viewport(), _pinch_event(QPoint(150, 100), 0.0, smart, on=view.viewport()))
    assert view.zoom() == pytest.approx(1.0)
    _send(view.viewport(), _pinch_event(QPoint(150, 100), 0.0, smart, on=view.viewport()))
    assert view._fitted is True


def test_gestures_without_an_image_do_nothing(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.resize(300, 200)
    before = view.transform()
    _send(view.viewport(), _pinch_event(QPoint(150, 100), 0.3, on=view.viewport()))
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


# --- review findings, 2026-09-24 ----------------------------------------------

def _windowed_view(qtbot):
    """The view as it sits in MainWindow: NOT the top-level widget, and offset
    by chrome above and beside it. A pinch arrives through the WINDOW, as
    macOS delivers it, not straight into the viewport."""
    from PySide6.QtWidgets import QGridLayout, QLabel, QWidget
    top = QWidget()
    qtbot.addWidget(top)
    grid = QGridLayout(top)
    grid.setContentsMargins(0, 0, 0, 0)
    header = QLabel("toolbar")
    header.setFixedHeight(150)
    side = QLabel("panel")
    side.setFixedWidth(120)
    view = ImageView()
    grid.addWidget(header, 0, 0, 1, 2)
    grid.addWidget(side, 1, 0)
    grid.addWidget(view, 1, 1)
    top.resize(420, 350)
    top.show()
    view.set_image(_qimage())
    view.actual_size()
    view.centerOn(200, 150)
    return top, view


def _pinch_through_window(top, widget, at, value,
                          kind=Qt.NativeGestureType.ZoomNativeGesture):
    in_window = widget.mapTo(top, at)
    glob = widget.mapToGlobal(at)
    ev = QNativeGestureEvent(kind, _TOUCHPAD, 2, QPointF(in_window),
                             QPointF(in_window), QPointF(glob), value, QPointF(), 0)
    QApplication.sendEvent(top.windowHandle(), ev)


def test_pinch_in_a_real_window_keeps_the_point_under_the_fingers(qtbot):
    """Review finding 1: through the window the event's position() is in
    WINDOW coordinates, so anchoring on it crept the picture toward the
    toolbar with every pinch. 14.6 image px per x1.1 step in the reviewer's
    probe; the old test sent to a top-level view, where the two coincide."""
    top, view = _windowed_view(qtbot)
    at = QPoint(50, 60)
    anchor = view.mapToScene(at)
    for _ in range(3):
        _pinch_through_window(top, view.viewport(), at, 0.1)
    assert view.zoom() == pytest.approx(1.1 ** 3)       # once per event, not twice
    after = view.mapToScene(at)
    assert after.x() == pytest.approx(anchor.x(), abs=1.0)
    assert after.y() == pytest.approx(anchor.y(), abs=1.0)


def test_pinch_over_the_zoom_pill_still_zooms_once(qtbot):
    """Review finding 4: the pills are children of the VIEW, not the viewport,
    so a pinch over one never reached viewportEvent."""
    top, view = _windowed_view(qtbot)
    pill = view._zoom_pill
    assert pill.isVisible()
    _pinch_through_window(top, pill, pill.rect().center(), 0.1)
    assert view.zoom() == pytest.approx(1.1)


def test_pinch_does_not_jump_against_its_own_direction(qtbot):
    """Review finding 3: the wheel can leave the zoom outside the pinch range
    (zoom_out has no floor, zoom_in overshoots 32x). A pinch OUT from there
    must not zoom IN to the floor, and vice versa."""
    view = _view(qtbot, zoom=1.0)
    view.fit()
    for _ in range(8):
        view.zoom_out()
    low = view.zoom()
    assert low < view._fit_zoom() * 0.5
    _send(view.viewport(), _pinch_event(QPoint(150, 100), -0.1, on=view.viewport()))
    assert view.zoom() == pytest.approx(low)

    view.actual_size()
    while view.zoom() < _MAX_ZOOM:
        view.zoom_in()
    high = view.zoom()
    assert high > _MAX_ZOOM
    _send(view.viewport(), _pinch_event(QPoint(150, 100), 0.1, on=view.viewport()))
    assert view.zoom() == pytest.approx(high)


def test_a_swipe_updates_the_hover_readout(qtbot):
    """Review finding 5: the picture moves under a still pointer, so the
    readout must follow the pixel now under it, not wait for a mouse move."""
    view = _view(qtbot)
    got = []
    view.hovered.connect(lambda x, y, side: got.append((x, y)))
    at = QPoint(150, 100)
    _swipe(view.viewport(), at, 0, -2, n=10)
    assert got, "a swipe emitted no hover update"
    p = view.mapToScene(at)
    assert got[-1] == (int(p.x()), int(p.y()))


def test_preview_fling_leaves_no_hidden_overshoot(qtbot):
    """Review finding 2: the centre was clamped to [0,1], not to what can be
    shown. A fling at fit moved nothing on screen but walked the centre to the
    edge, so the next zoom opened on the border; and zoomed in, a fling into an
    edge left a dead zone the way back."""
    p = _ZoomPreview()
    qtbot.addWidget(p)
    p.resize(300, 200)
    _swipe(p, QPoint(150, 100), 0, -30, n=20)          # fling at fit
    assert p._centre == pytest.approx([0.5, 0.5])

    p.set_zoom(4.0)
    _swipe(p, QPoint(150, 100), 0, -50, n=40)          # far past the bottom
    edge = p._centre[1]
    assert edge == pytest.approx(1 - 0.5 / 4.0)
    _swipe(p, QPoint(150, 100), 0, 10, n=1)            # a little way back
    assert p._centre[1] < edge, "dead zone: swiping back did nothing"
