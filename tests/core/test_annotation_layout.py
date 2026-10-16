import math

import numpy as np
import pytest

from astropy.coordinates import SkyCoord
from astropy.wcs import WCS
import astropy.units as u

from nocturne.core.annotation_layout import (
    Circle, GridLine, Label, Leader, Marker, build_layout_for, circle_for,
    filter_by_density, grid_lines, priority_of, star_marker, _is_messier)
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




def _layers(**over):
    base = {"objects": False, "stars": False, "grid": False, "compass": False,
            "scale": False, "by_type": False}
    base.update(over)
    return base




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






def test_build_layout_for_grid_layer_on_includes_grid_lines():
    prims = build_layout_for([], [], _grid_wcs(), (600, 800), 2.0,
                              _layers(grid=True), "all", measure=_measure)
    assert any(isinstance(p, GridLine) for p in prims)


def test_build_layout_for_grid_layer_off_yields_no_grid_lines():
    prims = build_layout_for([], [], _grid_wcs(), (600, 800), 2.0,
                              _layers(grid=False), "all", measure=_measure)
    assert not any(isinstance(p, GridLine) for p in prims)






def test_scale_bar_leader_is_not_screen_fixed():
    prims = build_layout_for([], [], _grid_wcs(), (600, 800), 2.0,
                              _layers(scale=True), "all", measure=_measure)
    leaders = [p for p in prims if isinstance(p, Leader)]
    assert leaders and all(not l.screen_fixed for l in leaders), \
        "the scale bar's length is truthful and must scale with zoom like any measured line"


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


def _boxes_overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _box(l):
    return (l.x, l.y, l.x + l.w, l.y + l.h)


def test_labels_do_not_overlap_on_screen_when_the_image_is_zoomed_out():
    """Found on a real IC 1396A frame: 39 objects at fit zoom (~0.31) printed
    straight through each other — "LDN 1109" and "LDN 1110" rendered as
    "LDND1N1110". Collision detection runs in IMAGE coordinates while labels
    render at a constant SCREEN size, so the live canvas passes ui_scale=1/Z
    and a measure that returns screen sizes / Z."""
    import random
    random.seed(3)
    objs = [_Obj(f"LDN {1085+i}", random.uniform(200, 1960), random.uniform(300, 3540))
            for i in range(39)]
    shape = (3840, 2160)
    zoom = 0.31
    prims = build_layout_for(objs, [], None, shape, 2.0, _layers(objects=True), "all",
                             measure=lambda t, s: tuple(v / zoom for v in _measure(t, s)),
                             ui_scale=1.0 / zoom)
    labels = [p for p in prims if isinstance(p, Label)]
    assert len(labels) >= 10, "fixture must still be crowded enough to matter"
    assert _screen_overlaps(labels, _measure, zoom) == 0


# --- the restyle (spec 2026-10-15-solve-restyle) -------------------------------

from nocturne.core.annotation_layout import (  # noqa: E402
    GRID_LINE_COLOUR, MAJOR_COLOUR, MINOR_COLOUR, STAR_COLOUR, STAR_RETICLE,
    _fmt_dec, _fmt_ra, merge_aliases, ra_parts, tier_of, _place_grid_labels)
from nocturne.core.catalog import CatalogObject  # noqa: E402,F811


@pytest.mark.parametrize("name, messier, common, tier", [
    ("NGC 6611", "16", "Eagle Nebula", "major"),
    ("NGC 7000", "", "North America Nebula", "major"),
    ("NGC 896", "", "", "major"),
    ("IC 1805", "", "", "major"),
    ("LDN 935", "", "", "minor"),
    ("B 33", "", "", "minor"),
    ("Sh 2-131", "", "", "minor"),
    ("vdB 141", "", "", "minor"),
    ("Sh 2-155", "", "Cave Nebula", "major"),     # a common name lifts any catalogue
    ("vdB 142", "", "Elephant's Trunk Nebula", "major"),
])
def test_tier_follows_catalogue_prefix_and_common_name(name, messier, common, tier):
    assert tier_of(_obj(1.0, name=name, messier=messier, common=common)) == tier


def test_a_named_star_is_its_own_tier():
    assert tier_of(NamedStar("Deneb", 0.0, 0.0, 1.25, 50.0, 60.0)) == "star"


