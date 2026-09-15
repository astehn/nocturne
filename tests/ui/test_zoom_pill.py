import pytest

pytest.importorskip("PySide6")
from nocturne.ui.zoom_pill import ZoomPill  # noqa: E402


def test_buttons_invoke_callbacks(qtbot):
    calls = []
    pill = ZoomPill(lambda: calls.append("out"),
                    lambda: calls.append("fit"),
                    lambda: calls.append("in"))
    qtbot.addWidget(pill)
    pill.out_btn.click()
    pill.fit_btn.click()
    pill.in_btn.click()
    assert calls == ["out", "fit", "in"]


# --- the pill during a crop ----------------------------------------------
# It used to be HIDDEN in crop mode (image_view.py, 2026), so the Trim tool and
# Upscale Crop had no zoom control at all — Andreas reported both on 2026-09-15.
# The reason for hiding it was real: at bottom-right it sits over the crop box's
# bottom-right handle and swallows its drags. Moving it to bottom-left keeps the
# control AND keeps the handle draggable, and that corner is provably free
# during a crop because the readout pill is hidden for the same reason.

def _view(qtbot, w=900, h=700):
    from nocturne.ui.image_view import ImageView
    v = ImageView()
    qtbot.addWidget(v)
    v.resize(w, h)
    v.show()
    qtbot.waitExposed(v)
    return v


def test_the_pill_stays_visible_while_cropping(qtbot):
    v = _view(qtbot)
    v.set_crop_overlay(True, content_bounds=(0, 0, 100, 100))
    assert v._zoom_pill.isVisible()


def test_it_moves_off_the_bottom_right_handle(qtbot):
    """The whole reason it was hidden. Asserted against the view's own right
    edge rather than a pixel constant, so a restyle cannot quietly break it."""
    v = _view(qtbot)
    v.set_crop_overlay(True, content_bounds=(0, 0, 100, 100))
    g = v._zoom_pill.geometry()
    assert g.right() < v.width() / 2, (g.right(), v.width())
    assert g.bottom() > v.height() / 2      # still on the bottom edge


def test_it_returns_to_the_bottom_right_when_the_crop_ends(qtbot):
    v = _view(qtbot)
    before = v._zoom_pill.geometry()
    v.set_crop_overlay(True, content_bounds=(0, 0, 100, 100))
    v.set_crop_overlay(False)
    assert v._zoom_pill.geometry() == before
    assert v._zoom_pill.isVisible()


def test_it_does_not_collide_with_the_readout_pill(qtbot):
    """Bottom-left is free DURING a crop because the readout is hidden there —
    but only during. If the readout is ever shown in crop mode, these two would
    sit on top of each other, so the guard is that they are never both visible
    in that corner."""
    v = _view(qtbot)
    v.set_crop_overlay(True, content_bounds=(0, 0, 100, 100))
    assert not v.readout_pill.isVisible()
