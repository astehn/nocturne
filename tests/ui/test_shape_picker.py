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
    p.orientation.click()               # Portrait
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
    assert not p.orientation.isEnabled()
    assert "no orientation" in p.orientation.toolTip(), "greyed without saying why"
    p.button("16:9").click()
    assert p.orientation.isEnabled()
    assert p.orientation.toolTip() == ("Turn the shape to portrait: 3:2 becomes 2:3. "
                                       "Free, Original and 1:1 have no orientation.")


def test_the_toggle_sits_in_the_grids_eighth_cell(qtbot):
    p = _picker(qtbot)
    p.show()
    last = p.buttons()[-1]
    assert p.orientation.y() == last.y() and p.orientation.x() > last.x()
    assert p.orientation.text() == "Portrait"
    assert p.orientation.height() == last.height() <= 44


def test_a_greyed_portrait_does_not_look_on_and_comes_back(qtbot):
    """Review M3: Portrait is remembered through Free/Original/1:1 (sticky is
    intended) but while greyed it must not LOOK on — and it is drawn on again
    the moment a ratio is picked."""
    p = _picker(qtbot)
    p.button("3:2").click()
    p.orientation.click()
    assert p.orientation.looks_on()
    for key in ("Free", "Picture", "1:1"):
        p.button(key).click()
        assert p.orientation.isChecked(), "the choice is remembered"
        assert not p.orientation.looks_on(), f"greyed but drawn on at {key}"
    p.button("16:9").click()
    assert p.orientation.looks_on() and p.shape() == "9:16"


def test_the_greyed_toggle_is_drawn_as_off(qtbot):
    """Pixels, not the flag: the greyed-checked toggle renders like the
    greyed-unchecked one."""
    from PySide6.QtGui import QImage

    def grab(p):
        img = QImage(p.orientation.size(), QImage.Format.Format_ARGB32)
        img.fill(0)
        p.orientation.render(img)
        return img

    a = _picker(qtbot); a.show()
    a.button("3:2").click(); a.orientation.click(); a.button("Free").click()
    b = _picker(qtbot); b.show()
    b.button("Free").click()
    assert grab(a) == grab(b)


def test_keyboard_focus_is_visible(qtbot):
    """Review M4: a focused shape button is drawn differently."""
    from PySide6.QtGui import QImage
    p = _picker(qtbot)
    p.show(); qtbot.waitExposed(p)
    b = p.button("4:3")

    def grab():
        img = QImage(b.size(), QImage.Format.Format_ARGB32)
        img.fill(0)
        b.render(img)
        return img

    plain = grab()
    b.setFocus()
    qtbot.waitUntil(b.hasFocus)
    assert grab() != plain


def test_free_and_original_ratios(qtbot):
    p = _picker(qtbot)
    assert p.shape() == "Free" and p.ratio() is None
    p.set_picture_ratio(1.25)
    p.button("Picture").click()
    assert p.shape() == "Picture" and p.ratio() == 1.25
    assert p.button("Picture").outline_size() == pytest.approx((18, 18 / 1.25))


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
