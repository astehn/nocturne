import numpy as np
from astropy.wcs import WCS
from nocturne.core.catalog import objects_in_field, identify_target, CatalogObject


def _wcs(center_ra=100.0, center_dec=0.0, w=1920, h=1080, scale_deg=0.0005556):
    wc = WCS(naxis=2)
    wc.wcs.crpix = [w / 2, h / 2]
    wc.wcs.crval = [center_ra, center_dec]
    wc.wcs.cd = [[-scale_deg, 0], [0, scale_deg]]
    wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wc


def test_objects_in_field_keeps_in_frame_drops_out():
    wcs = _wcs()
    rows = [
        ("NGC A", "Alpha", 100.0, 0.0, 20.0),     # dead centre -> in
        ("NGC B", "", 100.0, 5.0, 5.0),            # 5 deg north, small -> out of a ~0.6x0.3 deg field
    ]
    objs = objects_in_field(wcs, (1080, 1920), rows=rows)
    names = [o.name for o in objs]
    assert "NGC A" in names and "NGC B" not in names
    a = next(o for o in objs if o.name == "NGC A")
    assert abs(a.x - 960) < 2 and abs(a.y - 540) < 2      # centre pixel
    assert a.centered is True


def test_objects_in_field_includes_large_overlapping_off_centre_object():
    # A big object whose CENTRE is just off the top of the frame but whose extent
    # reaches into it (like a nebula filling the view) must still be labelled.
    wcs = _wcs()                                   # ~0.6deg x 0.3deg field, 0.0005556 deg/px
    # 0.4 deg north of centre (off the 0.3deg half-height frame) but 120' wide.
    rows = [("NGC 7000", "North America Nebula", 100.0, 0.4, 120.0)]
    objs = objects_in_field(wcs, (1080, 1920), rows=rows)
    assert len(objs) == 1
    o = objs[0]
    assert o.name == "NGC 7000" and o.common == "North America Nebula"
    assert o.centered is False                     # centre off-frame -> no ring, label clamped
    assert 0 <= o.x < 1920 and 0 <= o.y < 1080     # label anchor clamped into the frame


def test_objects_in_field_prettifies_zero_padded_names():
    wcs = _wcs()
    rows = [("NGC0224", "Andromeda", 100.0, 0.0, 20.0),
            ("IC5070", "", 100.0, 0.0, 10.0)]
    names = {o.name for o in objects_in_field(wcs, (1080, 1920), rows=rows)}
    assert names == {"NGC 224", "IC 5070"}         # zero-padding stripped, space inserted


def test_identify_target_picks_largest():
    objs = [
        CatalogObject("NGC A", "Alpha", 100.0, 0.0, 5.0, 900, 540),
        CatalogObject("NGC B", "Beta", 100.0, 0.0, 40.0, 1000, 540),
    ]
    assert identify_target(objs, (1080, 1920)) == "NGC B · Beta"
    assert identify_target([], (1080, 1920)) == ""


def test_named_stars_in_field_keeps_in_frame():
    from nocturne.core.catalog import named_stars_in_field
    wcs = _wcs(center_ra=100.0, center_dec=0.0)     # ~0.6x0.3 deg field at RA100/Dec0
    rows = [("Alpha", 100.0, 0.0, 1.5),             # dead centre -> in
            ("Beta", 100.0, 5.0, 2.0)]              # 5 deg north -> out
    stars = named_stars_in_field(wcs, (1080, 1920), rows=rows)
    names = [s.name for s in stars]
    assert names == ["Alpha"]
    assert abs(stars[0].x - 960) < 2 and abs(stars[0].y - 540) < 2


def test_bundled_named_stars_has_known_stars():
    from nocturne.core.catalog import load_named_stars
    d = {n: (ra, dec) for n, ra, dec, mag in load_named_stars()}
    assert "Deneb" in d and "Vega" in d and "Altair" in d
    ra, dec = d["Deneb"]
    assert abs(ra - 310.36) < 0.1 and abs(dec - 45.28) < 0.1     # sanity: real coords


def test_catalog_rows_expose_object_type():
    from nocturne.core.catalog import load_catalog
    rows = load_catalog()
    assert rows, "bundled catalogue must load"
    assert any(r[5] for r in rows), "at least some rows must carry a type"


def test_catalog_rows_expose_messier_number_via_a_separate_column():
    # The `name` field stays the OpenNGC designation (never renamed to "M 31")
    # so target metadata / provenance reports keep a stable identity; Messier
    # membership lives in its own column instead.
    from nocturne.core.catalog import load_catalog
    rows = load_catalog()
    row = next(r for r in rows if r[0] == "NGC0224")
    assert row[0] == "NGC0224"
    assert row[8] == "31"


