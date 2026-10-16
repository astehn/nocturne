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
