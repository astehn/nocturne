"""The shape buttons Crop, Trim, Share and Upscale Crop share (variant B)."""
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QWidget  # noqa: E402

from nocturne.ui.shape_picker import SegmentRow, ShapePicker, TIPS  # noqa: E402


def _picker(qtbot, **kw):
    p = ShapePicker(**kw)
    qtbot.addWidget(p)
    p.resize(320, 200)
    return p


def test_the_buttons_are_in_the_approved_order(qtbot):
    p = _picker(qtbot)
    assert p.labels() == ["Free", "Original", "1:1", "5:4", "4:3", "3:2", "16:9"]


def test_share_and_upscale_have_no_free(qtbot):
    p = _picker(qtbot, offer_free=False)
    assert p.labels() == ["Original", "1:1", "5:4", "4:3", "3:2", "16:9"]
    assert p.shape() == "Picture"


def test_four_to_a_row(qtbot):
    p = _picker(qtbot)
    p.show()
    ys = [b.y() for b in p.buttons()]
    assert ys[:4] == [ys[0]] * 4 and ys[4] > ys[0] and ys[4:] == [ys[4]] * 3


def test_portrait_turns_label_outline_and_the_stored_name(qtbot):
    p = _picker(qtbot)
    got = []
    p.shapeChanged.connect(got.append)
    b = p.button("3:2")
    b.click()
    w0, h0 = b.outline_size()
    assert w0 > h0 and p.shape() == "3:2"
    p.orientation.buttons()[1].click()               # Portrait
    assert b.text() == "2:3"
    w1, h1 = b.outline_size()
    assert h1 > w1 and (w1, h1) == pytest.approx((h0, w0))
    assert p.shape() == "2:3" and got[-1] == "2:3"
    assert p.ratio() == pytest.approx(2 / 3)
    assert [x.text() for x in p.buttons()] == \
        ["Free", "Original", "1:1", "4:5", "3:4", "2:3", "9:16"]
    assert b.toolTip() == TIPS["2:3"]
    assert p.button("16:9").toolTip() == "Tall, for phone screens and Stories"
    assert p.button("5:4").toolTip() == "Portrait, as Instagram crops it"


@pytest.mark.parametrize("key", ["Free", "Picture", "1:1"])
def test_orientation_is_disabled_for_free_original_and_square(qtbot, key):
    p = _picker(qtbot)
    p.button(key).click()
    assert all(not b.isEnabled() for b in p.orientation.buttons())
    assert all(b.toolTip() for b in p.orientation.buttons()), "greyed without saying why"
    p.button("16:9").click()
    assert all(b.isEnabled() for b in p.orientation.buttons())


def test_free_and_original_ratios(qtbot):
    p = _picker(qtbot)
    assert p.shape() == "Free" and p.ratio() is None
    p.set_picture_ratio(1.25)
    p.button("Picture").click()
    assert p.shape() == "Picture" and p.ratio() == 1.25
    assert p.button("Picture").outline_size() == pytest.approx((26, 26 / 1.25))


def test_hover_tooltips_are_plain_words(qtbot):
    p = _picker(qtbot)
    assert p.button("Free").toolTip() == "Drag any shape you like"
    assert p.button("Picture").toolTip() == "Keep the picture's own proportions"
    assert p.button("1:1").toolTip() == "Square"
    assert p.button("3:2").toolTip() == "The classic camera frame"
    assert p.button("16:9").toolTip() == "Widescreen"
    assert p.button("5:4").toolTip() == p.button("4:3").toolTip() == \
        "Close to square, like a print"


@pytest.mark.parametrize("stored, label, portrait", [
    ("9:16", "9:16", True), ("4:5", "4:5", True), ("3:2", "3:2", False),
    ("Original", "Free", False), ("Picture", "Original", False),
])
def test_set_shape_restores_a_stored_name(qtbot, stored, label, portrait):
    p = _picker(qtbot)
    got = []
    p.shapeChanged.connect(got.append)
    p.set_shape(stored)
    assert p.label() == label and p.portrait() is portrait
    assert got == [], "restoring is not a choice"


def test_a_legacy_original_in_share_is_the_whole_picture(qtbot):
    p = _picker(qtbot, offer_free=False)
    p.set_shape("1:1")
    p.set_shape("Original")
    assert p.shape() == "Picture"


def test_segment_row_speaks_the_combo_subset(qtbot):
    row = SegmentRow(["None", "Thirds", "Centre"])
    qtbot.addWidget(row)
    got = []
    row.currentTextChanged.connect(got.append)
    assert row.currentText() == "None"
    row.buttons()[1].click()
    assert row.currentText() == "Thirds" and got == ["Thirds"]


def test_it_paints_at_two_x_without_error(qtbot):
    from PySide6.QtGui import QImage
    p = _picker(qtbot)
    p.button("3:2").click()
    img = QImage(640, 400, QImage.Format.Format_ARGB32)
    img.setDevicePixelRatio(2.0)
    p.render(img)
    assert isinstance(p, QWidget)
