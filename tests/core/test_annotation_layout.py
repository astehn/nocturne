import math

import numpy as np
import pytest

from astropy.coordinates import SkyCoord
from astropy.wcs import WCS
import astropy.units as u

from nocturne.core.annotation_layout import (
    Circle, GridLine, Label, Leader, Marker, build_layout_for, circle_for, colour_for,
    filter_by_density, grid_lines, place_labels, priority_of, star_marker, _fmt_ra, _is_messier)
from nocturne.core.catalog import CatalogObject, NamedStar, load_catalog


def _obj(major_arcmin, cx=100.0, cy=120.0, name="NGC 7000", common="", messier="", obj_type=""):
    return CatalogObject(name, common, 0.0, 0.0, major_arcmin, cx, cy, True, cx, cy,
                          obj_type=obj_type, messier=messier)


def _measure(text, size):
    return (7.0 * len(text), 14.0)        # deterministic stub: 7px per char


def test_circle_radius_is_the_objects_true_angular_half_extent():
    # 30' object at 2.0"/px -> (30*60/2)/2.0 = 450 px radius
    c = circle_for(_obj(30.0), pixscale_arcsec=2.0)
    assert c.r == pytest.approx(450.0)


def test_circle_is_centred_on_the_true_position_not_the_clamped_label_anchor():
    o = CatalogObject("NGC 7000", "", 0.0, 0.0, 30.0, 12.0, 40.0, True, -500.0, 40.0)
    c = circle_for(o, pixscale_arcsec=2.0)
    assert c.x == pytest.approx(-500.0), "a big off-frame nebula must draw its real arc"


def test_tiny_objects_get_the_minimum_radius_so_they_stay_visible():
    c = circle_for(_obj(0.1), pixscale_arcsec=2.0)    # 1.5 px true radius
    assert c.r == pytest.approx(6.0)
    assert c.dashed is False


def test_unknown_size_is_a_dashed_minimum_ring():
    c = circle_for(_obj(0.0), pixscale_arcsec=2.0)
    assert c.r == pytest.approx(6.0)
    assert c.dashed is True, "unknown size must look different from known-but-small"


def test_zero_pixel_scale_does_not_divide_by_zero():
    c = circle_for(_obj(30.0), pixscale_arcsec=0.0)
    assert c.r == pytest.approx(6.0) and c.dashed is True


def test_star_marker_leaves_the_star_itself_uncovered():
    m = star_marker(NamedStar("Deneb", 0.0, 0.0, 1.25, 50.0, 60.0))
    assert m.kind == "star"
    assert (m.x, m.y) == (50.0, 60.0)


def test_brighter_stars_get_a_larger_marker():
    bright = star_marker(NamedStar("Deneb", 0.0, 0.0, 1.25, 0.0, 0.0))
    faint = star_marker(NamedStar("Faint", 0.0, 0.0, 5.5, 0.0, 0.0))
    assert bright.size != faint.size


def test_messier_outranks_a_plain_catalogue_object():
    assert priority_of(_obj(10.0, name="M 31", common="Andromeda")) > \
           priority_of(_obj(10.0, name="NGC 6996", common=""))


def test_named_objects_outrank_anonymous_ones():
    assert priority_of(_obj(10.0, name="NGC 7000", common="North America")) > \
           priority_of(_obj(10.0, name="LDN 935", common=""))


def test_messier_priority_is_driven_by_the_messier_column_not_a_name_prefix():
    # Regression: the bundled OpenNGC data never renames `name` to "M 31" (it
    # keeps the NGC/IC designation), so an "M "-prefixed name alone must NOT
    # earn the Messier priority tier -- only a populated `messier` column does.
    assert priority_of(_obj(1.0, name="M 999")) == 20
    assert priority_of(_obj(1.0, name="NGC 224", messier="31")) == 40