def test_tier_colours_reach_label_and_circle():
    major = _obj(10.0, cx=150.0, cy=150.0, name="NGC 7000")
    minor = _obj(10.0, cx=550.0, cy=400.0, name="LDN 935")
    prims = build_layout_for([major, minor], [], None, (600, 800), 2.0,
                             _layers(objects=True), "all", measure=_measure)
    labels = {p.text: p for p in prims if isinstance(p, Label)}
    circles = {p.x: p for p in prims if isinstance(p, Circle)}
    assert labels["NGC 7000"].colour == MAJOR_COLOUR and labels["NGC 7000"].tier == "major"
    assert labels["LDN 935"].colour == MINOR_COLOUR and labels["LDN 935"].tier == "minor"
    assert labels["NGC 7000"].size == "major" and labels["LDN 935"].size == "minor"
    # rings: the label's hue, slightly transparent (#AARRGGBB)
    for x, want in ((150.0, MAJOR_COLOUR), (550.0, MINOR_COLOUR)):
        c = circles[x]
        assert len(c.colour) == 9 and c.colour[3:].lower() == want[1:].lower()
        assert int(c.colour[1:3], 16) < 255
    assert circles[150.0].tier == "major" and circles[550.0].tier == "minor"


def test_by_type_is_accepted_and_changes_nothing():
    objs = [_obj(10.0, cx=150.0, cy=150.0, name="NGC 224", common="Andromeda", messier="31",
                 obj_type="G"),
            _obj(10.0, cx=550.0, cy=400.0, name="NGC 7000", obj_type="HII"),
            _obj(0.2, cx=250.0, cy=450.0, name="LDN 1", obj_type="DrkN")]   # only "all" keeps it
    stars = [NamedStar("Deneb", 0.0, 0.0, 1.25, 400.0, 100.0),
             NamedStar("Faint", 0.0, 0.0, 7.5, 650.0, 200.0)]
    before = build_layout_for(objs, stars, _grid_wcs(), (600, 800), 2.0,
                              _layers(objects=True, stars=True, grid=True), "all", measure=_measure)
    assert len([p for p in before if isinstance(p, Circle)]) == 3 and \
        len([p for p in before if isinstance(p, Marker)]) == 2, "fixture must reach every branch"
    after = build_layout_for(objs, stars, _grid_wcs(), (600, 800), 2.0,
                             _layers(objects=True, stars=True, grid=True, by_type=True), "all",
                             measure=_measure)
    assert after == before, "an old setting with by_type on must not alter the overlay"


def test_the_common_name_is_a_second_line():
    o = _obj(1.0, cx=300.0, cy=300.0, name="IC 1805", common="Heart Nebula")
    prims = build_layout_for([o], [], None, (600, 800), 2.0, _layers(objects=True), "all",
                             measure=_measure)
    (l,) = [p for p in prims if isinstance(p, Label)]
    assert (l.text, l.sub, l.sub_size) == ("IC 1805", "Heart Nebula", "major_common")
    assert l.w == pytest.approx(max(7.0 * len("IC 1805"), 7.0 * len("Heart Nebula")))
    assert l.h == pytest.approx(28.0), "two measured lines stacked"


def test_messier_designation_is_the_label():
    o = _obj(1.0, cx=300.0, cy=300.0, name="NGC 224", common="Andromeda Galaxy", messier="31")
    prims = build_layout_for([o], [], None, (600, 800), 2.0, _layers(objects=True), "all",
                             measure=_measure)
    (l,) = [p for p in prims if isinstance(p, Label)]
    assert l.text == "M 31" and l.sub == "Andromeda Galaxy"


def test_no_leader_is_ever_emitted_for_object_or_star_labels():
    crowd = [_obj(1.0, cx=100.0 + i * 2.0, cy=100.0, name=f"NGC {i}") for i in range(12)]
    stars = [NamedStar(f"S{i}", 0.0, 0.0, 2.0, 120.0 + i * 3, 110.0) for i in range(4)]
    prims = build_layout_for(crowd, stars, None, (600, 800), 2.0,
                             _layers(objects=True, stars=True), "all", measure=_measure)
    assert not any(isinstance(p, Leader) for p in prims)


def test_a_label_that_cannot_fit_is_dropped_never_overlapped():
    crowd = [_obj(1.0, cx=100.0 + i * 2.0, cy=100.0, name=f"NGC {i}") for i in range(12)]
    prims = build_layout_for(crowd, [], None, (600, 800), 2.0,
                             _layers(objects=True), "all", measure=_measure)
    labels = [p for p in prims if isinstance(p, Label)]
    assert 0 < len(labels) < 12, "some fit around the clump, the rest are dropped"
    assert len([p for p in prims if isinstance(p, Circle)]) == 12, "every ring still drawn"
    boxes = [_box(l) for l in labels]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert not _boxes_overlap(a, b)


def test_a_label_sits_against_its_circle():
    o = _obj(4.0, cx=400.0, cy=300.0, name="NGC 896")       # r = 60 px at 2"/px
    prims = build_layout_for([o], [], None, (600, 800), 2.0, _layers(objects=True), "all",
                             measure=_measure)
    (l,) = [p for p in prims if isinstance(p, Label)]
    # nearest point of the label box to the centre: just outside the ring
    nx = min(max(400.0, l.x), l.x + l.w)
    ny = min(max(300.0, l.y), l.y + l.h)
    d = math.hypot(nx - 400.0, ny - 300.0)
    assert 60.0 <= d <= 60.0 + 12.0, d


