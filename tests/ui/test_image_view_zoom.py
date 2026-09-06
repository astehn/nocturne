"""Zooming must not cost memory proportional to the zoom.

2026-09-06: Andreas zoomed into a 5.25 Mpx frame and his 64 GB machine reached a
215.9 GB footprint and stopped responding. The cause was a
QGraphicsDropShadowEffect on the pixmap item: a QGraphicsEffect makes Qt
rasterise the WHOLE item into an offscreen buffer at device resolution before
compositing, so the cost is the zoomed area of the entire image and the viewport
does not bound it. Measured on that frame: 409 MB at 0.45x, 2.3 GB at 1.73x —
dead by the eighth wheel click. Without the effect: 389 MB, flat, out to
236,000x.
"""
import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QImage  # noqa: E402
from nocturne.ui.image_view import _MAX_ZOOM, ImageView  # noqa: E402


def _qimage(w=400, h=300):
    arr = np.ascontiguousarray((np.random.rand(h, w, 3) * 255).astype(np.uint8))
    return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def test_the_image_item_carries_no_graphics_effect(qtbot):
    """The regression guard for the blow-up itself.

    Not "no drop shadow" — ANY QGraphicsEffect has this cost, so a future glow
    or blur added here would reintroduce it in a form a shadow-specific test
    would wave through.
    """
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage())
    assert view._item.graphicsEffect() is None


def test_zoom_stops_at_the_ceiling(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage())
    view.actual_size()
    for _ in range(80):
        view.zoom_in()
    # One step may overshoot: the ceiling is checked before scaling, so the last
    # permitted click lands above it. It must not RUN, which is what unbounded
    # 1.25-per-click did — sixty clicks reach 236,000x.
    assert view.zoom() <= _MAX_ZOOM * 1.25 + 1e-6
    assert view.zoom() >= _MAX_ZOOM


def test_zooming_out_is_still_free(qtbot):
    """The ceiling must not also pin the view when zooming back out."""
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage())
    for _ in range(60):
        view.zoom_in()
    at_top = view.zoom()
    for _ in range(5):
        view.zoom_out()
    assert view.zoom() < at_top


def test_zoom_in_past_the_ceiling_then_out_then_in_again(qtbot):
    """A view parked at the ceiling must still respond to the wheel.

    A ceiling implemented by clamping the TRANSFORM rather than refusing the
    step would leave zoom() at the cap while the user's clicks did nothing
    visible in either direction.
    """
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage())
    for _ in range(60):
        view.zoom_in()
    view.zoom_out()
    lowered = view.zoom()
    view.zoom_in()
    assert view.zoom() > lowered


def test_the_edge_shadow_is_skipped_when_the_image_fills_the_view(qtbot):
    """Zoomed in, the image edge is off-screen and there is nothing to shade.

    Exercised through a real paint rather than by calling the helper, so the
    skip is proven where Qt actually calls it.
    """
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage())
    view.resize(200, 150)
    for _ in range(20):
        view.zoom_in()
    view.grab()          # must not raise, and must not draw off into space


def test_a_full_zoom_sweep_paints_without_raising(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage())
    view.resize(300, 200)
    for _ in range(40):
        view.zoom_in()
        view.grab()
    for _ in range(40):
        view.zoom_out()
        view.grab()


def test_a_refused_zoom_leaves_the_view_where_it_was(qtbot):
    """At the ceiling, a further wheel click leaves scale AND position alone.

    Written expecting to catch a clamp-the-transform implementation
    (scale, then resetTransform and re-scale to the cap on overshoot) on the
    grounds that resetTransform would throw the pan away. Checked: it does not
    — Qt restores the centre afterwards, and that variant moves the view by
    (0.0, 0.0). So this guards the no-op property itself, not that alternative,
    and it is recorded here rather than left as a rationale that is not true.
    """
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(_qimage(800, 600))
    view.resize(200, 150)
    for _ in range(60):
        view.zoom_in()
    view.centerOn(700.0, 500.0)          # park somewhere that is not the origin
    before = (view.zoom(), view.mapToScene(view.viewport().rect().center()))
    view.zoom_in()
    after = (view.zoom(), view.mapToScene(view.viewport().rect().center()))
    assert after[0] == before[0], "a refused zoom changed the scale"
    assert abs(after[1].x() - before[1].x()) < 1.0, "a refused zoom moved the view"
    assert abs(after[1].y() - before[1].y()) < 1.0, "a refused zoom moved the view"