def test_is_messier_detects_a_meaningful_number_of_real_catalogue_objects():
    # The original _is_messier tested an "M "-prefixed `name`, which matched
    # ZERO rows in the real bundled catalogue (OpenNGC never renames `name`
    # to a Messier alias) -- so the Messier priority tier never once fired on
    # real data, only on synthetic fixtures using a fake "M ..." name. This
    # pins the behaviour to the actual bundled catalogue, not a test double:
    # it fails against the old name-prefix logic and passes against the
    # messier-column logic.
    rows = load_catalog()
    messier_rows = [r for r in rows if r[8]]
    assert len(messier_rows) >= 100, len(messier_rows)

    andromeda = next(r for r in rows if r[0] == "NGC0224")
    obj = _obj(andromeda[4], name=andromeda[0], common=andromeda[1], messier=andromeda[8])
    assert _is_messier(obj)


def test_colour_is_the_default_green_when_type_colouring_is_off():
    assert colour_for(_obj(1.0, name="NGC 224", messier="31"), by_type=False) == "#5cff5c"


def test_messier_objects_are_violet_when_colouring_by_type():
    c = colour_for(_obj(1.0, name="NGC 224", common="Andromeda", messier="31"), by_type=True)
    assert c.lower() != "#5cff5c"
    assert c.lower() == "#b38cff"


def test_each_type_family_gets_its_own_colour():
    fams = {}
    for t in ("HII", "DrkN", "PN", "G", "OCl"):
        o = _obj(1.0, name="NGC 1", obj_type=t)
        fams[t] = colour_for(o, by_type=True)
    assert len(set(fams.values())) >= 4, fams


def test_unknown_type_falls_back_to_a_neutral_colour_not_a_crash():
    o = _obj(1.0, name="NGC 1", obj_type="")
    assert colour_for(o, by_type=True)


def test_place_labels_prefers_the_messier_designation_when_present():
    obj = _obj(1.0, cx=100.0, cy=100.0, name="NGC 224", common="Andromeda Galaxy", messier="31")
    labels, _ = place_labels([obj], (600, 800), _measure)
    assert labels[0].text.startswith("M 31"), labels[0].text
    assert "Andromeda Galaxy" in labels[0].text


def test_place_labels_falls_back_to_catalogue_name_without_a_messier_number():
    obj = _obj(1.0, cx=100.0, cy=100.0, name="NGC 7000", common="North America Nebula")
    labels, _ = place_labels([obj], (600, 800), _measure)
    assert labels[0].text.startswith("NGC 7000"), labels[0].text


def test_balanced_density_drops_objects_below_the_size_threshold():
    big = _obj(30.0)                        # 450 px radius at 2"/px
    tiny = _obj(0.2, name="NGC 1")          # 3 px radius -> below 8
    objs, _ = filter_by_density([big, tiny], [], 2.0, "balanced")
    assert big in objs and tiny not in objs


def test_balanced_density_keeps_a_small_object_that_has_a_common_name():
    tiny_named = _obj(0.2, name="NGC 1", common="Something")
    objs, _ = filter_by_density([tiny_named], [], 2.0, "balanced")
    assert tiny_named in objs


def test_all_density_keeps_everything():
    tiny = _obj(0.2, name="NGC 1")
    objs, _ = filter_by_density([tiny], [], 2.0, "all")
    assert objs == [tiny]


def test_minimal_density_keeps_only_messier_and_named():
    m = _obj(1.0, name="NGC 7092", messier="39")   # M 39's real OpenNGC designation
    plain = _obj(30.0, name="LDN 935")
    objs, _ = filter_by_density([m, plain], [], 2.0, "minimal")
    assert m in objs and plain not in objs


def test_density_filters_stars_by_magnitude():
    from nocturne.core.catalog import NamedStar
    bright = NamedStar("Deneb", 0, 0, 1.25, 10, 10)
    faint = NamedStar("Faint", 0, 0, 8.5, 20, 20)      # past the naked-eye limit
    _, stars = filter_by_density([], [bright, faint], 2.0, "balanced")
    assert bright in stars and faint not in stars