@pytest.mark.parametrize("major_arcmin, inside", [(4.9, True), (4.7, False)])
def test_a_label_goes_inside_a_circle_wider_than_12_percent_of_the_short_side(major_arcmin, inside):
    # 600 px short side: 12% = 72 px. At 2"/px, 4.9' -> r 73.5 px (inside), 4.7' -> 70.5 (outside).
    o = _obj(major_arcmin, cx=400.0, cy=300.0, name="IC 1805", common="Heart Nebula")
    prims = build_layout_for([o], [], None, (600, 800), 2.0, _layers(objects=True), "all",
                             measure=_measure)
    (l,) = [p for p in prims if isinstance(p, Label)]
    centred = (l.x + l.w / 2, l.y + l.h / 2) == (pytest.approx(400.0), pytest.approx(300.0))
    assert centred is inside


def test_a_small_circle_keeps_its_label_outside():
    o = _obj(4.0, cx=400.0, cy=300.0, name="NGC 896")       # r = 60 px < 0.12 * 600
    prims = build_layout_for([o], [], None, (600, 800), 2.0, _layers(objects=True), "all",
                             measure=_measure)
    (l,) = [p for p in prims if isinstance(p, Label)]
    assert not _boxes_overlap(_box(l), (340.0, 240.0, 460.0, 360.0))


def test_labels_stay_inside_the_frame():
    objs = [_obj(1.0, cx=795.0, cy=595.0, name="EDGE OBJECT"),
            _obj(1.0, cx=2.0, cy=3.0, name="NGC 1", common="Corner Nebula")]
    prims = build_layout_for(objs, [], None, (600, 800), 2.0, _layers(objects=True), "all",
                             measure=_measure)
    labels = [p for p in prims if isinstance(p, Label)]
    assert len(labels) == 2
    for l in labels:
        assert l.x >= 0 and l.y >= 0 and l.x + l.w <= 800 and l.y + l.h <= 600


def test_a_major_gets_the_first_spot_before_a_larger_minor():
    """Same priority (both anonymous); the LDN is bigger, the NGC is major. The
    first placed takes the preferred spot (right of the ring), whatever the
    input order."""
    minor = _obj(2.4, cx=300.0, cy=300.0, name="LDN 935")   # r 36 px; rings >= 30 px are
    major = _obj(2.0, cx=300.0, cy=300.0, name="NGC 1")     # not obstacles, so both can label
    assert priority_of(minor) == priority_of(major)
    prims = build_layout_for([minor, major], [], None, (600, 800), 2.0,
                             _layers(objects=True), "all", measure=_measure)
    labels = {p.text: p for p in prims if isinstance(p, Label)}
    assert labels["NGC 1"].x > 300.0 and labels["LDN 935"].x + labels["LDN 935"].w <= 300.0 + 1e-6


# --- alias merge ---------------------------------------------------------------

def _eagle_pair():
    m16 = _obj(120.0, cx=400.0, cy=300.0, name="NGC 6611", common="Eagle Nebula", messier="16")
    ic = _obj(5.05, cx=430.0, cy=280.0, name="IC 4703", common="Eagle Nebula")
    return m16, ic


def test_aliases_of_one_object_become_one_label():
    m16, ic = _eagle_pair()
    prims = build_layout_for([ic, m16], [], None, (2000, 2000), 2.0,
                             _layers(objects=True), "all", measure=_measure)
    labels = [p for p in prims if isinstance(p, Label)]
    assert [(l.text, l.sub) for l in labels] == [("M 16 · IC 4703", "Eagle Nebula")]
    assert len([p for p in prims if isinstance(p, Circle)]) == 2, "both rings stay"


def test_merge_groups_by_representative():
    m16, ic = _eagle_pair()
    groups = merge_aliases([ic, m16], 2.0)
    assert len(groups) == 1 and groups[0][0] is m16 and groups[0][1] == [m16, ic]


def test_a_near_pair_with_different_names_stays_two():
    a = _obj(20.0, cx=400.0, cy=300.0, name="NGC 6992", common="Eastern Veil")
    b = _obj(20.0, cx=420.0, cy=300.0, name="NGC 6960", common="Western Veil")
    c = _obj(20.0, cx=380.0, cy=300.0, name="NGC 1")         # anonymous: never merged
    d = _obj(20.0, cx=390.0, cy=300.0, name="NGC 2")
    assert len(merge_aliases([a, b, c, d], 2.0)) == 4


def test_the_same_name_far_apart_stays_two():
    a = _obj(1.0, cx=100.0, cy=100.0, name="B 142", common="Barnard's E Nebula")
    b = _obj(1.0, cx=900.0, cy=900.0, name="B 143", common="Barnard's E Nebula")
    assert len(merge_aliases([a, b], 2.0)) == 2


# --- named stars ---------------------------------------------------------------

