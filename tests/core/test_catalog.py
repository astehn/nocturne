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
        ("NGC B", "", 100.0, 5.0, 5.0),            # 5 deg north -> far out of a ~0.6x0.3 deg field
    ]
    objs = objects_in_field(wcs, (1080, 1920), rows=rows)
    names = [o.name for o in objs]
    assert "NGC A" in names and "NGC B" not in names
    a = next(o for o in objs if o.name == "NGC A")
    assert abs(a.x - 960) < 2 and abs(a.y - 540) < 2      # centre pixel


def test_identify_target_picks_largest():
    objs = [
        CatalogObject("NGC A", "Alpha", 100.0, 0.0, 5.0, 900, 540),
        CatalogObject("NGC B", "Beta", 100.0, 0.0, 40.0, 1000, 540),
    ]
    assert identify_target(objs, (1080, 1920)) == "NGC B · Beta"
    assert identify_target([], (1080, 1920)) == ""
