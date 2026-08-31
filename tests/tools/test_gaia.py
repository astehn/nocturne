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


# --- telling the three failures apart (2026-08-17) ---------------------------
# Reported by Andreas: "Couldn't reach Gaia" appears often, and he suspected it
# might be bogus. It was: GaiaError was raised from two unrelated places and the
# step reported both as unreachable, discarding the reason entirely.

_VIZIER_HEADER = (
    "#\n#   VizieR Astronomical Server vizier.cds.unistra.fr\n"
    "#    Date: 2026-08-17T17:26:58 [V7.5.8]\n#\n"
)


def test_a_failed_request_is_reported_as_unreachable():
    from nocturne.tools.gaia import GaiaUnreachable, query_field

    def boom(url):
        raise OSError("Name or service not known")

    with pytest.raises(GaiaUnreachable) as e:
        query_field(10.0, 41.0, 0.5, fetch=boom)
    assert "Name or service not known" in str(e.value), (
        "the underlying reason was discarded — the log can say nothing useful")


def test_a_valid_answer_with_no_matching_stars_is_NOT_unreachable():
    """Gaia answered perfectly well. Calling that 'couldn't reach Gaia' sends the
    user looking at their network for a problem that is not there."""
    from nocturne.tools.gaia import GaiaNoStars, GaiaUnreachable, query_field
    with pytest.raises(GaiaNoStars) as e:
        query_field(10.0, 41.0, 0.5, fetch=lambda url: _VIZIER_HEADER)
    assert not isinstance(e.value, GaiaUnreachable)


def test_an_unreadable_answer_is_reported_separately_and_quotes_it():
    """The case that actually bites: under load VizieR returns a throttle or
    error page. The fetch SUCCEEDS, no rows parse, and the user was told the
    service could not be reached. Reproduced against the live service while
    investigating this."""
    from nocturne.tools.gaia import GaiaBadResponse, query_field
    body = "<html><head><title>503 Service Unavailable</title></head></html>"
    with pytest.raises(GaiaBadResponse) as e:
        query_field(10.0, 41.0, 0.5, fetch=lambda url: body)
    assert "503" in str(e.value), (
        "the response was not quoted, so the log cannot show what came back")


def test_all_three_remain_catchable_as_GaiaError():
    """Callers that only care that it failed must keep working."""
    from nocturne.tools.gaia import (GaiaBadResponse, GaiaError, GaiaNoStars,
                                     GaiaUnreachable)
    for cls in (GaiaUnreachable, GaiaNoStars, GaiaBadResponse):
        assert issubclass(cls, GaiaError)


def test_a_good_answer_still_parses():
    from nocturne.tools.gaia import query_field
    body = _VIZIER_HEADER + "\n".join([
        "RA_ICRS\tDE_ICRS\tGmag\tBP-RP", "deg\tdeg\tmag\tmag", "---\t---\t---\t---",
        "274.46109074146\t-14.13118862167\t13.808144\t1.003389",
        "275.06002573092\t-13.59705855421\t11.783297\t1.751653",
    ])
    stars = query_field(274.7, -13.8, 0.5, fetch=lambda url: body)
    assert len(stars) == 2
    assert stars[0].g_mag == pytest.approx(13.808144)


# --- fail fast when Gaia is unreachable, wait when it is merely slow ---------
# Andreas: "If gaia cant be reached fail fast. If gaia can be reached but it
# takes time to get a response then thats fine."

def test_an_unreachable_service_fails_without_waiting_for_the_query():
    """Measured 2026-08-17: the real query takes 12-18 s and can run past 45 s on
    a dense field, so the read timeout has to stay generous. A cheap reachability
    probe separates the two questions — a HEAD costs 0.48 s when the service is
    up, returns instantly on a DNS failure, and hits its own 5 s limit when the
    route is black-holed, against 60 s before."""
    from nocturne.tools.gaia import GaiaUnreachable, query_field

    fetched = []

    def probe():
        raise OSError("nodename nor servname provided")

    with pytest.raises(GaiaUnreachable) as e:
        query_field(10.0, 41.0, 0.5, probe=probe,
                    fetch=lambda url: fetched.append(url) or _VIZIER_HEADER)
    assert not fetched, "the slow query ran anyway — nothing was gained"
    assert "nodename" in str(e.value), "the probe's reason was discarded"