def test_a_named_star_is_yellow_and_its_label_starts_past_the_reticle():
    star = NamedStar("Deneb", 0.0, 0.0, 1.25, 300.0, 300.0)
    prims = build_layout_for([], [star], None, (600, 800), 2.0, _layers(stars=True), "all",
                             measure=_measure)
    marker = next(p for p in prims if isinstance(p, Marker))
    label = next(p for p in prims if isinstance(p, Label))
    assert marker.colour[-6:].lower() == STAR_COLOUR[1:].lower()
    assert label.colour == STAR_COLOUR and label.tier == "star"
    gap, arm = STAR_RETICLE[marker.size]
    assert label.x >= 300.0 + gap + arm, "the name starts past the arm"
    assert label.y < 300.0 < label.y + label.h, "level with the star"


def test_a_star_name_keeps_the_mockups_clearance_from_the_arm():
    """The real render showed '—56 Cyg' glued to the arm's tip. The mockup set
    the name a ring-gap (6 px) beyond the arm plus its 2 px pad, as objects get."""
    star = NamedStar("Deneb", 0.0, 0.0, 1.25, 300.0, 300.0)
    for u in (1.0, 2.5):
        prims = build_layout_for([], [star], None, (600, 800), 2.0, _layers(stars=True), "all",
                                 measure=_measure, ui_scale=u)
        label = next(p for p in prims if isinstance(p, Label))
        gap, arm = STAR_RETICLE["star"]
        assert label.x == pytest.approx(300.0 + (gap + arm + 2.0 + 6.0) * u)


def test_an_object_label_never_covers_a_star_reticle():
    star = NamedStar("Deneb", 0.0, 0.0, 1.25, 330.0, 300.0)
    o = _obj(1.0, cx=300.0, cy=300.0, name="NGC 1")
    prims = build_layout_for([o], [star], None, (600, 800), 2.0,
                             _layers(objects=True, stars=True), "all", measure=_measure)
    gap, arm = STAR_RETICLE["star_bright"]
    e = gap + arm
    for l in (p for p in prims if isinstance(p, Label)):
        assert not _boxes_overlap(_box(l), (330.0 - e, 300.0 - e, 330.0 + e, 300.0 + e)), l


# --- grid ------------------------------------------------------------------------

@pytest.mark.parametrize("ra, text, parts", [
    (40.0, "2h40m", (("2", False), ("h", True), ("40", False), ("m", True))),
    (30.0, "2h", (("2", False), ("h", True))),
    (180.0, "12h", (("12", False), ("h", True))),
    (359.99, "0h", (("0", False), ("h", True))),        # a 23h60m carry wraps to 0h
    (-0.001, "0h", (("0", False), ("h", True))),
])
def test_ra_notation_raises_h_and_m(ra, text, parts):
    assert _fmt_ra(ra) == text
    assert ra_parts(ra) == parts
    assert "".join(t for t, _ in parts) == text


@pytest.mark.parametrize("dec, text", [
    (61.0, "+61°"), (61.5, "+61°30′"), (-14.0, "−14°"), (-0.25, "−0°15′"), (0.0, "+0°"),
    (44.9999, "+45°"),
])
def test_dec_notation(dec, text):
    assert _fmt_dec(dec) == text


def _rotated_wcs(rot_deg, scale_deg, ra=310.0, dec=44.0, w=800, h=600):
    k = WCS(naxis=2)
    k.wcs.crpix = [w / 2, h / 2]
    k.wcs.crval = [ra, dec]
    c, s = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))
    k.wcs.cd = [[-scale_deg * c, scale_deg * s], [scale_deg * s, scale_deg * c]]
    k.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return k


def test_grid_labels_are_labels_with_their_tips_and_lines_carry_no_text():
    prims = build_layout_for([], [], _grid_wcs(), (600, 800), 2.0, _layers(grid=True), "all",
                             measure=_measure)
    lines = [p for p in prims if isinstance(p, GridLine)]
    labels = [p for p in prims if isinstance(p, Label)]
    assert lines and labels
    assert all(gl.label == "" and gl.colour == GRID_LINE_COLOUR for gl in lines)
    for l in labels:
        assert l.tier == "grid" and l.size == "grid"
        assert l.text in l.tip and ("right ascension" in l.tip or "declination" in l.tip)
    ra = [l for l in labels if "right ascension" in l.tip]
    assert ra and all(l.parts and "".join(t for t, _ in l.parts) == l.text for l in ra)


def test_grid_line_colour_is_white_at_about_half_opacity():
    # 27% was lost on all three of his test fields (2026-10-15); half reads and stays calm.
    a = int(GRID_LINE_COLOUR[1:3], 16) / 255
    assert 0.45 <= a <= 0.55 and all(int(GRID_LINE_COLOUR[i:i + 2], 16) > 0xe0 for i in (3, 5, 7))