def test_data_paths_are_resolved_without_dotdot():
    # In the PyInstaller bundle, nocturne/core/ is not a real directory (code
    # lives in the PYZ archive), so an un-normalized "core/../data/..." path
    # can't be traversed and open() raises ENOENT. The paths must be resolved
    # (no "..") and point at existing files.
    import os
    from nocturne.core import catalog
    assert ".." not in catalog._DATA
    assert ".." not in catalog._STARS
    assert os.path.exists(catalog._DATA)
    assert os.path.exists(catalog._STARS)


# --- ground truth from a real ASTAP solve -------------------------------------
# Every other plate-solve test builds its WCS synthetically, and a synthetic WCS
# is SELF-CONSISTENT under either vertical convention: the test projects with the
# same flip it asserts against, so it passes whichever value FITS_Y_DOWN holds.
# That is exactly how a mirrored overlay shipped from 0.3.0 to 0.5.0 past a
# 1130-test suite. These constants come from an actual ASTAP solution of an
# NGC 7000 frame (saved project, 2026-07-31) and the expected pixels are the
# positions the corrected app draws, verified by eye against the real stars.
_REAL_ASTAP_WCS = {
    "WCSAXES": 2, "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
    "CRVAL1": 313.73419145078, "CRVAL2": 43.980673202631,
    "CRPIX1": 792.5, "CRPIX2": 1232.0, "CDELT1": 1.0, "CDELT2": 1.0,
    "CUNIT1": "deg", "CUNIT2": "deg",
    "PC1_1": -0.00072664976972844, "PC1_2": 0.00071098142641278,
    "PC2_1": -0.00071098508198742, "PC2_2": -0.00072675805361948,
    "LONPOLE": 180.0, "LATPOLE": 43.980673202631, "RADESYS": "ICRS",
}
_REAL_SHAPE = (3544, 1584)          # h, w of the solved frame
_REAL_EXPECTED = {                   # name -> (cx, cy) the corrected app draws
    "IC5067": (1408.7, 76.8),
    "IC5070": (992.1, 449.9),
    "NGC6989": (27.2, 246.4),
    "NGC6997": (128.0, 983.5),
}
_REAL_ROWS = [                       # exact bundled-catalogue coordinates
    ("IC5067", "", 311.959083, 44.366972, 0.0),
    ("IC5070", "", 312.753, 44.4015, 60.0),
    ("NGC6989", "", 313.528833, 45.239278, 5.4),
    ("NGC6997", "", 314.164375, 44.6315, 6.9),
]


def test_projection_matches_a_real_astap_solve():
    """Pins the vertical convention against a REAL solver output.

    Flipping FITS_Y_DOWN back to True moves every object by roughly the frame
    height and fails this — which no synthetic-WCS test in the suite can do.
    """
    from astropy.wcs import WCS
    from nocturne.core.catalog import objects_in_field

    wcs = WCS(_REAL_ASTAP_WCS)
    got = {o.name.replace(" ", ""): (o.cx, o.cy)
           for o in objects_in_field(wcs, _REAL_SHAPE, rows=_REAL_ROWS)}
    for name, (ex, ey) in _REAL_EXPECTED.items():
        assert name in got, f"{name} should project into the solved frame"
        gx, gy = got[name]
        assert abs(gx - ex) < 1.5, f"{name} x: {gx:.1f} vs {ex}"
        assert abs(gy - ey) < 1.5, f"{name} y: {gy:.1f} vs {ey} — vertical convention wrong?"


def test_named_stars_use_the_same_convention_as_objects():
    """A star and an object at the SAME sky position must land on the same pixel.

    They travel different code paths (per-object vs vectorised), so a convention
    fixed in one and not the other would put stars in the wrong place while
    nebula circles still looked plausible — the failure the user actually saw.
    """
    from astropy.wcs import WCS
    from nocturne.core.catalog import named_stars_in_field, objects_in_field

    wcs = WCS(_REAL_ASTAP_WCS)
    ra, dec = 312.753, 44.4015
    obj = objects_in_field(wcs, _REAL_SHAPE, rows=[("X", "", ra, dec, 0.0)])[0]
    star = named_stars_in_field(wcs, _REAL_SHAPE, rows=[("X", ra, dec, 4.0)])[0]
    assert abs(star.x - obj.cx) < 0.01 and abs(star.y - obj.cy) < 0.01


