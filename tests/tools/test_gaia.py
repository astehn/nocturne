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


# --- our own copy first, VizieR second (2026-11-01) --------------------------
# Andreas: "More often than not Gaia does not work when i try it." The night
# this was decided, all of CDS Strasbourg was unreachable while he recorded a
# video. gaia.nocturneastro.com answers the same question; VizieR stays as the
# fallback, unchanged.

_MIRROR_BODY = ("#Nocturne Gaia mirror (Gaia DR3, ESA/Gaia/DPAC)\n\n"
                "RA_ICRS\tDE_ICRS\tGmag\tBP-RP\ndeg\tdeg\tmag\tmag\n---\t---\t---\t---\n"
                "274.4\t-14.1\t13.8\t1.0\n274.5\t-14.2\t12.1\t\n")
_VIZIER_BODY = _VIZIER_HEADER + "274.4\t-14.1\t13.8\t1.0\n274.6\t-14.3\t11.0\t0.5\n"


def _refuse(url):
    raise AssertionError("VizieR must not be asked when the mirror answered")


def test_the_mirror_answer_is_used_and_labelled():
    from nocturne.tools.gaia import MIRROR_LABEL
    stars = query_field(274.7, -13.8, 0.5, mirror_fetch=lambda u: _MIRROR_BODY,
                        fetch=_refuse, probe=lambda: None)
    assert len(stars) == 1                       # the blank BP-RP row still dropped
    assert stars.source == MIRROR_LABEL == "nocturneastro.com"
    assert stars.mirror_failure is None


def _vizier_after(mirror_fetch):
    asked = []
    stars = query_field(274.7, -13.8, 0.5, mirror_fetch=mirror_fetch,
                        fetch=lambda u: asked.append(u) or _VIZIER_BODY,
                        probe=lambda: None)
    return stars, asked


def test_a_mirror_failure_falls_through_to_vizier_and_is_recorded():
    def boom(url):
        raise OSError("connection refused")
    stars, asked = _vizier_after(boom)
    assert len(asked) == 1 and len(stars) == 2
    assert stars.source == "VizieR"
    assert "connection refused" in stars.mirror_failure


def test_an_empty_mirror_answer_falls_through():
    """Every field SPCC asks about has stars, so an empty answer from the mirror
    means a broken mirror, not an empty sky."""
    body = _MIRROR_BODY.split("274.4")[0]
    stars, asked = _vizier_after(lambda u: body)
    assert len(asked) == 1 and stars.source == "VizieR"
    assert stars.mirror_failure


def test_an_unmarked_mirror_answer_falls_through():
    stars, asked = _vizier_after(lambda u: "<html>Service Unavailable</html>")
    assert len(asked) == 1 and stars.source == "VizieR"
    assert "not catalogue data" in stars.mirror_failure


def test_a_vizier_marker_does_not_pass_for_the_mirror():
    """Each source is checked against its own marker: a page that merely says
    'VizieR' coming back from our host is not our answer."""
    stars, asked = _vizier_after(lambda u: _VIZIER_BODY)   # VizieR's marker AND rows
    assert len(asked) == 1 and stars.source == "VizieR"
    assert "not catalogue data" in stars.mirror_failure


def test_the_mirror_path_is_bounded_per_operation_and_in_total(monkeypatch):
    import nocturne.tools.gaia as gaia
    seen = []
    monkeypatch.setattr(gaia, "_fetch", lambda url, timeout, total=None:
                        seen.append((timeout, total)) or _MIRROR_BODY)
    gaia._default_mirror_fetch("https://example.invalid/")
    (timeout, total), = seen
    assert timeout <= 3 and total is not None and total <= 10


def test_a_trickling_server_is_cut_off_at_the_total():
    """urllib's timeout restarts on every read; a byte every 0.2 s never trips a
    1 s limit. The total must."""
    import socket
    import threading
    import time
    from nocturne.tools.gaia import _fetch
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    stop = threading.Event()

    def serve():
        conn, _ = srv.accept()
        conn.recv(4096)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n")
        end = time.monotonic() + 3     # without the total the read fails, not hangs
        try:
            while not stop.is_set() and time.monotonic() < end:
                conn.sendall(b"#")
                time.sleep(0.2)
        except OSError:
            pass
        conn.close()
    threading.Thread(target=serve, daemon=True).start()
    t0 = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            _fetch(f"http://127.0.0.1:{srv.getsockname()[1]}/", timeout=1, total=0.8)
    finally:
        stop.set()
        srv.close()
    assert time.monotonic() - t0 < 3


