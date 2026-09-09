"""CompareView: Off/Wipe/Side modes, and the shared pan/zoom model that is the
whole point of the widget — see round2-task-A-brief.md, ruling 1.3."""
import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

pytest.importorskip("PySide6")
from nocturne.ui.compare_view import CompareView  # noqa: E402
from nocturne.ui.preview import rgb_to_qimage  # noqa: E402


def _qimage(w=60, h=40, fill=128):
    arr = np.full((h, w, 3), fill, dtype=np.uint8)
    return rgb_to_qimage(arr)


def _drag(widget, start: QPointF, end: QPointF) -> None:
    """A real press-move-release, per CLAUDE.md: qtbot.mouseMove is unreliable
    here, so build and send the events directly. Drives _ZoomPreview's actual
    mousePressEvent/mouseMoveEvent handlers, not a shortcut around them."""
    press = QMouseEvent(QEvent.Type.MouseButtonPress, start, start,
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, press)
    move = QMouseEvent(QEvent.Type.MouseMove, end, end,
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, move)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, end, end,
                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                          Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, release)


def _mk(qtbot) -> CompareView:
    w = CompareView()
    qtbot.addWidget(w)
    w.resize(800, 400)
    return w


def test_default_mode_is_off(qtbot):
    w = _mk(qtbot)
    assert w.mode() == "off"


def test_switching_modes_changes_what_is_shown(qtbot):
    w = _mk(qtbot)
    w.set_images(_qimage(fill=10), _qimage(fill=200))

    # Off: the after pane is the one on-screen widget; the before pane and the
    # wipe view are both detached, not merely hidden behind it.
    w.set_mode("off")
    assert w._after_pane.parent() is w
    assert w._before_pane.parent() is None
    assert w._wipe_view.parent() is None

    # Wipe: ImageView is the one on-screen widget.
    w.set_mode("wipe")
    assert w._wipe_view.parent() is w
    assert w._after_pane.parent() is None
    assert w._before_pane.parent() is None

    # Side: both panes are on screen, under the widget, each with its label.
    w.set_mode("side")
    assert w.isAncestorOf(w._before_pane)
    assert w.isAncestorOf(w._after_pane)
    assert w.isAncestorOf(w._before_label)
    assert w.isAncestorOf(w._after_label)
    assert w._wipe_view.parent() is None


def test_mode_round_trips_and_rejects_unknown(qtbot):
    w = _mk(qtbot)
    w.set_mode("wipe")
    assert w.mode() == "wipe"
    w.set_mode("side")
    assert w.mode() == "side"
    w.set_mode("off")
    assert w.mode() == "off"
    with pytest.raises(ValueError):
        w.set_mode("split")  # not one of off/wipe/side


def test_zooming_one_pane_moves_the_other_identically(qtbot):
    """The feature under test. Driven through the real widget's own public
    zoom entry point (the same one wheelEvent calls), not by poking shared
    state into existence for the test's own benefit. A naive implementation
    with two independent _ZoomPreview instances leaves the untouched pane at
    its default 1.0 zoom and fails this."""
    w = _mk(qtbot)
    w.set_mode("side")
    w.set_images(_qimage(), _qimage())
    assert w._before_pane.zoom_level() == w._after_pane.zoom_level() == 1.0

    w._before_pane.set_zoom(5.0)

    assert w._after_pane.zoom_level() == pytest.approx(5.0)
    assert w._before_pane.zoom_level() == pytest.approx(5.0)
    assert w.zoom_level() == pytest.approx(5.0)

    # And the other direction: zooming the after pane moves the before pane.
    w._after_pane.set_zoom(2.0)
    assert w._before_pane.zoom_level() == pytest.approx(2.0)


def test_panning_one_pane_moves_the_other_identically(qtbot):
    """Same guarantee for pan. A real mouse drag on ONE pane; read the other
    pane's own state back, not a signal or a return value."""
    w = _mk(qtbot)
    w.set_mode("side")
    w.set_images(_qimage(), _qimage())
    w._before_pane.resize(200, 200)
    w._after_pane.resize(200, 200)
    w._before_pane.set_zoom(4.0)   # panning at zoom 1.0 is clamped to nothing

    before_centre = list(w._before_pane._centre)
    _drag(w._before_pane, QPointF(150, 150), QPointF(80, 60))
    after_drag_centre = list(w._before_pane._centre)
    assert after_drag_centre != before_centre, "fixture drag did not move the pane itself"

    assert w._after_pane._centre == pytest.approx(after_drag_centre)
    shape = (300, 500, 3)
    assert w._after_pane.visible_rect(shape) == w._before_pane.visible_rect(shape)


def test_viewChanged_emitted_once_per_shared_interaction(qtbot):
    w = _mk(qtbot)
    w.set_mode("side")
    seen = []
    w.viewChanged.connect(lambda: seen.append(1))
    w._before_pane.set_zoom(3.0)
    assert len(seen) == 1, "expected exactly one CompareView.viewChanged for one pane interaction"


def test_visible_rect_and_zoom_level_reflect_shared_model(qtbot):
    w = _mk(qtbot)
    w.set_mode("side")
    w.resize(400, 200)
    shape = (200, 400, 3)
    assert w.zoom_level() == 1.0
    full = w.visible_rect(shape)
    assert full == (0, 0, 400, 200)

    w.set_zoom(2.0)
    assert w.zoom_level() == pytest.approx(2.0)
    zoomed = w.visible_rect(shape)
    assert zoomed != full
    # The model, read straight off the pane the widget forwards to.
    assert w.visible_rect(shape) == w._after_pane.visible_rect(shape)

    w.reset_view()
    assert w.zoom_level() == pytest.approx(1.0)
    assert w.visible_rect(shape) == full


@pytest.mark.parametrize("mode", ["off", "wipe", "side"])
def test_set_images_with_before_none_does_not_crash(qtbot, mode):
    w = _mk(qtbot)
    w.set_mode(mode)
    w.set_images(None, _qimage())
    # And the reverse order: mode switched into AFTER a None before was set.
    other = {"off": "wipe", "wipe": "side", "side": "off"}[mode]
    w.set_mode(other)
    w.set_images(None, _qimage())


def test_pane_size_is_the_pane_not_the_widget(qtbot):
    """A host that must produce its pixels AT the display size — Starless
    Levels' clipping overlay, whose block-max must not be re-diluted by a later
    rescale — needs the pane. In Side mode that is roughly half the width, and
    rendering to the full 800 would be scaled down again on arrival."""
    w = _mk(qtbot)
    w.show()                     # nested layouts only lay out once shown
    qtbot.waitExposed(w)
    assert w.pane_size() == w._after_pane.size()
    off_w = w.pane_size().width()

    w.set_mode("side")
    qtbot.waitUntil(lambda: w._after_pane.width() < off_w, timeout=1000)
    assert w.pane_size().width() < off_w * 0.75, (
        "Side mode still reports the full width — the overlay would be built "
        "twice the size of the pane it lands in")


def test_wipe_pane_size_leaves_room_to_scale_up(qtbot):
    """ImageView fits with fitInView, which insets the viewport by 2 px and
    transforms nearest-neighbour: a picture sized to the exact viewport is
    shrunk very slightly, and a nearest-neighbour shrink DROPS an isolated
    speck. The margin means it can only ever scale up."""
    w = _mk(qtbot)
    w.set_mode("wipe")
    w.show()
    qtbot.waitExposed(w)
    viewport = w._wipe_view.viewport().size()
    assert w.pane_size().width() < viewport.width()
    assert w.pane_size().height() < viewport.height()
