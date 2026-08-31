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


# --- aspect ratio and guides, matching the Crop step -------------------------

def test_choosing_an_aspect_actually_snaps_the_box(qtbot):
    """Not "the combo exists" — the box has to change shape. Trim shipped with a
    bare rubber-band and Andreas (2026-08-31): "it's kind of difficult to do a
    meaningful trim". ImageView already had apply_aspect; nothing was wired to it.
    """
    d = TrimDialog(_img(h=200, w=300)); qtbot.addWidget(d); d.show()
    qtbot.waitExposed(d)
    d.aspect_box.setCurrentText("1:1")
    top, bottom, left, right = d.view.crop_bounds()
    w, h = right - left, bottom - top
    assert h > 0 and abs(w / h - 1.0) < 0.05, f"1:1 gave a {w}x{h} box"


def test_a_wide_aspect_gives_a_wide_box(qtbot):
    """Two ratios, so the test cannot pass on a box that merely changed once."""
    d = TrimDialog(_img(h=400, w=400)); qtbot.addWidget(d); d.show()
    qtbot.waitExposed(d)
    d.aspect_box.setCurrentText("16:9")
    t, b, l, r = d.view.crop_bounds()
    wide = (r - l) / max(1, b - t)
    d.aspect_box.setCurrentText("4:5")
    t, b, l, r = d.view.crop_bounds()
    tall = (r - l) / max(1, b - t)
    assert wide > tall, f"16:9 ({wide:.2f}) is not wider than 4:5 ({tall:.2f})"
    assert abs(wide - 16 / 9) < 0.1 and abs(tall - 4 / 5) < 0.1


def test_original_leaves_the_box_free_to_be_any_shape(qtbot):
    """The default must not start snapping — a trim is usually a few pixels off
    one edge, which no fixed ratio allows."""
    d = TrimDialog(_img()); qtbot.addWidget(d); d.show()
    qtbot.waitExposed(d)
    assert d.aspect_box.currentText() == "Original"
    assert d.view._aspect is None


def test_guides_default_to_off_and_reach_the_view(qtbot):
    d = TrimDialog(_img()); qtbot.addWidget(d); d.show()
    qtbot.waitExposed(d)
    assert d.guides_box.currentText() == "None"
    assert d.view._guides == "none"
    d.guides_box.setCurrentText("Rule of thirds")
    assert d.view._guides == "thirds"
    d.guides_box.setCurrentText("Center cross")
    assert d.view._guides == "center"


def test_trim_offers_exactly_what_crop_offers(qtbot):
    """The request was to mimic Crop. If someone adds a ratio to one, this fails
    rather than letting the two drift — which is the whole reason the maps were
    merged into core.crop."""
    from nocturne.core.crop import ASPECTS, GUIDES
    d = TrimDialog(_img()); qtbot.addWidget(d)
    assert [d.aspect_box.itemText(i) for i in range(d.aspect_box.count())] == ASPECTS
    assert [d.guides_box.itemText(i) for i in range(d.guides_box.count())] == GUIDES


def test_the_aspect_map_has_one_definition():
    """It was written out twice, in core.crop and main_window, and wiring Trim
    would have made a third. Two dicts that must agree, in different files, is
    how a 4:5 in one place becomes 5:4 in another."""
    import pathlib
    root = pathlib.Path(__file__).parents[2]
    literal = '"16:9": 16 / 9'
    found = sorted(str(f.relative_to(root)) for f in (root / "nocturne").rglob("*.py")
                   if literal in f.read_text(errors="ignore"))
    assert found == ["nocturne/core/crop.py"], f"aspect ratios defined in: {found}"
