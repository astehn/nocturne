import math

import pytest

from nocturne.core.annotation_layout import Circle, circle_for, star_marker
from nocturne.core.catalog import CatalogObject, NamedStar


def _obj(major_arcmin, cx=100.0, cy=120.0, name="NGC 7000", common=""):
    return CatalogObject(name, common, 0.0, 0.0, major_arcmin, cx, cy, True, cx, cy)


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