def test_a_reachable_but_slow_service_is_left_alone():
    """The complement, and the reason the read timeout is NOT being shortened:
    once the probe says the service is there, a slow answer is fine."""
    from nocturne.tools.gaia import query_field
    body = _VIZIER_HEADER + "274.4\t-14.1\t13.8\t1.0"
    stars = query_field(274.7, -13.8, 0.5, probe=lambda: None, fetch=lambda url: body)
    assert len(stars) == 1


def test_injecting_a_fetch_skips_the_probe(monkeypatch):
    """Tests and callers that supply their own fetch must not reach the network
    to satisfy a reachability check.

    Asserted by making the real probe RAISE rather than by observing that it
    happens to succeed — the first version passed on a mutation that always
    probed, simply because this machine was online.
    """
    import nocturne.tools.gaia as gaia

    def must_not_run():
        raise AssertionError("the default probe reached the network")

    monkeypatch.setattr(gaia, "_default_probe", must_not_run)
    body = _VIZIER_HEADER + "274.4\t-14.1\t13.8\t1.0"
    assert len(gaia.query_field(274.7, -13.8, 0.5, fetch=lambda url: body)) == 1


# --- a certificate failure is not a network failure (2026-08-31) -------------

def _ssl_verify_error():
    """What urllib actually raises: a URLError with the SSL error in .reason,
    so the exception TYPE alone cannot tell you this was TLS."""
    import ssl
    import urllib.error
    return urllib.error.URLError(ssl.SSLCertVerificationError(
        1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
           "unable to get local issuer certificate"))


def test_a_tls_failure_is_its_own_kind_of_failure():
    """Until v0.21.0 the built app shipped no CA certificates, so this failed on
    every Mac that was not the build machine — and was reported as "Couldn't
    reach Gaia". That named a plausible cause instead of the real one, and the
    problem sat in the backlog as a slow catalogue for weeks while SPCC simply
    never worked on Andreas' MacBook Pro."""
    from nocturne.tools.gaia import GaiaTlsError, query_field

    def fetch(url):
        raise _ssl_verify_error()

    with pytest.raises(GaiaTlsError):
        query_field(10.0, 41.0, 0.5, fetch=fetch)


def test_a_tls_failure_in_the_reachability_probe_is_caught_too():
    """The probe runs first, so on a machine with no certificates it is what
    fails — the query never gets a chance."""
    from nocturne.tools.gaia import GaiaTlsError, query_field

    def probe():
        raise _ssl_verify_error()

    with pytest.raises(GaiaTlsError):
        query_field(10.0, 41.0, 0.5, fetch=lambda u: "", probe=probe)


def test_an_ordinary_outage_is_still_plain_unreachable():
    """The new class must not swallow the common case: a real outage should
    still say the catalogue could not be reached, not blame certificates."""
    import urllib.error
    from nocturne.tools.gaia import GaiaTlsError, GaiaUnreachable, query_field

    with pytest.raises(GaiaUnreachable) as e:
        query_field(10.0, 41.0, 0.5,
                    fetch=lambda u: (_ for _ in ()).throw(
                        urllib.error.URLError(TimeoutError("timed out"))))
    assert not isinstance(e.value, GaiaTlsError)


def test_a_certificate_error_still_satisfies_older_handlers():
    """GaiaTlsError subclasses GaiaUnreachable deliberately: every caller
    written before it existed must keep catching it."""
    from nocturne.tools.gaia import GaiaError, GaiaTlsError, GaiaUnreachable
    assert issubclass(GaiaTlsError, GaiaUnreachable)
    assert issubclass(GaiaTlsError, GaiaError)
