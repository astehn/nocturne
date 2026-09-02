"""The title plate's painter.

These tests are the specification for `draw_plate`. In particular they pin the
one behaviour this whole feature exists to fix: the plate WRAPS. The renderer it
replaces elided, and the real caption for a 2037-frame IC 1396A export lost its
date and the photographer's handle to a '…' that nothing warned about.
"""
import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QColor, QImage  # noqa: E402

from nocturne.core.plate import PlateText  # noqa: E402
from nocturne.ui.fonts import load_bundled_fonts  # noqa: E402
from nocturne.ui.plate_render import ANCHORS, blur, draw_plate, last_layout  # noqa: E402


@pytest.fixture(autouse=True)
def _fonts(qapp):
    """Without this a family that is merely REQUESTED substitutes in silence,
    and every measurement below would be of some other typeface."""
    load_bundled_fonts()


class _Style:
    family = "Jost"; size_title = 0.030; size_sub = 0.042; size_credit = 0.016
    tracking_title = 14; tracking_sub = 4; weight_title = 500; weight_sub = 300
    treatment = "scrim"; anchor = "bottom-centre"; margin = 0.055
    colour = "#F0E9E2"; rule = True; keyline = False


def _dark(w=800, h=1000):
    img = QImage(w, h, QImage.Format.Format_RGB888)
    img.fill(0x101010)
    return img


def _mean(img):
    w, h = img.width(), img.height()
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    a = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w*3]
    return float(a.mean())


def test_it_draws_something(qtbot):
    text = PlateText("IC 1396A", "Elephant's Trunk Nebula", "5 h 39 m · @andreas")
    out = draw_plate(_dark(), text, _Style())
    assert _mean(out) > _mean(_dark()), "nothing was painted"


def test_long_text_wraps_instead_of_being_elided(qtbot):
    """The regression this feature exists to kill: today's renderer elides, and
    the real caption for IC 1396A loses the date AND the handle to a '…' with
    no warning."""
    long_name = "The Extremely Long Common Name Of Some Nebula Or Other"
    draw_plate(_dark(), PlateText("IC 1396A", long_name, ""), _Style())
    lines = last_layout()["sub_lines"]
    assert len(lines) > 1, "did not wrap"
    assert not any("…" in ln for ln in lines), "elided instead of wrapping"
    assert "".join(lines).replace(" ", "") == long_name.replace(" ", "")


def test_an_empty_slot_is_omitted_and_the_gap_closes(qtbot):
    draw_plate(_dark(), PlateText("IC 1396A", "Trunk", "credit"), _Style())
    h_full = last_layout()["block_height"]
    draw_plate(_dark(), PlateText("", "Trunk", ""), _Style())
    assert last_layout()["block_height"] < h_full


def test_each_anchor_puts_the_block_where_it_says(qtbot):
    """Nine anchors, nine distinct positions — a grid that silently collapses to
    three would look like it worked."""
    seen = {}
    for _label, key in ANCHORS:
        st = _Style(); st.anchor = key
        draw_plate(_dark(), PlateText("IC 1396A", "Trunk", ""), st)
        lay = last_layout()
        seen[key] = (round(lay["block_left"]), round(lay["block_top"]))
    assert len(set(seen.values())) == len(ANCHORS), f"anchors collide: {seen}"


def test_the_scrim_darkens_the_bottom_and_leaves_the_top_alone(qtbot):
    grey = QImage(400, 400, QImage.Format.Format_RGB888); grey.fill(0x808080)
    st = _Style(); st.treatment = "scrim"
    out = draw_plate(grey, PlateText("", "", ""), st)
    top = out.pixelColor(200, 20).red()
    bot = out.pixelColor(200, 395).red()
    assert top == 0x80, "the scrim reached the top of the frame"
    assert bot < 0x60, "the scrim did not darken the bottom"


def test_the_band_treatment_still_reproduces_a_hard_edge(qtbot):
    """Kept so the Data preset can reproduce today's output."""
    grey = QImage(400, 400, QImage.Format.Format_RGB888); grey.fill(0x808080)
    st = _Style(); st.treatment = "band"
    out = draw_plate(grey, PlateText("", "", "x"), st)
    top = last_layout()["band_top"]
    assert out.pixelColor(200, top - 4).red() == 0x80
    assert out.pixelColor(200, top + 4).red() < 0x80


def test_the_shadow_darkens_beneath_the_glyphs(qtbot):
    """Legibility with NO band depends entirely on this."""
    grey = QImage(600, 400, QImage.Format.Format_RGB888); grey.fill(0xB0B0B0)
    st = _Style(); st.treatment = "shadow"; st.rule = False
    out = draw_plate(grey, PlateText("", "TRUNK", ""), st)
    assert _mean(out) < _mean(grey), "no shadow was laid down"


def test_matte_extends_the_canvas_rather_than_covering_the_picture(qtbot):
    st = _Style(); st.treatment = "matte"
    src = _dark(800, 1000)
    out = draw_plate(src, PlateText("IC 1396A", "Trunk", "c"), st)
    assert out.height() > 1000
    assert out.width() == 800


def test_the_keyline_is_independent_of_the_treatment(qtbot):
    grey = QImage(400, 400, QImage.Format.Format_RGB888); grey.fill(0x303030)
    st = _Style(); st.treatment = "none"; st.keyline = True; st.rule = False
    out = draw_plate(grey, PlateText("", "", ""), st)
    assert _mean(out) > _mean(grey), "keyline not drawn"


def test_blur_spreads_a_point_without_moving_it(qtbot):
    img = QImage(41, 41, QImage.Format.Format_ARGB32)
    img.fill(0)
    img.setPixelColor(20, 20, QColor(255, 255, 255, 255))
    out = blur(img, 4)
    assert out.pixelColor(20, 20).alpha() < 255       # spread
    assert out.pixelColor(22, 20).alpha() > 0         # into the neighbourhood
    assert out.pixelColor(20, 20).alpha() >= out.pixelColor(26, 20).alpha()  # still centred


def test_last_layout_carries_what_the_dialog_and_compose_read(qtbot):
    """These six keys are a contract, not a debug dump: share_render reads
    block_height to prove the plate scales with the output, and the dialog reads
    overflow to say 'this will not fit' out loud."""
    draw_plate(_dark(), PlateText("IC 1396A", "Trunk", "credit"), _Style())
    lay = last_layout()
    for key in ("sub_lines", "block_height", "block_left", "block_top",
                "band_top", "overflow"):
        assert key in lay, f"{key} missing from last_layout()"
    assert isinstance(lay["overflow"], bool)


def test_overflow_is_false_when_everything_fits(qtbot):
    draw_plate(_dark(), PlateText("IC 1396A", "Trunk", "5 h 39 m"), _Style())
    assert last_layout()["overflow"] is False


def test_a_word_longer_than_the_line_keeps_every_character(qtbot):
    """It must not spin looking for a break that does not exist, and it must not
    quietly drop the tail — that is the elide bug wearing a different hat. The
    dialog is what tells the user, via overflow."""
    word = "x" * 400
    draw_plate(_dark(), PlateText("", word, ""), _Style())
    lay = last_layout()
    assert lay["sub_lines"] == [word]
    assert lay["overflow"] is True