def test_a_body_shorter_than_its_content_length_is_refused():
    """Cut short, an unchunked answer must not parse as fewer stars."""
    import http.client
    import socket
    import threading
    from nocturne.tools.gaia import _fetch
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        conn.recv(4096)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n" + b"#" * 30)
        conn.close()
    threading.Thread(target=serve, daemon=True).start()
    try:
        with pytest.raises(http.client.IncompleteRead):
            _fetch(f"http://127.0.0.1:{srv.getsockname()[1]}/", timeout=1, total=5)
    finally:
        srv.close()


def test_a_tls_fault_on_the_mirror_is_named_even_when_vizier_is_down():
    """CDS down (why the mirror exists) plus a broken certificate store on this
    computer must not read as "Couldn't reach Gaia"."""
    import ssl
    import urllib.error
    from nocturne.tools.gaia import GaiaTlsError

    def mirror(url):
        raise urllib.error.URLError(ssl.SSLCertVerificationError("certificate verify failed"))

    def probe():
        raise OSError("timed out")
    with pytest.raises(GaiaTlsError) as e:
        query_field(10.0, 41.0, 0.5, mirror_fetch=mirror, fetch=_refuse, probe=probe)
    assert "certificate verify failed" in str(e.value) and "timed out" in str(e.value)


def test_when_both_fail_the_vizier_kind_is_raised_with_both_reasons():
    from nocturne.tools.gaia import GaiaTlsError, GaiaUnreachable

    def mirror(url):
        raise OSError("mirror down")

    def vizier(url):
        raise OSError("vizier down")
    with pytest.raises(GaiaUnreachable) as e:
        query_field(10.0, 41.0, 0.5, mirror_fetch=mirror, fetch=vizier,
                    probe=lambda: None)
    assert not isinstance(e.value, GaiaTlsError)
    msg = str(e.value)
    assert "nocturneastro.com" in msg and "mirror down" in msg
    assert "VizieR" in msg and "vizier down" in msg


def test_injecting_only_a_fetch_never_touches_the_mirror(monkeypatch):
    """Every test written before the mirror existed passes fetch= only. They
    must stay off the network: asserted by making the real mirror fetch RAISE,
    not by observing that it happens to work."""
    import nocturne.tools.gaia as gaia

    def must_not_run(url):
        raise AssertionError("the default mirror fetch reached the network")
    monkeypatch.setattr(gaia, "_default_mirror_fetch", must_not_run)
    stars = gaia.query_field(274.7, -13.8, 0.5, fetch=lambda u: _VIZIER_BODY)
    assert stars.source == "VizieR" and stars.mirror_failure is None


def test_the_real_path_asks_the_mirror_first(monkeypatch):
    import nocturne.tools.gaia as gaia
    order = []
    monkeypatch.setattr(gaia, "_default_mirror_fetch",
                        lambda u: order.append("mirror") or _MIRROR_BODY)
    monkeypatch.setattr(gaia, "_default_probe", lambda: order.append("probe"))
    monkeypatch.setattr(gaia, "_default_fetch", lambda u: order.append("vizier"))
    stars = gaia.query_field(274.7, -13.8, 0.5)
    assert order == ["mirror"] and stars.source == "nocturneastro.com"


def test_the_mirror_is_asked_the_same_question_on_a_different_host():
    seen = {}
    query_field(274.7, -13.8, 0.5, fetch=lambda u: seen.setdefault("v", u) and _VIZIER_BODY,
                probe=lambda: None)
    query_field(274.7, -13.8, 0.5, mirror_fetch=lambda u: seen.setdefault("m", u) and _MIRROR_BODY,
                fetch=_refuse, probe=lambda: None)
    v, m = seen["v"], seen["m"]
    assert v.startswith("https://vizier.cds.unistra.fr/viz-bin/asu-tsv?")
    assert m.startswith("https://gaia.nocturneastro.com/viz-bin/asu-tsv?")
    assert v.split("?", 1)[1] == m.split("?", 1)[1]