def test_balanced_density_keeps_a_naked_eye_star():
    # A 2-3 degree field holds very few bright stars: NGC 7000's has exactly one
    # (57 Cyg, mag 4.78). A tighter cut made the "Named stars" toggle look broken.
    from nocturne.core.catalog import NamedStar
    _, stars = filter_by_density([], [NamedStar("57 Cyg", 0, 0, 4.78, 10, 10)],
                                 2.0, "balanced")
    assert stars, "the default density must show a naked-eye named star"


def test_placed_labels_never_overlap():
    objs = [_obj(1.0, cx=100.0, cy=100.0, name="AAA"),
            _obj(1.0, cx=104.0, cy=102.0, name="BBB"),
            _obj(1.0, cx=108.0, cy=104.0, name="CCC")]
    labels, _ = place_labels(objs, (600, 800), _measure)
    rects = [(l.x, l.y, l.x + 7.0 * len(l.text), l.y + 14.0) for l in labels]
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            overlap = not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
            assert not overlap, "labels must not be placed on top of each other"


def test_labels_stay_inside_the_frame():
    objs = [_obj(1.0, cx=795.0, cy=595.0, name="EDGE OBJECT")]
    labels, _ = place_labels(objs, (600, 800), _measure)
    for l in labels:
        assert l.x >= 0 and l.y >= 0
        assert l.x + 7.0 * len(l.text) <= 800 and l.y + 14.0 <= 600


def test_a_displaced_label_gets_a_leader_line():
    crowd = [_obj(1.0, cx=100.0 + i * 2.0, cy=100.0, name=f"OBJ{i}") for i in range(6)]
    labels, leaders = place_labels(crowd, (600, 800), _measure)
    assert leaders, "a label pushed away from its object must be connected to it"


def test_higher_priority_labels_are_placed_first():
    m = _obj(1.0, cx=100.0, cy=100.0, name="NGC 7092", messier="39")   # M 39's real designation
    plain = _obj(1.0, cx=101.0, cy=100.0, name="LDN 935")
    labels, _ = place_labels([plain, m], (600, 800), _measure)
    assert labels[0].text.startswith("M 39"), "priority order, not input order"


def test_a_label_wider_than_the_frame_is_pinned_not_pushed_negative():
    # 60-char name -> 420 px wide via _measure, on a 300x300 frame: wider than
    # the frame itself. The clamp must pin to 0, never go negative.
    objs = [_obj(1.0, cx=150.0, cy=150.0, name="A" * 60)]
    labels, _ = place_labels(objs, (300, 300), _measure)
    assert labels, "label should still be placed, just pinned to the edge"
    for l in labels:
        assert l.x >= 0 and l.y >= 0


def test_label_search_finds_free_space_beyond_an_occupied_diagonal():
    # One big label placed dead centre of an otherwise empty 800x600 frame
    # occupies exactly (250,270)-(700,420). A second object's four primary
    # anchors all land inside that occupied rect, so it must fall back to the
    # outward search — which must look in every direction, not just
    # right-and-down, to find the free space that surrounds the rectangle.
    big_text = "M 1"                                  # M 1 = NGC 1952 (Crab Nebula); forces priority 40: placed first

    def _measure_big_then_small(text, size):
        if text == big_text:
            return (450.0, 150.0)                    # -> rect (250,270)-(700,420)
        return (7.0 * len(text), 14.0)

    big = _obj(1.0, cx=241.0, cy=345.0, name="NGC 1952", messier="1")
    small = _obj(1.0, cx=400.0, cy=300.0, name="LDN 1")  # all 4 primary anchors land inside big's rect
    labels, leaders = place_labels([small, big], (600, 800), _measure_big_then_small)
    small_labels = [l for l in labels if l.text == "LDN 1"]
    assert small_labels, "free space exists around the occupied rectangle; label must not be dropped"
    assert leaders, "a label pushed off its primary anchors must be connected by a leader"


def _grid_wcs(ra=310.0, dec=44.0, scale_deg=0.001, w=800, h=600):
    k = WCS(naxis=2)
    k.wcs.crpix = [w / 2, h / 2]
    k.wcs.crval = [ra, dec]
    k.wcs.cdelt = [-scale_deg, scale_deg]
    k.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return k


