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
