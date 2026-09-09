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


# --- geometry after layout: the two Criticals of the round-2 review ---------
#
# Both defects were about widget geometry AFTER the layout runs, which is why
# every test above missed them: a widget that is never shown and never laid out
# reports its default size, and the defect only exists in the difference
# between that and the real one. These show the widget, let the layout settle,
# and read the real sizes back.


def _shown_side(qtbot, image=None, w=800, h=400):
    """The real gesture, in order: the dialog opens in Off with a picture
    already in the after pane, and the user THEN picks Side by side.

    The order is load-bearing. Starting in Side with both panes empty leaves
    the two sizeHints equal, and a layout that splits by hint then looks
    correct — the fixture would be symmetric, and a symmetric fixture cannot
    tell a correct implementation from a broken one. The defect IS the
    asymmetry: the after pane arrives holding a full-width picture while the
    before pane holds nothing.
    """
    image = _qimage(300, 300) if image is None else image
    view = CompareView()
    qtbot.addWidget(view)
    view.resize(w, h)
    view.show()
    qtbot.waitExposed(view)
    view.set_images(image, image)          # Off: only the after pane is filled
    qtbot.waitUntil(lambda: view._after_pane.width() > w // 2, timeout=1000)
    view.set_mode("side")
    return view


def test_the_two_side_panes_are_equal_on_the_first_click(qtbot):
    """`_ZoomPreview` is a QLabel, so its sizeHint is its PIXMAP's size. With no
    stretch on the two boxes the QHBoxLayout split the width by those hints, and
    the after pane arrives holding the Off-mode picture while the before pane
    holds nothing — measured 400 px against 216 here, and 460 against 328 in the
    dialog at 1180x860. Two pictures at a 40% scale difference cannot be
    compared, which is the entire point of the mode.

    Read IMMEDIATELY, with no waiting: that frame is what the user sees when
    they click, and with both panes eventually rendering the same size the
    unequal split can converge afterwards — which is why the bug reads as
    intermittent rather than as always broken.
    """
    view = _shown_side(qtbot)
    assert view._before_pane.size() == view._after_pane.size(), (
        f"on the first click: before {view._before_pane.size()}, after "
        f"{view._after_pane.size()} — the pixmaps are driving the layout")
    qtbot.waitUntil(
        lambda: view._before_pane.width() == view._after_pane.width(), timeout=1000)
    assert view._before_pane.size() == view._after_pane.size()


def test_no_pane_is_left_holding_a_pixmap_larger_than_itself(qtbot):
    """QLabel AlignCenter CENTRE-CROPS a pixmap bigger than the label, with no
    scrollbar and no indication — measured, a 611x611 picture inside a 460 px
    pane cut 75 px off each side. A pane's geometry settles after the layout
    runs, so a picture rendered before that is left oversized unless the pane's
    own resize triggers a re-render."""
    view = _shown_side(qtbot)
    view.resize(420, 300)                  # shrink: the panes follow, later
    qtbot.waitUntil(lambda: view._after_pane.width() < 260, timeout=1000)
    for name, pane in (("before", view._before_pane), ("after", view._after_pane)):
        pm = pane.pixmap()
        assert pm.width() <= pane.width() and pm.height() <= pane.height(), (
            f"{name} pane is {pane.width()}x{pane.height()} holding a "
            f"{pm.width()}x{pm.height()} pixmap — silently centre-cropped")


def test_a_speck_in_a_corner_survives_to_the_displayed_pixmap(qtbot):
    """The reviewer's repro: a speck at (20, 20) of a 1200^2 frame vanished
    entirely, which is exactly what "drag until the first specks appear" is
    looking for. Mid-grey field, never np.zeros — a black field is itself
    shadow-clipped and would make this pass for the wrong reason."""
    from nocturne.ui.preview import qimage_to_rgb8
    arr = np.full((1200, 1200, 3), 128, dtype=np.uint8)
    arr[20, 20] = 255
    view = _shown_side(qtbot, image=rgb_to_qimage(arr), w=1180, h=700)
    view.resize(900, 560)
    qtbot.waitUntil(lambda: view._after_pane.width() < 460, timeout=1000)

    for name, pane in (("before", view._before_pane), ("after", view._after_pane)):
        pm = pane.pixmap()
        assert pm.width() <= pane.width() and pm.height() <= pane.height(), (
            f"the {name} pane centre-crops its picture, so the frame's own "
            "corners are not on screen at all")
        shown = qimage_to_rgb8(pm.toImage())
        h, w = shown.shape[:2]
        corner = shown[:max(1, h // 8), :max(1, w // 8)]
        assert int(corner.max()) > 128, (
            f"the speck is missing from the {name} pane's top-left corner")


def test_the_letterbox_is_not_the_same_colour_as_a_black_picture(qtbot):
    """A clipping overlay is pure black wherever nothing clips. If the pane
    behind it were black too, a letterboxed picture would have no visible edge
    and the view reads as though the overlay covers only part of the image —
    which is exactly how it was reported. The pane must be distinguishable from
    #000000 without being bright enough to compete with the picture.
    """
    from nocturne.ui.compare_view import _LETTERBOX

    view = CompareView()
    qtbot.addWidget(view)
    for pane in (view._after_pane, view._before_pane):
        assert _LETTERBOX in pane.styleSheet()
    r, g, b = (int(_LETTERBOX[i:i + 2], 16) for i in (1, 3, 5))
    assert max(r, g, b) >= 0x28, "too close to black to bound the picture"
    assert max(r, g, b) <= 0x50, "bright enough to compete with the picture"