def test_grid_labels_never_leave_the_frame_under_any_rotation_or_scale():
    import random
    rng = random.Random(11)
    shape = (600, 800)
    seen = 0
    for _ in range(40):
        rot, scale = rng.uniform(0, 360), rng.uniform(0.0004, 0.004)
        prims = build_layout_for([], [], _rotated_wcs(rot, scale), shape, 2.0,
                                 _layers(grid=True), "all", measure=_measure)
        for l in (p for p in prims if isinstance(p, Label)):
            seen += 1
            assert l.x >= 0 and l.y >= 0 and l.x + l.w <= 800 and l.y + l.h <= 600, (rot, scale, l)
    assert seen > 40, "the sweep must actually place labels"


def test_a_grid_label_sits_on_its_line():
    prims = build_layout_for([], [], _grid_wcs(), (600, 800), 2.0, _layers(grid=True), "all",
                             measure=_measure)
    lines = [p for p in prims if isinstance(p, GridLine)]
    for l in (p for p in prims if isinstance(p, Label)):
        cx, cy = l.x + l.w / 2, l.y + l.h / 2
        d = min(_dist_to_polyline(cx, cy, gl.points) for gl in lines)
        assert d < 2.0, (l.text, d)


def _dist_to_polyline(px, py, pts):
    best = float("inf")
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        dx, dy = x1 - x0, y1 - y0
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(px - (x0 + t * dx), py - (y0 + t * dy)))
    return best


def test_a_grid_label_takes_the_other_end_when_its_end_is_taken():
    line = GridLine([(10.0, 300.0), (790.0, 300.0)], "#fff", "+44°", "tip")
    free = _place_grid_labels([line], (600, 800), _measure, 1.0, [])
    assert free and free[0].x < 400, "a Dec line's preferred end is the left"
    blocked = _place_grid_labels([line], (600, 800), _measure, 1.0, [(0.0, 250.0, 200.0, 350.0)])
    assert blocked and blocked[0].x > 400, "with the left taken it moves to the right end"
    both = _place_grid_labels([line], (600, 800), _measure, 1.0,
                              [(0.0, 250.0, 200.0, 350.0), (600.0, 250.0, 800.0, 350.0)])
    assert both == [], "neither end free: dropped, not clipped or overlapped"


# --- compass and scale bar ----------------------------------------------------------

def test_compass_is_a_thin_arrow_and_an_n_scaling_with_ui_scale():
    for ui in (1.0, 2.0):
        prims = build_layout_for([], [], _grid_wcs(), (600, 800), 2.0, _layers(compass=True),
                                 "all", measure=_measure, ui_scale=ui)
        (arrow,) = [p for p in prims if isinstance(p, Leader)]
        (n,) = [p for p in prims if isinstance(p, Label)]
        assert not arrow.screen_fixed, "image px at the consumer's scale, like every other offset"
        assert math.hypot(arrow.x2 - arrow.x1, arrow.y2 - arrow.y1) == pytest.approx(38.0 * ui)
        assert n.text == "N" and n.tier == "furniture" and n.tip
        assert not any(isinstance(p, Marker) for p in prims), "no dot: the calm look"


def test_scale_bar_has_end_ticks_and_a_centred_label():
    prims = build_layout_for([], [], None, (600, 800), 2.0, _layers(scale=True), "all",
                             measure=_measure)
    leaders = [p for p in prims if isinstance(p, Leader)]
    bar = next(l for l in leaders if l.y1 == l.y2)
    ticks = [l for l in leaders if l.x1 == l.x2]
    assert sorted(t.x1 for t in ticks) == [bar.x1, bar.x2]
    assert all(t.y1 < bar.y1 < t.y2 for t in ticks)
    (lab,) = [p for p in prims if isinstance(p, Label)]
    assert lab.x + lab.w / 2 == pytest.approx((bar.x1 + bar.x2) / 2)
    assert lab.y + lab.h < bar.y1


# --- one layout for every consumer --------------------------------------------------

def test_layout_is_deterministic_and_geometry_does_not_depend_on_text_scale():
    objs = [_obj(30.0, cx=400.0, cy=300.0, name="NGC 7000", common="North America Nebula"),
            _obj(2.0, cx=150.0, cy=120.0, name="LDN 935")]
    args = (objs, [NamedStar("Deneb", 0, 0, 1.25, 600.0, 450.0)], _grid_wcs(), (600, 800), 2.0,
            _layers(objects=True, stars=True, grid=True, compass=True, scale=True), "all")
    a = build_layout_for(*args, measure=_measure)
    assert build_layout_for(*args, measure=_measure) == a
    b = build_layout_for(*args, measure=lambda t, s: tuple(1.8 * v for v in _measure(t, s)),
                         ui_scale=1.8)
    true_size = lambda ps: [p for p in ps if isinstance(p, (Circle, GridLine, Marker))]
    assert true_size(a) == true_size(b), "rings, grid and star positions are the sky's, not the font's"


