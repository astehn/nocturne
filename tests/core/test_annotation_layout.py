import math

import numpy as np
import pytest

from astropy.coordinates import SkyCoord
from astropy.wcs import WCS
import astropy.units as u

from nocturne.core.annotation_layout import (
    Circle, circle_for, colour_for, filter_by_density, grid_lines, place_labels, priority_of,
    star_marker, _fmt_ra)
from nocturne.core.catalog import CatalogObject, NamedStar


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
    m = _obj(1.0, name="M 39")
    plain = _obj(30.0, name="LDN 935")
    objs, _ = filter_by_density([m, plain], [], 2.0, "minimal")
    assert m in objs and plain not in objs


def test_density_filters_stars_by_magnitude():
    from nocturne.core.catalog import NamedStar
    bright = NamedStar("Deneb", 0, 0, 1.25, 10, 10)
    faint = NamedStar("Faint", 0, 0, 5.9, 20, 20)
    _, stars = filter_by_density([], [bright, faint], 2.0, "balanced")
    assert bright in stars and faint not in stars


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
    m = _obj(1.0, cx=100.0, cy=100.0, name="M 39")
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
    big_name = "M " + "Z" * 20                       # forces priority 40: placed first

    def _measure_big_then_small(text, size):
        if text == big_name:
            return (450.0, 150.0)                    # -> rect (250,270)-(700,420)
        return (7.0 * len(text), 14.0)

    big = _obj(1.0, cx=241.0, cy=345.0, name=big_name)
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
    raw_x, raw_y = wcs.world_to_pixel(SkyCoord(310.0 * u.deg, 44.0 * u.deg))
    expected_y = h - 1 - float(raw_y)          # FITS_Y_DOWN convention

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
