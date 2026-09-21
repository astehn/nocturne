"""Submitting a finished picture to the wall.

Spec §3. The payload is built here rather than in the dialog so it can be
tested without a window, and so the one rule that matters — no location, ever —
is enforced in a single function.
"""
import urllib.error

import pytest

from nocturne.core import submit as S


# The shape fits_io actually produces: lowercase, normalised keys — NOT raw
# FITS card names. resolve_integration reads `livetime`/`exposure`/`frames`,
# and a fixture using EXPTIME silently resolves to None, which would have let a
# payload with no capture data pass as correct.
META = {
    "target": "NGC 7000", "frames": 163, "livetime": 3260.0, "exposure": 20.0,
    "date": "2026-08-09T23:14:02", "creator": "ZWO Seestar S30 Pro",
}


def _boom(*a, **k):
    raise AssertionError("must not reach the network")


def test_fields_carry_the_facts_the_wall_renders():
    f = S.submission_fields(META, "@andreas")
    assert f["handle"] == "@andreas"
    assert f["target"] == "NGC 7000"
    assert f["frames"] == "163"
    assert f["integration_s"] == "3260"
    assert f["sub_s"] == "20.00"
    assert f["instrument"] == "ZWO Seestar S30 Pro"
    assert f["captured_on"] == "2026-08-09"      # the DATE, never the time


def test_consent_is_a_field_the_caller_must_set():
    """The endpoint refuses a submission without it, and the dialog only sets
    it when the tick is on. It is never defaulted here."""
    assert "consent" not in S.submission_fields(META, "@a")


def test_NO_LOCATION_EVER_reaches_the_payload():
    """The one rule. `metadata` is a raw FITS-derived dict and carries whatever
    the header held, so the fields are NAMED, never copied."""
    dirty = dict(META, SITELAT="55.6", SITELONG="13.0", location="Malmo",
                 OBSERVER="A Stehn", site="backyard")
    blob = " ".join(S.submission_fields(dirty, "@a").values()).lower()
    for leak in ("55.6", "13.0", "malmo", "backyard", "observer"):
        assert leak not in blob, f"{leak!r} reached the payload"


def test_a_sparse_capture_still_produces_a_payload():
    """A master with almost no header must still be submittable; the wall
    renders what it has."""
    f = S.submission_fields({"target": "M 31"}, "@a")
    assert f["handle"] == "@a" and f["target"] == "M 31"
    assert all(isinstance(v, str) for v in f.values())


def test_empty_values_are_dropped_rather_than_sent_blank():
    """A blank `instrument` on the wall renders a dangling separator. Absent
    is not the same as empty, and the renderer already handles absent."""
    f = S.submission_fields({"target": "M 31"}, "@a")
    assert "instrument" not in f and "captured_on" not in f


def test_an_empty_handle_is_refused_before_the_network():
    """§3.1: the handle is the only attribution there is. Failing here saves a
    round trip and gives a better message than the endpoint's."""
    ok, msg = S.submit(b"x", META, "   ", opener=_boom)
    assert ok is False and "handle" in msg.lower()


def test_multipart_encodes_the_image_and_the_fields():
    body, ctype = S.encode_multipart({"handle": "@a"}, b"\xff\xd8\xff-jpeg", "s.jpg")
    assert ctype.startswith("multipart/form-data; boundary=")
    boundary = ctype.split("boundary=", 1)[1].encode()
    assert b'name="handle"' in body and b"@a" in body
    assert b'name="image"' in body and b'filename="s.jpg"' in body
    assert b"\xff\xd8\xff-jpeg" in body, "the image bytes must survive verbatim"
    assert body.rstrip().endswith(b"--" + boundary + b"--")


def test_a_boundary_that_collides_with_the_image_is_REGENERATED(monkeypatch):
    """A boundary occurring in the image truncates the upload, and the server
    stores a corrupt file rather than reporting an error — a failure that looks
    like success at both ends.

    Driven directly, because a RANDOM boundary never collides with an arbitrary
    payload: the first draft of this test passed a wall of "A"s and went green
    against a hardcoded boundary, which is not a test of anything.
    """
    handed = iter(["dead", "dead", "beef"])
    monkeypatch.setattr(S.secrets, "token_hex", lambda n: next(handed))
    # The image contains the first boundary, so it must not be used.
    body, ctype = S.encode_multipart({"handle": "@a"}, b"xx--dead-yy", "s.jpg")
    assert ctype.endswith("boundary=beef"), ctype
    assert b"xx--dead-yy" in body, "the image must still be sent verbatim"


def test_a_boundary_colliding_with_a_FIELD_is_also_regenerated(monkeypatch):
    """A target or handle is user text and can contain anything."""
    handed = iter(["dead", "beef"])
    monkeypatch.setattr(S.secrets, "token_hex", lambda n: next(handed))
    body, ctype = S.encode_multipart({"target": "--dead"}, b"img", "s.jpg")
    assert ctype.endswith("boundary=beef"), ctype


def test_the_delimiters_are_well_formed():
    """Two parts open with the boundary, and the body closes with the
    terminating `--boundary--`."""
    body, ctype = S.encode_multipart({"handle": "@a"}, b"img", "s.jpg")
    boundary = ctype.split("boundary=", 1)[1].encode()
    assert body.count(b"--" + boundary) == 3
    assert body.rstrip().endswith(b"--" + boundary + b"--")


def test_submit_returns_false_on_any_network_failure_and_never_raises():
    """A failed submission must not take the dialog down with it."""
    for exc in (urllib.error.URLError("down"), TimeoutError(), OSError("dns")):
        def opener(*a, _e=exc, **k):
            raise _e
        ok, msg = S.submit(b"x", META, "@a", opener=opener)
        assert ok is False and msg


class _Resp:
    status = 200

    def __init__(self, body):
        self._b = body

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_submit_reports_the_endpoints_own_errors():
    """The endpoint's messages are written for the reporter; passing them
    through beats a generic failure."""
    r = _Resp(b'{"ok":false,"errors":["That image is larger than the 15 MB limit."]}')
    ok, msg = S.submit(b"x", META, "@a", opener=lambda *a, **k: r)
    assert ok is False and "15 MB" in msg


def test_submit_survives_a_reply_that_is_not_json():
    """A proxy or an error page can answer instead of the endpoint."""
    r = _Resp(b"<html>502 Bad Gateway</html>")
    ok, msg = S.submit(b"x", META, "@a", opener=lambda *a, **k: r)
    assert ok is False and msg


def test_submit_succeeds_on_ok_true():
    r = _Resp(b'{"ok":true,"errors":[]}')
    ok, msg = S.submit(b"x", META, "@a", opener=lambda *a, **k: r)
    assert ok is True and msg


def test_submit_asks_for_JSON_and_sends_consent():
    """`ajax=1` is what makes the endpoint answer JSON rather than a page."""
    seen = {}

    def opener(req, timeout=None):
        seen["body"] = req.data
        seen["url"] = req.full_url
        return _Resp(b'{"ok":true,"errors":[]}')

    S.submit(b"x", META, "@a", opener=opener)
    assert b'name="ajax"' in seen["body"] and b"1" in seen["body"]
    assert b'name="consent"' in seen["body"]
    assert seen["url"].endswith("/submit.php")