def test_an_ngc_or_ic_name_leads_a_merged_label_over_a_bigger_survey_entry():
    """Real catalogue, Soul field: Sh2-199 (120') and IC 1848 (40') are both
    "Soul Nebula"; people say IC 1848, so it leads although Sh2-199 is larger."""
    sh = _obj(120.0, cx=420.0, cy=300.0, name="Sh 2-199", common="Soul Nebula")
    ic = _obj(40.0, cx=400.0, cy=300.0, name="IC 1848", common="Soul Nebula")
    (rep, grp), = merge_aliases([sh, ic], 2.0)
    assert rep is ic and grp == [ic, sh]


# --- fix round 1: guards for the reviewer's surviving mutations -------------------

def test_the_mockup_reticle_for_every_star():
    assert STAR_RETICLE["star"] == STAR_RETICLE["star_bright"] == (9.0, 11.0)


def test_alias_merge_reaches_as_far_as_the_larger_ring():
    """The Soul: IC 1848 (40', r 20') and Sh 2-199 (120', r 60') sit 25' apart —
    outside IC 1848's ring, inside Sh 2-199's."""
    ic = _obj(40.0, cx=1000.0, cy=1000.0, name="IC 1848", common="Soul Nebula")
    sh = _obj(120.0, cx=1000.0 + 750.0, cy=1000.0, name="Sh 2-199", common="Soul Nebula")  # 25' at 2"/px
    groups = merge_aliases([sh, ic], 2.0)
    assert len(groups) == 1 and groups[0][0] is ic


def _overlaps_any(prims, box):
    return [p.text for p in prims if isinstance(p, Label) and p.tier in ("major", "minor")
            and _boxes_overlap(_box(p), box)]


def test_object_labels_keep_out_of_the_compass_corner():
    o = _obj(1.0, cx=640.0, cy=60.0, name="NGC 1234567")   # its right-hand spot is the corner
    prims = build_layout_for([o], [], _grid_wcs(), (600, 800), 2.0,
                             _layers(objects=True, compass=True), "all", measure=_measure)
    assert [p for p in prims if isinstance(p, Label) and p.text == "NGC 1234567"], "placed elsewhere"
    assert not _overlaps_any(prims, (730.0 - 60, 70.0 - 60, 730.0 + 60, 70.0 + 60))


def test_object_labels_keep_out_of_the_scale_bar_corner():
    o = _obj(1.0, cx=90.0, cy=545.0, name="NGC 1234567")
    prims = build_layout_for([o], [], None, (600, 800), 2.0,
                             _layers(objects=True, scale=True), "all", measure=_measure)
    bar = next(p for p in prims if isinstance(p, Leader) and p.y1 == p.y2)
    lab = next(p for p in prims if isinstance(p, Label) and p.tier == "furniture")
    assert [p for p in prims if isinstance(p, Label) and p.text == "NGC 1234567"]
    assert not _overlaps_any(prims, (bar.x1 - 10, lab.y - 4, bar.x2 + 10, bar.y1 + 10))


def test_a_small_ring_is_an_obstacle_to_other_labels():
    a = _obj(1.0, cx=300.0, cy=300.0, name="NGC 1")
    b = _obj(1.0, cx=345.0, cy=300.0, name="LDN 9")        # its ring sits where NGC 1's label would
    prims = build_layout_for([a, b], [], None, (600, 800), 2.0, _layers(objects=True), "all",
                             measure=_measure)
    e = 7.5 + 3.0
    assert not _overlaps_any(prims, (345.0 - e, 300.0 - e, 345.0 + e, 300.0 + e))


def test_an_off_frame_centre_labels_by_its_clamped_anchor():
    o = CatalogObject("NGC 7000", "", 0.0, 0.0, 30.0, 8.0, 300.0, False, -300.0, 300.0)  # r 450 px
    prims = build_layout_for([o], [], None, (600, 800), 2.0, _layers(objects=True), "all",
                             measure=_measure)
    (l,) = [p for p in prims if isinstance(p, Label)]
    nx, ny = min(max(8.0, l.x), l.x + l.w), min(max(300.0, l.y), l.y + l.h)
    assert math.hypot(nx - 8.0, ny - 300.0) < 20.0, "beside its anchor, not a ring's radius away"


def test_a_large_ring_falls_back_to_its_inner_rim():
    from nocturne.core.annotation_layout import _object_labels
    o = _obj(4.0, cx=1000.0, cy=1000.0, name="NGC 1")        # r 60 px > 40, < 12% of 2000
    occupied = [(0, 0, 940, 2000), (1060, 0, 2000, 2000), (0, 0, 2000, 940), (0, 1060, 2000, 2000)]
    labels = _object_labels([(o, [o])], (2000, 2000), 2.0, _measure, 1.0, occupied)
    assert labels, "the inner rim is free"
    l = labels[0]
    assert 940 <= l.x and l.x + l.w <= 1060 and 940 <= l.y and l.y + l.h <= 1060


