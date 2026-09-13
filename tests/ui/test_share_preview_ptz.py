"""The Share preview can be panned and zoomed.

Andreas, 2026-09-13: "We need to implement so that users can pan, tilt and zoom
in the share function, that makes it easier for the user to decide, placement,
color and size if the title plate."

Read correctly, the ask is about inspecting the RESULT. The left pane already
gives framing — dragging the crop box IS pan and zoom in effect — but the right
pane was a QLabel holding a down-scaled pixmap, so a 4096 px share was judged at
roughly 25%. That is not a size anyone can decide typography at.

So the fix is the widget, not a new mechanism: the same ImageView the left pane
uses, which brings zoom, pan, fit and the zoom pill with it.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QGraphicsView

from nocturne.ui.image_view import ImageView
from tests.ui.test_share_dialog import _dlg


def test_the_preview_pane_is_a_real_view(qtbot):
    d = _dlg(qtbot)
    assert isinstance(d._preview_view, ImageView)


def test_it_zooms(qtbot):
    d = _dlg(qtbot)
    d.show(); qtbot.waitExposed(d)
    fitted = d._preview_view.zoom()
    d._preview_view.zoom_in()
    assert d._preview_view.zoom() > fitted
    d._preview_view.fit()
    assert d._preview_view.zoom() == pytest.approx(fitted, rel=0.02)


def test_it_pans_by_dragging(qtbot):
    """ScrollHandDrag is what makes it pannable; without it zooming in strands
    you on whatever corner the fit happened to leave."""
    d = _dlg(qtbot)
    assert d._preview_view.dragMode() == QGraphicsView.DragMode.ScrollHandDrag


def test_the_zoom_pill_is_available_here(qtbot):
    """The pane has no crop overlay, so the pill is not suppressed — which is
    also where the percentage readout shows up."""
    d = _dlg(qtbot)
    d.show(); qtbot.waitExposed(d)
    assert not d._preview_view._zoom_pill.isHidden()


def test_a_deliberate_zoom_survives_a_recompose(qtbot):
    """The point of the feature. Zoom in to judge the plate, change the caption
    or the colour, and you must still be looking at the same place — a re-fit
    on every edit would make inspecting anything impossible."""
    d = _dlg(qtbot)
    d.show(); qtbot.waitExposed(d)
    d._preview_view.zoom_in()
    d._preview_view.zoom_in()
    zoomed = d._preview_view.zoom()

    d._refresh_preview()                     # as any control change does

    assert d._preview_view.zoom() == pytest.approx(zoomed, rel=0.02), (
        "the preview re-fitted and threw away where the user was looking")


def test_changing_the_aspect_refits(qtbot):
    """The exception, and it is ImageView's own rule: new DIMENSIONS mean the
    old viewport is meaningless, so it fits again. Switching 1:1 to 16:9 must
    show the whole new frame, not a corner of it."""
    from nocturne.core.share import ASPECTS
    d = _dlg(qtbot)
    d.show(); qtbot.waitExposed(d)
    d._aspect_buttons["1:1"].click()
    qtbot.wait(10)
    d._preview_view.zoom_in()
    d._aspect_buttons["16:9"].click()
    qtbot.wait(10)
    w = d._preview_view._item.boundingRect().width() * d._preview_view.zoom()
    assert w <= d._preview_view.viewport().width() + 2, (
        "after an aspect change the whole frame should be in view")


def test_the_crop_box_stays_off_this_pane(qtbot):
    """The reframing box belongs to the LEFT pane. A second one here would be
    the third crop tool on screen — Andreas already read one as that."""
    d = _dlg(qtbot)
    assert d._preview_view._crop_mode is False
    assert d._preview_view.crop_box_visible() is False