def test_grid_produces_lines_across_the_frame():
    lines = grid_lines(_grid_wcs(), (600, 800), "#888888")
    assert lines, "a solved frame should yield grid lines"
    assert all(len(l.points) >= 2 for l in lines)


def test_grid_lines_carry_a_readable_label():
    lines = grid_lines(_grid_wcs(), (600, 800), "#888888")
    assert any(l.label for l in lines)
    for l in lines:
        if l.label:
            assert any(mark in l.label for mark in ("h", "°", "′")), l.label


def test_grid_points_lie_inside_the_frame():
    for l in grid_lines(_grid_wcs(), (600, 800), "#888888"):
        for x, y in l.points:
            assert -1 <= x <= 801 and -1 <= y <= 601


def test_grid_of_an_unusable_wcs_is_empty_not_an_exception():
    assert grid_lines(None, (600, 800), "#888888") == []


def _asymmetric_grid_wcs(w=800, h=600):
    # crpix well off-centre and a crval whose Dec (44 deg) is offset from the
    # frame centre: a FITS_Y_DOWN sign flip must move the "+44°" line by
    # ~(h - 1 - 2*raw_y) px, not leave it near where it already was, the way
    # a centred fixture would (its raw y sits near h/2, so h-1-y ~= y).
    k = WCS(naxis=2)
    k.wcs.crpix = [w * 0.25, h * 0.75]
    k.wcs.crval = [310.0, 44.0]
    k.wcs.cdelt = [-0.001, 0.001]
    k.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return k


def test_grid_dec_line_position_matches_fits_y_down_convention():
    # Independently project the WCS reference point (RA 310, Dec 44) exactly
    # the way core/catalog.py:97 does, then require the "+44 deg" grid line
    # (which passes through that Dec) to sit at that same screen y. An
    # inverted FITS_Y_DOWN sign would place it ~299 px away instead.
    w, h = 800, 600
    wcs = _asymmetric_grid_wcs(w, h)
    from nocturne.tools.astap import FITS_Y_DOWN
    raw_x, raw_y = wcs.world_to_pixel(SkyCoord(310.0 * u.deg, 44.0 * u.deg))
    # Derived from the constant rather than hard-coding a flip: this test exists
    # to prove the GRID agrees with core/catalog's object projection, whichever
    # convention that is. Hard-coding it made the test restate the bug when the
    # constant turned out to be wrong (corrected 2026-07-31 against a real solve).
    expected_y = (h - 1 - float(raw_y)) if FITS_Y_DOWN else float(raw_y)

    lines = grid_lines(wcs, (h, w), "#888888")
    dec_44 = next(l for l in lines if l.label == "+44°")
    ys = [p[1] for p in dec_44.points]
    assert all(abs(y - expected_y) < 15.0 for y in ys), (ys, expected_y)


def test_grid_lines_are_not_axis_transposed():
    # A constant-Dec line must sweep in x while staying near one y (it is
    # horizontal-ish); a constant-RA line must sweep in y while staying near
    # one x (vertical-ish). A transposed sampling loop, or a _fmt_ra/_fmt_dec
    # mix-up, would blur or invert this and is caught here.
    w, h = 800, 600
    wcs = _asymmetric_grid_wcs(w, h)
    lines = grid_lines(wcs, (h, w), "#888888")

    dec_lines = [l for l in lines if "°" in l.label]
    ra_lines = [l for l in lines if "h" in l.label]
    assert dec_lines and ra_lines

    for l in dec_lines:
        xs = [p[0] for p in l.points]
        ys = [p[1] for p in l.points]
        assert max(xs) - min(xs) > 100, "a Dec line should sweep across x"
        assert max(ys) - min(ys) < 20, "a Dec line should stay near one y"

    for l in ra_lines:
        xs = [p[0] for p in l.points]
        ys = [p[1] for p in l.points]
        assert max(ys) - min(ys) > 100, "an RA line should sweep across y"
        assert max(xs) - min(xs) < 20, "an RA line should stay near one x"