def test_a_label_too_big_for_the_frame_is_dropped():
    o = _obj(1.0, cx=150.0, cy=150.0, name="A" * 60)       # 420 px on a 300 px frame
    prims = build_layout_for([o], [], None, (300, 300), 2.0, _layers(objects=True), "all",
                             measure=_measure)
    assert not [p for p in prims if isinstance(p, Label)]


def test_an_ra_label_prefers_the_bottom_edge():
    line = GridLine([(400.0, 5.0), (400.0, 595.0)], "#fff", "2h40m", "tip", ra_parts(40.0))
    (l,) = _place_grid_labels([line], (600, 800), _measure, 1.0, [])
    assert l.y > 300.0
    line_up = line._replace(points=line.points[::-1])
    (l2,) = _place_grid_labels([line_up], (600, 800), _measure, 1.0, [])
    assert l2.y > 300.0, "whichever way the polyline runs"


def test_a_hair_south_of_the_equator_is_plus_zero():
    assert _fmt_dec(-0.001) == "+0°"


def test_the_default_measure_reserves_at_the_rendered_scale():
    """PS-07: no measure passed -> the fallback must reserve at ui_scale."""
    from nocturne.core.annotation_layout import _default_measure
    o = _obj(1.0, cx=300.0, cy=300.0, name="NGC 1")
    prims = build_layout_for([o], [], None, (2000, 2000), 2.0, _layers(objects=True), "all",
                             ui_scale=1.8)
    (l,) = [p for p in prims if isinstance(p, Label)]
    assert (l.w, l.h) == _default_measure("NGC 1", "major", 1.8)
    assert _default_measure("NGC 1", "major", 1.8)[0] == pytest.approx(1.8 * _default_measure("NGC 1", "major")[0])


def test_grid_labels_stay_on_their_own_line_under_any_rotation_or_scale():
    """After the frame clamp a label more than half its height off its line is
    moved to the other end, or dropped (ruling, fix round 1)."""
    import random
    rng = random.Random(5)
    shape, kept = (2160, 3840), 0
    for _ in range(40):
        rot, sc, dec = rng.uniform(0, 360), rng.uniform(1.5, 8) / 3600, rng.uniform(-80, 80)
        wcs = _rotated_wcs(rot, sc, dec=dec, w=3840, h=2160)
        prims = build_layout_for([], [], wcs, shape, sc * 3600, _layers(grid=True, compass=True,
                                 scale=True), "all", ui_scale=3.2)
        lines = grid_lines(wcs, shape, "#fff")
        for l in (p for p in prims if isinstance(p, Label) and p.tier == "grid"):
            kept += 1
            own = [g for g in lines if g.label == l.text]
            d = min(_dist_to_polyline(l.x + l.w / 2, l.y + l.h / 2, g.points) for g in own)
            assert d <= l.h / 2 + 1e-6, (l.text, round(d), rot, sc * 3600)
            assert l.x >= 0 and l.y >= 0 and l.x + l.w <= 3840 and l.y + l.h <= 2160
    assert kept > 200, "the sweep must keep most labels"


def test_a_grid_label_the_clamp_pushes_off_its_line_takes_the_other_end():
    # A Dec line hugging the top edge at its left end: there the clamp pushes the
    # label ~12 px below the line (more than half its 14 px height); the right
    # end, 40 px down, is clean.
    line = GridLine([(0.0, 1.0), (790.0, 40.0)], "#fff", "+44°", "tip")
    (l,) = _place_grid_labels([line], (600, 800), _measure, 1.0, [])
    assert l.x > 400, "the left end would sit off its line after the clamp"


# --- fix round 2: a ring's obstacle box never blocks a label anchored inside it ---

def test_two_coincident_small_rings_both_keep_their_labels():
    a = _obj(1.0, cx=300.0, cy=300.0, name="NGC 1")         # r 15 px
    b = _obj(0.5, cx=300.0, cy=300.0, name="LDN 2")         # r 7.5 px, inside a's box
    prims = build_layout_for([a, b], [], None, (600, 800), 2.0, _layers(objects=True), "all",
                             measure=_measure)
    labels = [p for p in prims if isinstance(p, Label)]
    assert sorted(l.text for l in labels) == ["LDN 2", "NGC 1"]
    assert not _boxes_overlap(_box(labels[0]), _box(labels[1]))


