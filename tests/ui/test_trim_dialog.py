import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.core.image import AstroImage  # noqa: E402
from nocturne.ui.trim_dialog import TrimDialog  # noqa: E402


def _shrink(dlg, bounds):
    """Put the crop box at `bounds`, as dragging its edges would. Moving the box
    at full extent is a no-op — it is clamped to the frame."""
    dlg.view.hide_crop_box()             # show_crop_box is idempotent — it will
    dlg.view.set_crop_overlay(True, content_bounds=bounds, aspect_ratio=None)
    dlg.view.show_crop_box()             # not rebuild a box that is already up
    dlg._refresh()


def _img(h=200, w=300, linear=False):
    return AstroImage((np.random.rand(h, w, 3) * 0.5).astype(np.float32), is_linear=linear)


def test_opens_with_the_box_at_the_full_frame(qtbot):
    """Unlike the Crop step there is no content detection to offer — the edges
    the user wants gone are ones only they can see."""
    d = TrimDialog(_img()); qtbot.addWidget(d)
    assert d.view.crop_box_visible()
    assert d.view.crop_bounds() == (0, 200, 0, 300)


def test_apply_is_disabled_until_something_is_actually_removed(qtbot):
    """A full-frame "trim" is a no-op, and offering it invites a pointless step
    in the history."""
    d = TrimDialog(_img()); qtbot.addWidget(d)
    assert not d.apply_btn.isEnabled()
    _shrink(d, (10, 190, 15, 285))       # as if the user dragged the edges in
    assert d.apply_btn.isEnabled()


def test_reports_the_resulting_size_and_how_much_goes(qtbot):
    d = TrimDialog(_img()); qtbot.addWidget(d)
    assert "300 × 200" in d.size_label.text()
    assert "0.0% removed" in d.size_label.text()


def test_bounds_is_none_unless_accepted(qtbot):
    d = TrimDialog(_img()); qtbot.addWidget(d)
    assert d.bounds() is None
    d._accept()
    assert d.bounds() is None, "a full-frame trim must not be accepted"
    _shrink(d, (10, 190, 15, 285))
    d._accept()
    assert d.bounds() == (10, 190, 15, 285)