# --- curated common names -----------------------------------------------------

def test_curated_names_fill_only_blanks_never_override_the_catalogue():
    """A name the source catalogue supplies must always win — the curated file is
    a fallback for catalogues that carry none, not an editorial layer."""
    from nocturne.core.catalog import _curated_names
    names = _curated_names()
    assert names, "curated file failed to load"
    import csv
    for r in csv.DictReader(open("nocturne/data/openngc.csv")):
        d = r["name"].replace(" ", "")
        if d in names and r.get("common", "").strip():
            pytest.fail(f"{d} has a catalogue name AND a curated one — remove the curated row")


def test_every_curated_designation_exists_in_the_catalogue():
    """A dead row is silently useless: it never matches, so the name never
    appears and nothing complains. An earlier draft had four."""
    import csv
    from nocturne.core.catalog import _curated_names
    have = {r["name"].replace(" ", "") for r in csv.DictReader(open("nocturne/data/openngc.csv"))}
    dead = [d for d in _curated_names() if d not in have]
    assert not dead, f"curated names for objects not in the catalogue: {dead}"


def test_a_named_small_object_can_win_the_target_over_a_large_anonymous_one():
    """Reported on a real IC 1396A frame: the target read "Sh 2-131" — the whole
    170' region — rather than the Elephant's Trunk the user actually pointed at.
    The trunk (vdB 142) was found, but anonymous and 0' across, so size decided
    it. A common name outranks size, which is what a curated name restores."""
    from nocturne.core.catalog import CatalogObject, identify_target
    shape = (3840, 2160)
    big = CatalogObject("Sh 2-131", "", 323.9, 57.4, 170.0, 1080, 1900, True, 1080, 1900)
    anon = CatalogObject("vdB 142", "", 324.7, 57.5, 0.0, 900, 1750, True, 900, 1750)
    named = CatalogObject("vdB 142", "Elephant's Trunk Nebula", 324.7, 57.5, 0.0,
                          900, 1750, True, 900, 1750)
    assert identify_target([big, anon], shape) == "Sh 2-131"
    assert identify_target([big, named], shape) == "vdB 142 · Elephant's Trunk Nebula"


def test_the_elephants_trunk_is_named_on_vdb142_not_on_the_whole_region():
    """Sh2-131 is the 170' IC 1396 region; the trunk is vdB 142 inside it. An
    earlier draft of the curated file put the name on Sh2-131, which would have
    made the reported problem worse rather than better."""
    from nocturne.core.catalog import _curated_names
    names = _curated_names()
    assert names.get("vdB142") == "Elephant's Trunk Nebula"
    assert "Sh2-131" not in names


def test_identify_target_parts_keeps_the_pair_apart():
    """identify_target joins these with ' · '. The plate needs them separate —
    and the join must stay, because target_solved, the info strip, the
    provenance report and the FITS export all read the joined form."""
    from nocturne.core.catalog import CatalogObject, identify_target, identify_target_parts
    objs = [CatalogObject(name="IC 1396A", common="Elephant's Trunk Nebula",
                          ra_deg=324.7, dec_deg=57.5, major_arcmin=20.0, x=50, y=50)]
    assert identify_target_parts(objs, (100, 100)) == ("IC 1396A", "Elephant's Trunk Nebula")
    assert identify_target(objs, (100, 100)) == "IC 1396A · Elephant's Trunk Nebula"


def test_identify_target_parts_on_an_object_with_no_common_name():
    from nocturne.core.catalog import CatalogObject, identify_target_parts
    objs = [CatalogObject(name="NGC 7380", common="", ra_deg=341.8, dec_deg=58.1,
                          major_arcmin=25.0, x=50, y=50)]
    assert identify_target_parts(objs, (100, 100)) == ("NGC 7380", "")


def test_identify_target_parts_on_an_empty_field():
    from nocturne.core.catalog import identify_target_parts
    assert identify_target_parts([], (100, 100)) == ("", "")


def test_common_name_for_reads_the_curated_table():
    """vdB142 has no common name in openngc.csv; common_names.csv supplies it."""
    from nocturne.core.catalog import common_name_for
    assert common_name_for("vdB142") == "Elephant's Trunk Nebula"
    assert common_name_for("NGC7000") == "North America Nebula"
    assert common_name_for("NGC 7000") == "North America Nebula"   # spaces tolerated
    assert common_name_for("NGC9999") == ""                        # absent, not an error
