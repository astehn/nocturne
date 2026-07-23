import pytest
from nocturne.tools.gaia import query_field, GaiaStar, GaiaError

_CSV = ("ra,dec,phot_g_mean_mag,bp_rp\n"
        "314.750000,44.310000,9.12,0.83\n"
        "314.760000,44.320000,11.40,1.55\n"
        "314.770000,44.330000,10.01,\n")          # missing bp_rp -> skipped


def test_query_field_parses_and_builds_url():
    seen = {}
    def fake_fetch(url):
        seen["url"] = url
        return _CSV
    stars = query_field(314.75, 44.31, 1.2, fetch=fake_fetch)
    assert len(stars) == 2                                   # the empty-bp_rp row dropped
    assert isinstance(stars[0], GaiaStar)
    assert abs(stars[0].ra_deg - 314.75) < 1e-6 and abs(stars[0].bp_rp - 0.83) < 1e-6
    assert "gaiadr3.gaia_source" in seen["url"]
    assert "314.75" in seen["url"] and "44.31" in seen["url"] and "1.2" in seen["url"]


def test_query_field_raises_on_fetch_error():
    def boom(url):
        raise OSError("no network")
    with pytest.raises(GaiaError):
        query_field(1.0, 2.0, 0.5, fetch=boom)


def test_query_field_raises_on_empty():
    with pytest.raises(GaiaError):
        query_field(1.0, 2.0, 0.5, fetch=lambda url: "ra,dec,phot_g_mean_mag,bp_rp\n")