def test_fmt_ra_wraps_the_hour_not_just_the_minute():
    assert _fmt_ra(359.99) == "0h00m", "a minute-carry at 23h60m must wrap to 0h"
    assert _fmt_ra(-0.001) == "0h00m"
    assert _fmt_ra(180.0) == "12h00m"


def _layers(**over):
    base = {"objects": False, "stars": False, "grid": False, "compass": False,
            "scale": False, "by_type": False}
    base.update(over)
    return base


def test_build_layout_for_ui_scale_reserves_labels_at_the_scale_they_render():
    # PS-07 recurring one level up: place_labels' collision avoidance is only
    # valid if the box it reserves matches the box the CONSUMING adapter
    # actually renders. build_layout_for's default measure must scale with
    # ui_scale exactly the way the export adapter's text size does (1.8x is
    # roughly what a 3840px-wide Seestar export gets against the 1200px
    # baseline) -- otherwise labels that "don't overlap" at layout time
    # overlap once rendered bigger.
    from nocturne.core.annotation_layout import _default_measure
    objs = [_obj(1.0, cx=100.0 + i * 6.0, cy=100.0, name=f"NGC {7000 + i}", common=f"Nebula {i}")
            for i in range(8)]
    prims = build_layout_for(objs, [], None, (600, 800), 2.0,
                              _layers(objects=True), "all", ui_scale=1.8)
    labels = [p for p in prims if isinstance(p, Label)]
    assert len(labels) >= 2, "the crowded cluster must force the collision-avoidance search"
    rects = []
    for l in labels:
        tw, th = _default_measure(l.text, l.size, 1.8)
        rects.append((l.x, l.y, l.x + tw, l.y + th))
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            overlap = not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
            assert not overlap, \
                "labels reserved for ui_scale=1.8 must not overlap when measured at that scale"


def test_build_layout_for_produces_a_circle_and_label_per_kept_object():
    obj = _obj(30.0, cx=100.0, cy=100.0, name="NGC 7000", common="North America")
    prims = build_layout_for([obj], [], None, (600, 800), 2.0,
                              _layers(objects=True), "all", measure=_measure)
    assert any(isinstance(p, Circle) for p in prims)
    assert any(isinstance(p, Label) and "NGC 7000" in p.text for p in prims)


def test_build_layout_for_objects_layer_off_drops_circles_and_object_labels():
    obj = _obj(30.0, cx=100.0, cy=100.0, name="NGC 7000", common="North America")
    prims = build_layout_for([obj], [], None, (600, 800), 2.0,
                              _layers(objects=False), "all", measure=_measure)
    assert not any(isinstance(p, (Circle, Label)) for p in prims)


def test_build_layout_for_stars_layer_on_yields_a_star_marker():
    star = NamedStar("Deneb", 0.0, 0.0, 1.25, 50.0, 60.0)
    prims = build_layout_for([], [star], None, (600, 800), 2.0,
                              _layers(stars=True), "all", measure=_measure)
    markers = [p for p in prims if isinstance(p, Marker) and p.kind == "star"]
    assert markers and (markers[0].x, markers[0].y) == (50.0, 60.0)


def test_build_layout_for_stars_layer_off_yields_no_star_marker():
    star = NamedStar("Deneb", 0.0, 0.0, 1.25, 50.0, 60.0)
    prims = build_layout_for([], [star], None, (600, 800), 2.0,
                              _layers(stars=False), "all", measure=_measure)
    assert not any(isinstance(p, Marker) for p in prims)


def test_build_layout_for_gives_a_named_star_a_label():
    star = NamedStar("Deneb", 0.0, 0.0, 1.25, 50.0, 60.0)
    prims = build_layout_for([], [star], None, (600, 800), 2.0,
                              _layers(stars=True), "all", measure=_measure)
    assert any(isinstance(p, Label) and p.text == "Deneb" for p in prims)


