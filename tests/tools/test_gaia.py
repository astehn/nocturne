import pytest
from nocturne.tools.gaia import query_field, GaiaStar, GaiaError

# A canned VizieR asu-tsv response: '#' comment block, then header / units /
# separator rows, then tab-separated data (one with a blank BP-RP -> skipped).
_TSV = (
    "#comment line from VizieR\n"
    "\n"
    "RA_ICRS\tDE_ICRS\tGmag\tBP-RP\n"
    "deg\tdeg\tmag\tmag\n"
    "---------------\t---------------\t---------\t---------\n"
    "314.750000\t+44.310000\t9.12\t0.83\n"
    "314.760000\t+44.320000\t11.40\t1.55\n"
    "314.770000\t+44.330000\t10.01\t\n"          # blank BP-RP -> dropped
)


def test_query_field_parses_and_builds_url():
    seen = {}
    def fake_fetch(url):
        seen["url"] = url
        return _TSV
    stars = query_field(314.75, 44.31, 1.2, fetch=fake_fetch)
    assert len(stars) == 2                                   # the blank-BP-RP row dropped
    assert isinstance(stars[0], GaiaStar)
    assert abs(stars[0].ra_deg - 314.75) < 1e-6 and abs(stars[0].bp_rp - 0.83) < 1e-6
    assert abs(stars[0].g_mag - 9.12) < 1e-6
    assert "I/355/gaiadr3" in seen["url"]                    # VizieR Gaia DR3 catalogue
    assert "314.75" in seen["url"] and "44.31" in seen["url"] and "1.2" in seen["url"]


def test_query_field_raises_on_fetch_error():
    def boom(url):
        raise OSError("no network")
    with pytest.raises(GaiaError):
        query_field(1.0, 2.0, 0.5, fetch=boom)


def test_query_field_raises_on_empty():
    with pytest.raises(GaiaError):
        query_field(1.0, 2.0, 0.5, fetch=lambda url: "#no data\nRA_ICRS\tDE_ICRS\tGmag\tBP-RP\n")
