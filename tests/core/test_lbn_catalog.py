"""Lynds' Bright Nebulae in the bundled catalogue (spec 2026-10-16-lbn-research,
DECISION): net-new rows only, sizes 10'-120', minor tier, and never the target."""
import csv
import math
import re

import pytest
from astropy.wcs import WCS

from nocturne.core.annotation_layout import tier_of
from nocturne.core.catalog import (CatalogObject, _DATA, identify_target,
                                   identify_target_parts, load_catalog, objects_in_field)

# The 2026-10-16 dry run of scripts/fetch_extra_catalogs.py --only LBN:
# 1125 fetched -> 835 no NGC/IC/Sh2 cross-ref -> 397 Bright <= 4
# -> 300 Diam1 10'-120' -> 278 not a positional duplicate.
SHIPPED_LBN = 278


def _rows():
    with open(_DATA, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _lbn():
    return [r for r in _rows() if r["name"].startswith("LBN")]


def test_lbn_rows_are_present_and_well_formed():
    rows = _lbn()
    assert len(rows) == SHIPPED_LBN
    nums = [int(r["name"][3:]) for r in rows]
    assert nums == sorted(set(nums)) and 1 <= nums[0] and nums[-1] <= 1125
    for r in rows:
        assert re.fullmatch(r"LBN[1-9]\d*", r["name"]), r["name"]
        assert r["common"] == "" and r["type"] == "Neb"
        assert r["pos_angle"] == "" and r["messier"] == ""
        assert 0.0 <= float(r["ra_deg"]) < 360.0 and -90.0 <= float(r["dec_deg"]) <= 90.0
        assert 0.0 < float(r["minor_arcmin"]) <= float(r["major_arcmin"])


def test_lbn_rows_are_appended_after_everything_else():
    """Adding LBN must not reorder, and so not churn, the rows already shipped."""
    names = [r["name"] for r in _rows()]
    first = next(i for i, n in enumerate(names) if n.startswith("LBN"))
    assert all(n.startswith("LBN") for n in names[first:])
    assert names[first - 1] == "vdB158"


def test_lbn_sizes_stay_inside_the_ruled_bounds():
    for r in _lbn():
        assert 10.0 <= float(r["major_arcmin"]) <= 120.0, r["name"]


@pytest.mark.parametrize("lbn, shipped_as", [
    (373, "NGC 7000"), (350, "IC 5070"), (654, "IC 1805"), (529, "Sh2-155"),
])
def test_an_lbn_cross_referenced_to_a_shipped_object_is_not_shipped_again(lbn, shipped_as):
    """Each passes the brightness and size cuts; only the cross-ref drops it."""
    names = {r["name"] for r in _rows()}
    assert f"LBN{lbn}" not in names
    assert shipped_as.replace("NGC ", "NGC").replace("IC ", "IC") in names


def test_no_lbn_row_is_positionally_an_ngc_ic_or_sh2_object():
    """The fetch script's own _same_object rule, re-stated: centres within 30%
    of the larger radius and sizes within 3x."""
    others = [r for r in _rows() if r["name"].startswith(("NGC", "IC", "Sh2-"))
              and float(r["major_arcmin"] or 0) > 0]
    for r in _lbn():
        ra, dec, maj = float(r["ra_deg"]), float(r["dec_deg"]), float(r["major_arcmin"])
        for o in others:
            omaj = float(o["major_arcmin"])
            if not (1 / 3 <= maj / omaj <= 3):
                continue
            d = math.hypot((ra - float(o["ra_deg"])) * math.cos(math.radians(dec)),
                           dec - float(o["dec_deg"]))
            assert d > 0.30 * max(maj, omaj) / 2 / 60, (r["name"], o["name"])


def test_a_loaded_lbn_object_is_minor_tier():
    row = next(r for r in load_catalog() if r[0].startswith("LBN"))
    wcs = _field(row[2], row[3])
    lbn = [o for o in objects_in_field(wcs, (2160, 3840), rows=[row])]
    assert lbn and lbn[0].name.startswith("LBN ")
    assert tier_of(lbn[0]) == "minor"


# --- the target ------------------------------------------------------------------

def _obj(name, major, cx, cy, centred=True, r_px=None, common=""):
    return CatalogObject(name, common, 0.0, 0.0, major, cx, cy, centred, cx, cy,
                         r_px=major * 8.0 if r_px is None else r_px)


@pytest.mark.parametrize("other", ["LDN 1234", "B 33", "Sh 2-240", "vdB 141", "NGC 896"])
def test_identify_target_never_names_an_lbn_over_another_catalogue(other):
    """The LBN is centred, covers the frame centre and is far larger; the other
    is small and off to the side. On every other rule the LBN wins."""
    shape = (1080, 1920)
    lbn = _obj("LBN 437", 100.0, 960.0, 540.0)
    rival = _obj(other, 2.0, 100.0, 100.0, centred=False)
    assert identify_target([lbn, rival], shape) == other
    assert identify_target([rival, lbn], shape) == other


def test_an_lbn_alone_can_still_be_the_target():
    assert identify_target([_obj("LBN 437", 100.0, 960.0, 540.0)], (1080, 1920)) == "LBN 437"


# --- real fields, real catalogue -------------------------------------------------

def _field(ra, dec, w=3840, h=2160, scale_deg=3.75 / 3600):
    wc = WCS(naxis=2)
    wc.wcs.crpix = [w / 2, h / 2]
    wc.wcs.crval = [ra, dec]
    wc.wcs.cd = [[-scale_deg, 0], [0, scale_deg]]
    wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wc


@pytest.mark.parametrize("ra, dec, want", [
    (38.2, 61.45, "IC 1805"),
    (314.7, 44.3, "NGC 7000"),
    (85.25, -2.45, "B 33"),       # the Horsehead itself, once IC 434 lost the Flame's name
])
def test_real_fields_keep_their_target_with_lbn_in_the_catalogue(ra, dec, want):
    shape = (2160, 3840)
    objs = objects_in_field(_field(ra, dec), shape)
    assert any(o.name.startswith("LBN ") for o in objs)      # the field does hold LBN
    assert identify_target_parts(objs, shape)[0] == want


# --- the overlay: LBN only at "all", a label with no ring (his call 2026-10-16) ----

from nocturne.core.annotation_layout import (Circle, Label, build_layout_for,  # noqa: E402
                                             filter_by_density)


def _lay(name, major, cx, cy, common=""):
    return CatalogObject(name, common, 0.0, 0.0, major, cx, cy, True, cx, cy)


def _measure(text, size):
    return (7.0 * len(text), 14.0)


def _layout(objs, pixscale=3.75, density="all", shape=(1000, 1600)):
    return build_layout_for(objs, [], None, shape, pixscale, {"objects": True}, density,
                            measure=_measure)


@pytest.mark.parametrize("density, kept", [("minimal", False), ("balanced", False), ("all", True)])
def test_lbn_is_shown_only_at_density_all(density, kept):
    lbn = _lay("LBN 437", 60.0, 500.0, 500.0)
    control = _lay("LDN 1234", 60.0, 900.0, 500.0, common="Named" if density == "minimal" else "")
    objs, _ = filter_by_density([lbn, control], [], 3.75, density)
    assert (lbn in objs) is kept
    assert control in objs                      # same size, other catalogue: the gate is LBN's


def test_a_named_lbn_still_waits_for_all():
    lbn = _lay("LBN 437", 60.0, 500.0, 500.0, common="Some Name")
    assert filter_by_density([lbn], [], 3.75, "balanced")[0] == []


def test_lbn_gets_a_label_but_no_ring():
    lbn, ldn = _lay("LBN 437", 60.0, 500.0, 500.0), _lay("LDN 1234", 60.0, 1100.0, 500.0)
    prims = _layout([lbn, ldn])
    circles = [p for p in prims if isinstance(p, Circle)]
    assert [(c.x, c.y) for c in circles] == [(1100.0, 500.0)]
    assert {p.text for p in prims if isinstance(p, Label)} == {"LBN 437", "LDN 1234"}


def test_an_lbn_label_sits_by_its_point_not_out_on_its_ring():
    """14' at 3.75"/px is a 112 px radius: small enough to take its label
    outside the rim. With no ring drawn, a label out there names empty sky."""
    prims = _layout([_lay("LBN 437", 14.0, 800.0, 500.0)])
    lab = next(p for p in prims if isinstance(p, Label))
    assert math.hypot(lab.x + lab.w / 2 - 800.0, lab.y + lab.h / 2 - 500.0) < 60.0


def test_an_lbn_claims_no_invisible_obstacle():
    """At a wide-field scale a 10' LBN would be a small in-frame ring, and small
    rings block other labels. Nothing is drawn there, so nothing may block."""
    shape, ps = (1000, 1600), 30.0               # 10' -> r = 10 px
    ngc = _lay("NGC 1", 0.0, 500.0, 500.0)
    alone = next(p for p in _layout([ngc], ps, shape=shape) if isinstance(p, Label))
    with_lbn = _layout([ngc, _lay("LBN 437", 10.0, alone.x + 20.0, alone.y + 7.0)], ps,
                       shape=shape)
    lab = next(p for p in with_lbn if isinstance(p, Label) and p.text == "NGC 1")
    assert (lab.x, lab.y) == (alone.x, alone.y)


def test_an_lbn_label_never_takes_the_spot_of_another_catalogues():
    """NGC 7000 at "all" lost LDN 931 to an LBN: equal priority, and the LBN's
    bigger catalogued size put it down first. An LBN is placed last."""
    from nocturne.core.annotation_layout import priority_of
    lbn, ldn = _lay("LBN 437", 120.0, 800.0, 500.0), _lay("LDN 931", 0.0, 800.0, 500.0)
    assert priority_of(lbn) < priority_of(ldn)
    alone = next(p for p in _layout([ldn]) if isinstance(p, Label))
    both = {p.text: p for p in _layout([lbn, ldn]) if isinstance(p, Label)}
    assert (both["LDN 931"].x, both["LDN 931"].y) == (alone.x, alone.y)


@pytest.mark.parametrize("ra, dec", [(314.7, 44.3), (300.9, 45.81), (38.2, 61.45)])
def test_lbn_moves_no_other_label_at_all(ra, dec):
    """Review 2026-10-16: placed with the object labels, LBN took named stars'
    spots (57 Cyg moved ~195 px; 30 Cyg vanished at 300.9/+45.81). Every
    non-LBN label must sit exactly where it sat without LBN."""
    from nocturne.core.annotation_layout import build_layout_for as layout
    from nocturne.core.catalog import named_stars_in_field
    shape, wcs = (2160, 3840), _field(ra, dec)
    objs = objects_in_field(wcs, shape)
    assert any(o.name.startswith("LBN") for o in objs)
    before = [o for o in objs if not o.name.startswith("LBN")]

    def placed(o):
        prims = layout(o, named_stars_in_field(wcs, shape), wcs, shape, 3.75,
                       {"objects": True, "stars": True, "grid": True, "compass": True,
                        "scale": True}, "all", ui_scale=1.8)
        return {(p.text, round(p.x, 3), round(p.y, 3)) for p in prims
                if isinstance(p, Label) and not p.text.startswith("LBN")}
    assert placed(before) == placed(objs)


def test_an_lbn_whose_centre_is_off_frame_is_not_drawn():
    """LBN 384 floated on NGC 7000's left edge, a label for a point outside
    the picture. The list still names it; the overlay does not."""
    from nocturne.core.annotation_layout import Marker
    inside, outside = _lay("LBN 437", 30.0, 800.0, 500.0), _lay("LBN 438", 60.0, -40.0, 500.0)
    outside = outside.__class__(**{**outside.__dict__, "x": 8.0, "centered": False})
    prims = _layout([inside, outside])
    assert {p.text for p in prims if isinstance(p, Label)} == {"LBN 437"}
    assert [(m.x, m.y) for m in prims if isinstance(m, Marker)] == [(800.0, 500.0)]


def test_a_crowded_lbn_point_reaches_past_its_first_eight_spots():
    """A bare point has 8 spots at the gap; a named star on the same point
    takes all of them with its reticle, and the label must step outward."""
    from nocturne.core.catalog import NamedStar
    star = NamedStar("Test Star", 0.0, 0.0, 5.0, 800.0, 500.0)
    prims = build_layout_for([_lay("LBN 437", 30.0, 800.0, 500.0)], [star], None, (1000, 1600),
                             3.75, {"objects": True, "stars": True}, "all", measure=_measure)
    assert "LBN 437" in {p.text for p in prims if isinstance(p, Label)}


def test_a_labelled_lbn_gets_a_soft_point_and_nothing_else_does():
    from nocturne.core.annotation_layout import LBN_POINT_COLOUR, Marker
    lbn, ldn = _lay("LBN 437", 60.0, 500.0, 500.0), _lay("LDN 1234", 0.0, 1100.0, 500.0)
    marks = [m for m in _layout([lbn, ldn]) if isinstance(m, Marker)]
    assert marks == [Marker(500.0, 500.0, "point", LBN_POINT_COLOUR, "point")]
    assert int(LBN_POINT_COLOUR[1:3], 16) <= 140            # translucent: "about here"
    assert not [m for m in _layout([lbn, ldn], density="balanced") if isinstance(m, Marker)]


def test_an_lbn_without_room_for_its_label_gets_no_point():
    from nocturne.core.annotation_layout import Marker
    tiny = (40, 60)                               # no label fits this frame at all
    prims = _layout([_lay("LBN 437", 30.0, 30.0, 20.0)], shape=tiny)
    assert not [p for p in prims if isinstance(p, (Label, Marker))]


def test_the_lbn_point_blocks_no_label():
    """The point is drawn under labels, never reserved: a label placed on it
    is where it would be without it."""
    from nocturne.core.annotation_layout import Marker
    ngc = _lay("NGC 1", 0.0, 500.0, 500.0)
    alone = next(p for p in _layout([ngc]) if isinstance(p, Label))
    pt = (alone.x + 10.0, alone.y + 7.0)                  # inside NGC 1's own label box
    prims = _layout([ngc, _lay("LBN 437", 30.0, *pt)])
    lab = next(p for p in prims if isinstance(p, Label) and p.text == "NGC 1")
    assert (lab.x, lab.y) == (alone.x, alone.y)
    assert any(isinstance(m, Marker) and (m.x, m.y) == pt for m in prims)
    kinds = [type(p).__name__ for p in prims]
    assert kinds.index("Marker") < kinds.index("Label")     # painted under the text
