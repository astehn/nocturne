"""Plain-words tooltips on the plate-solve overlay (his ask, 2026-10-14, after asking
whether 15' on his M 16 solve meant 15 degrees). The texts live in core so they can
be tested without Qt; the canvas only shows them."""
import pytest

from nocturne.core.annotate import scale_bar_tip
from nocturne.core.annotation_layout import GridLine, Label, build_layout_for, grid_lines
from tests.core.test_annotation_layout import _grid_wcs, _layers


@pytest.mark.parametrize("arcsec, says", [
    (900, ["15 arcminutes", "half the width of the full Moon"]),
    (1800, ["30 arcminutes", "about the width of the full Moon"]),
    (600, ["10 arcminutes", "a third of the width of the full Moon"]),
    (300, ["5 arcminutes", "1/6 of the width of the full Moon"]),
    (3600, ["1 degree", "about 2 full Moons side by side"]),
    (7200, ["2 degrees", "about 4 full Moons side by side"]),
    (30, ["30 arcseconds", "1/60 of the width of the full Moon"]),
    (60, ["1 arcminute", "1/30 of the width of the full Moon"]),
])
def test_the_scale_bar_tip_names_the_unit_and_compares_with_the_moon(arcsec, says):
    tip = scale_bar_tip(arcsec)
    for s in says:
        assert s in tip, (arcsec, tip)
    assert "60 arcminutes make 1 degree" in tip


def test_the_scale_bar_label_carries_the_tip_for_its_own_length():
    prims = build_layout_for([], [], None, (600, 800), 2.0, _layers(scale=True), "all")
    bar = [p for p in prims if isinstance(p, Label)]
    assert len(bar) == 1
    # 800 px * 0.2 * 2"/px = 320" -> the nearest nice length is 300" = 5'
    assert bar[0].text == "5′"
    assert bar[0].tip == scale_bar_tip(300)


def test_grid_lines_say_which_coordinate_they_are():
    lines = [l for l in grid_lines(_grid_wcs(), (600, 800), "#888888") if l.label]
    ra = [l for l in lines if "h" in l.label]
    dec = [l for l in lines if "°" in l.label]
    assert ra and dec, "fixture must produce both kinds"
    assert all("right ascension" in l.tip and "east–west" in l.tip for l in ra)
    assert all("declination" in l.tip and "north–south" in l.tip for l in dec)
    assert all(l.label in l.tip for l in ra + dec), "the tip repeats the value it explains"


def test_the_compass_n_explains_north_and_east():
    prims = build_layout_for([], [], _grid_wcs(), (600, 800), 2.0, _layers(compass=True), "all")
    n = [p for p in prims if isinstance(p, Label) and p.text == "N"]
    assert len(n) == 1
    assert "north" in n[0].tip and "east is to the left" in n[0].tip


def test_tips_default_to_empty_so_old_callers_and_the_export_are_unchanged():
    assert Label("x", 0, 0, "#fff").tip == ""
    assert GridLine([(0, 0), (1, 1)], "#fff").tip == ""