def test_by_type_gives_a_named_star_the_star_palette_colour():
    star = NamedStar("Deneb", 0.0, 0.0, 1.25, 50.0, 60.0)
    prims = build_layout_for([], [star], None, (600, 800), 2.0,
                              _layers(stars=True, by_type=True), "all", measure=_measure)
    marker = next(p for p in prims if isinstance(p, Marker))
    label = next(p for p in prims if isinstance(p, Label) and p.text == "Deneb")
    assert marker.colour == label.colour == "#ffd75e"


def test_by_type_off_keeps_the_default_colour_for_a_named_star():
    star = NamedStar("Deneb", 0.0, 0.0, 1.25, 50.0, 60.0)
    prims = build_layout_for([], [star], None, (600, 800), 2.0,
                              _layers(stars=True, by_type=False), "all", measure=_measure)
    marker = next(p for p in prims if isinstance(p, Marker))
    label = next(p for p in prims if isinstance(p, Label) and p.text == "Deneb")
    assert marker.colour == label.colour == "#5cff5c"


def test_build_layout_for_grid_layer_on_includes_grid_lines():
    prims = build_layout_for([], [], _grid_wcs(), (600, 800), 2.0,
                              _layers(grid=True), "all", measure=_measure)
    assert any(isinstance(p, GridLine) for p in prims)


def test_build_layout_for_grid_layer_off_yields_no_grid_lines():
    prims = build_layout_for([], [], _grid_wcs(), (600, 800), 2.0,
                              _layers(grid=False), "all", measure=_measure)
    assert not any(isinstance(p, GridLine) for p in prims)


def test_build_layout_for_compass_and_scale_layers_add_their_own_primitives():
    prims = build_layout_for([], [], _grid_wcs(), (600, 800), 2.0,
                              _layers(compass=True, scale=True), "all", measure=_measure)
    assert any(isinstance(p, Label) and p.text == "N" for p in prims), "compass needs its N label"
    assert any(isinstance(p, Label) and p.text not in ("N", "") for p in prims), \
        "scale bar needs a length label"
    assert any(isinstance(p, Leader) for p in prims), \
        "compass arrow and scale bar are both drawn as Leader lines"


def test_compass_arrow_leader_is_screen_fixed():
    prims = build_layout_for([], [], _grid_wcs(), (600, 800), 2.0,
                              _layers(compass=True), "all", measure=_measure)
    leaders = [p for p in prims if isinstance(p, Leader)]
    assert leaders and any(l.screen_fixed for l in leaders), \
        "the compass arrow is a cosmetic HUD indicator, not a measured line"


def test_scale_bar_leader_is_not_screen_fixed():
    prims = build_layout_for([], [], _grid_wcs(), (600, 800), 2.0,
                              _layers(scale=True), "all", measure=_measure)
    leaders = [p for p in prims if isinstance(p, Leader)]
    assert leaders and all(not l.screen_fixed for l in leaders), \
        "the scale bar's length is truthful and must scale with zoom like any measured line"


def test_by_type_colouring_gives_different_label_colours_per_object_type():
    messier = _obj(10.0, cx=100.0, cy=100.0, name="NGC 224", common="Andromeda", messier="31")
    hii = _obj(10.0, cx=400.0, cy=400.0, name="NGC 7000", common="North America", obj_type="HII")
    prims = build_layout_for([messier, hii], [], None, (600, 800), 2.0,
                              _layers(objects=True, by_type=True), "all", measure=_measure)
    labels = [p for p in prims if isinstance(p, Label)]
    messier_label = next(l for l in labels if "M 31" in l.text)
    hii_label = next(l for l in labels if "NGC 7000" in l.text)
    assert messier_label.colour != hii_label.colour, "by-type colouring must reach the label text"


def test_by_type_colouring_off_gives_every_label_the_same_colour():
    messier = _obj(10.0, cx=100.0, cy=100.0, name="NGC 224", common="Andromeda", messier="31")
    hii = _obj(10.0, cx=400.0, cy=400.0, name="NGC 7000", common="North America", obj_type="HII")
    prims = build_layout_for([messier, hii], [], None, (600, 800), 2.0,
                              _layers(objects=True, by_type=False), "all", measure=_measure)
    labels = [p for p in prims if isinstance(p, Label)]
    messier_label = next(l for l in labels if "M 31" in l.text)
    hii_label = next(l for l in labels if "NGC 7000" in l.text)
    assert messier_label.colour == hii_label.colour == "#5cff5c"


