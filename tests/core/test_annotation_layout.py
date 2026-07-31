import math

import pytest

from nocturne.core.annotation_layout import (
    Circle, circle_for, filter_by_density, place_labels, priority_of, star_marker)
from nocturne.core.catalog import CatalogObject, NamedStar


def _obj(major_arcmin, cx=100.0, cy=120.0, name="NGC 7000", common=""):
    return CatalogObject(name, common, 0.0, 0.0, major_arcmin, cx, cy, True, cx, cy)


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