def test_a_label_anchored_inside_another_ring_still_avoids_third_rings():
    """The exemption is for the ring the anchor sits in, not every ring."""
    host = _obj(1.6, cx=300.0, cy=300.0, name="NGC 1")       # r 24 px, obstacle box +-27
    guest = _obj(0.2, cx=310.0, cy=300.0, name="LDN 2")      # anchor inside host's box
    other = _obj(0.5, cx=355.0, cy=300.0, name="LDN 3")      # a ring where guest's label would go
    prims = build_layout_for([host, guest, other], [], None, (600, 800), 2.0,
                             _layers(objects=True), "all", measure=_measure)
    assert {p.text for p in prims if isinstance(p, Label)} == {"NGC 1", "LDN 2", "LDN 3"}
    e = 7.5 + 3.0
    assert not _overlaps_any(prims, (355.0 - e, 300.0 - e, 355.0 + e, 300.0 + e)), \
        "neither the host's label nor the guest's may sit on the third ring"


def _real_field(ra, dec, w=3840, h=2160, s=3.75 / 3600):
    k = WCS(naxis=2)
    k.wcs.crpix = [w / 2, h / 2]
    k.wcs.crval = [ra, dec]
    k.wcs.cd = [[-s, 0], [0, s]]
    k.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return k


@pytest.mark.parametrize("ui", [1.0, 2.0, 3.0])
@pytest.mark.parametrize("ra, dec", [(36.6, 62.0), (106.15, -10.47)])   # Fish Head, Seagull
def test_real_frames_keep_every_object_label(ra, dec, ui):
    """At ui_scale 3 these dropped LDN 1359 (inside NGC 896's ring) and vdB 88 /
    vdB 90 (inside Sh 2-293 / Sh 2-295): their own anchors sat in another
    small ring's obstacle box, so every candidate was 'taken'."""
    from nocturne.core.annotation_layout import designation
    from nocturne.core.catalog import objects_in_field
    shape = (2160, 3840)
    wcs = _real_field(ra, dec)
    objs = objects_in_field(wcs, shape)
    prims = build_layout_for(objs, [], wcs, shape, 3.75, _layers(objects=True), "all", ui_scale=ui)
    got = {p.text for p in prims if isinstance(p, Label)}
    kept, _ = filter_by_density(objs, [], 3.75, "all")
    want = {" · ".join(dict.fromkeys(designation(g) for g in grp))
            for _, grp in merge_aliases(kept, 3.75)}
    assert len(want) >= 15 and want - got == set()
    labels = [p for p in prims if isinstance(p, Label)]
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            assert not _boxes_overlap(_box(a), _box(b)), (a.text, b.text)


@pytest.mark.parametrize("cy", [300.0, 30.0, 570.0])     # mid edge, and near both corners
def test_a_label_clamped_back_into_the_frame_never_lands_on_its_own_ring(cy):
    """NGC 7000 (2026-10-15 render): B 349 and LDN 931 sit by the right edge;
    their right-hand spot was clamped back into the frame and onto their own
    ring. The mockup set them to the left of it."""
    r = 12.0
    o = _obj(r * 2 * 2.0 / 60.0, cx=790.0, cy=cy, name="LDN 931")       # r = 12 px at 2"/px
    prims = build_layout_for([o], [], None, (600, 800), 2.0, _layers(objects=True), "all",
                             measure=_measure)
    (label,) = [p for p in prims if isinstance(p, Label)]
    nx = min(max(790.0, label.x), label.x + label.w)
    ny = min(max(cy, label.y), label.y + label.h)
    assert math.hypot(nx - 790.0, ny - cy) >= r, "the label covers its own ring"
    assert label.x + label.w <= 790.0 - r, "it goes to the free side, the left"


@pytest.mark.parametrize("u", [1.0, 2.0, 3.0, 4.2])
def test_a_merged_label_stays_off_its_aliases_small_ring(u):
    """M 16 · IC 4703 sat on IC 4703's 5' ring: the ring whose box holds the
    anchor is exempt as an obstacle (so a label inside another ring keeps
    room), and that exemption also covered the label's own alias. Geometry
    from the real M 16 frame (3911x2608 at 2.4"/px)."""
    from nocturne.core.annotation_layout import _covers_disc, _default_measure
    m16 = _obj(120.0, cx=1953.0, cy=1292.0, name="NGC 6611", common="Eagle Nebula", messier="16")
    ic = _obj(5.05, cx=1905.0, cy=1235.0, name="IC 4703", common="Eagle Nebula")
    prims = build_layout_for([m16, ic], [], None, (2608, 3911), 2.4, _layers(objects=True),
                             "balanced", measure=lambda t, s: _default_measure(t, s, u),
                             ui_scale=u)
    labels = [p for p in prims if isinstance(p, Label)]
    assert [l.text for l in labels] == ["M 16 · IC 4703"], "the merged label must survive"
    l = labels[0]
    ring = circle_for(ic, 2.4)
    assert not _covers_disc((l.x, l.y, l.x + l.w, l.y + l.h), (ring.x, ring.y, ring.r)), \
        f"label {l.x:.0f},{l.y:.0f} {l.w:.0f}x{l.h:.0f} on IC 4703's ring at u={u}"