def test_by_type_colouring_also_reaches_the_circle_not_just_the_label():
    messier = _obj(10.0, cx=100.0, cy=100.0, name="NGC 224", common="Andromeda", messier="31")
    hii = _obj(10.0, cx=400.0, cy=400.0, name="NGC 7000", common="North America", obj_type="HII")
    prims = build_layout_for([messier, hii], [], None, (600, 800), 2.0,
                              _layers(objects=True, by_type=True), "all", measure=_measure)
    circles = [p for p in prims if isinstance(p, Circle)]
    assert len(circles) == 2
    # Assert the WIRING, not the palette's current hues: each circle carries the
    # colour colour_for resolves for its own object, and the two differ. Pinning
    # literal hex here made a legitimate palette change fail a test about routing.
    by_x = {c.x: c.colour for c in circles}
    assert by_x[100.0] == colour_for(messier, by_type=True)
    assert by_x[400.0] == colour_for(hii, by_type=True)
    assert by_x[100.0] != by_x[400.0], "type colouring must actually distinguish types"


# --- reserved boxes must match what is actually drawn -------------------------

class _Obj:
    def __init__(self, name, x, y):
        self.name, self.x, self.y = name, x, y
        self.common = ""; self.major_arcmin = 0.0; self.messier = ""
        self.cx, self.cy = x, y


def _screen_overlaps(labels, measure, zoom):
    """Overlapping pairs in SCREEN space — what the user actually sees. Labels are
    positioned in image coordinates but rendered at a constant screen size."""
    boxes = []
    for L in labels:
        tw, th = measure(L.text, L.size)
        boxes.append((L.x * zoom, L.y * zoom, L.x * zoom + tw, L.y * zoom + th))
    n = 0
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]):
                n += 1
    return n


def test_labels_do_not_overlap_on_screen_when_the_image_is_zoomed_out():
    """Found on a real IC 1396A frame: 39 objects at fit zoom (~0.31) printed
    straight through each other — "LDN 1109" and "LDN 1110" rendered as
    "LDND1N1110" — despite place_labels' "no room: drop, never overlap" rule.

    The rule was sound; it was guarding the wrong rectangle. Collision detection
    runs in IMAGE coordinates while labels render at a constant SCREEN size, so
    at zoom Z a label covers tw/Z image px against a box reserving tw. Passing
    ui_scale=1/Z converts screen sizes into the space the placement runs in.
    """
    import random
    random.seed(3)
    objs = [_Obj(f"LDN {1085+i}", random.uniform(200, 1960), random.uniform(300, 3540))
            for i in range(39)]
    shape = (3840, 2160)
    zoom = 0.31
    base = _measure                      # module-level test measure, screen px

    wrong, _ = place_labels(objs, shape, base, ui_scale=1.0)
    right, _ = place_labels(
        objs, shape,
        lambda t, s: tuple(v / zoom for v in base(t, s)), ui_scale=1.0 / zoom)

    assert _screen_overlaps(wrong, base, zoom) > 0, \
        "fixture no longer reproduces the bug — it must overlap at ui_scale=1.0"
    assert _screen_overlaps(right, base, zoom) == 0, \
        "reserved boxes still do not match what is drawn"


def test_at_100_percent_zoom_the_two_agree():
    """The bug only exists below 1:1 — the sanity check that the fix is a
    coordinate conversion, not a fudge factor."""
    objs = [_Obj("LDN 1109", 100, 100), _Obj("LDN 1110", 180, 110)]
    a, _ = place_labels(objs, (400, 400), _measure, ui_scale=1.0)
    b, _ = place_labels(objs, (400, 400), _measure, ui_scale=1.0)
    assert [(l.x, l.y) for l in a] == [(l.x, l.y) for l in b]
