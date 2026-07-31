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
