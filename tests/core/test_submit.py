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


# --- the picture that is sent (2026-09-22) ---------------------------------

def _astro(h, w):
    import numpy as np
    from nocturne.core.image import AstroImage
    rng = np.random.default_rng(5)
    return AstroImage(rng.random((h, w, 3)).astype("float32"))


def test_jpeg_bytes_is_the_EXPORTS_own_pixels():
    """It goes through display_data + _to_uint exactly as save_png does, so a
    submission cannot differ from the file the same step would write. That is
    the whole reason submitting moved out of the Share dialog."""
    import inspect
    from nocturne.core import export
    src = inspect.getsource(export.jpeg_bytes)
    assert "display_data(" in src and "_to_uint(" in src


def test_jpeg_bytes_caps_the_longest_edge():
    from PIL import Image
    import io
    from nocturne.core.export import jpeg_bytes
    data = jpeg_bytes(_astro(1200, 2400), 900)
    im = Image.open(io.BytesIO(data))
    assert max(im.size) == 900
    assert abs(im.size[0] / im.size[1] - 2.0) < 0.02, "aspect must survive"


def test_jpeg_bytes_NEVER_upscales():
    """Upscaling adds pixels without detail, and a bigger upload with them.

    This pins PIL's guarantee rather than our own code: thumbnail() never
    enlarges, which is why jpeg_bytes has no size check. A mutation of the
    check could not fail this test, because there is no check — the honest
    response was to delete the redundant guard rather than keep a test that
    appeared to cover it.
    """
    from PIL import Image
    import io
    from nocturne.core.export import jpeg_bytes
    im = Image.open(io.BytesIO(jpeg_bytes(_astro(300, 400), 2400)))
    assert im.size == (400, 300)


def test_jpeg_bytes_survives_a_MONO_image():
    """A single-channel master must not raise on the way to the wall."""
    import io
    import numpy as np
    from PIL import Image
    from nocturne.core.image import AstroImage
    from nocturne.core.export import jpeg_bytes
    mono = AstroImage(np.random.default_rng(1).random((200, 300)).astype("float32"))
    im = Image.open(io.BytesIO(jpeg_bytes(mono, 900)))
    assert im.mode == "RGB", "JPEG needs three channels"


# --- the plate solve that goes with a submission (2026-10-18) ---------------
#
# Spec docs/superpowers/specs/2026-10-18-app-sends-solve-design.md. The app
# sends its solve rescaled to the uploaded JPEG's own pixels, so the server can
# check it against the stored file with the star check instead of running
# ASTAP. Every test here works from the REAL ASTAP header of an NGC 7000 frame:
# a synthetic WCS is self-consistent under either convention (see
# test_catalog's _REAL_ASTAP_WCS note) and cannot catch a wrong one.

import json as _json

from tests.core.test_catalog import _REAL_ASTAP_WCS, _REAL_ROWS, _REAL_SHAPE


def _thumb_size(h, w, edge=S.SUBMIT_EDGE):
    """(w, h) PIL's thumbnail() gives a (h, w) picture — the size jpeg_bytes
    uploads, rounding included."""
    from PIL import Image
    im = Image.new("L", (w, h))
    im.thumbnail((edge, edge))
    return im.size


def _wcs_from_field(field):
    """The WCS a receiver builds from the field: plain TAN, nothing else."""
    from astropy.io import fits
    from astropy.wcs import WCS
    d = _json.loads(field)
    h = fits.Header()
    h["CTYPE1"], h["CTYPE2"] = "RA---TAN", "DEC--TAN"
    h["CRVAL1"], h["CRVAL2"] = d["crval"]
    h["CRPIX1"], h["CRPIX2"] = d["crpix"]
    (h["CD1_1"], h["CD1_2"]), (h["CD2_1"], h["CD2_2"]) = d["cd"]
    return WCS(h)


def _real_wcs():
    from astropy.io import fits
    from astropy.wcs import WCS
    return WCS(fits.Header(_REAL_ASTAP_WCS))


def test_the_sky_field_lands_every_star_where_the_resize_puts_it():
    """A star at 0-based (x, y) in the solved frame sits at (x+0.5)*sx - 0.5 in
    the resized one: a whole-image resize maps outer edge to outer edge.

    The frame is non-square and its thumbnail rounds the two axes differently
    (sx != sy), so a swap of the factors moves stars too. Must fail against:
    dropping the 0.5 terms (~0.16 px here); swapping sx and sy; scaling CRVAL;
    scaling the CD matrix by rows instead of columns."""
    h, w = _REAL_SHAPE
    tw, th = _thumb_size(h, w)
    sx, sy = tw / w, th / h
    assert abs(sx - sy) > 1e-4, "fixture: the axes must round differently"
    field = S.sky_wcs_field(dict(_REAL_ASTAP_WCS), (h, w), (tw, th))
    orig, scaled = _real_wcs(), _wcs_from_field(field)
    ras = [r[2] for r in _REAL_ROWS]
    decs = [r[3] for r in _REAL_ROWS]
    x0, y0 = orig.world_to_pixel_values(ras, decs)
    x1, y1 = scaled.world_to_pixel_values(ras, decs)
    for a, b, c, d in zip(x0, y0, x1, y1):
        assert c == pytest.approx((a + 0.5) * sx - 0.5, abs=0.01)
        assert d == pytest.approx((b + 0.5) * sy - 0.5, abs=0.01)
    # The fixture reaches far from the reference pixel, or a swapped factor
    # would hide inside the tolerance.
    assert max(abs(a - (_REAL_ASTAP_WCS["CRPIX1"] - 1)) for a in x0) > 500


def test_the_sky_field_is_exactly_the_agreed_shape():
    """Compact JSON, these keys and no others — the server validates against
    exactly this. Nothing else from the header can ride along."""
    h, w = _REAL_SHAPE
    tw, th = _thumb_size(h, w)
    hdr = dict(_REAL_ASTAP_WCS, SITELAT=57.7, SITELONG=11.9, OBSERVER="someone")
    field = S.sky_wcs_field(hdr, (h, w), (tw, th))
    d = _json.loads(field)
    assert set(d) == {"v", "w", "h", "crval", "crpix", "cd"}
    assert d["v"] == 1 and (d["w"], d["h"]) == (tw, th)
    assert isinstance(d["w"], int) and isinstance(d["h"], int)
    assert d["crval"] == [_REAL_ASTAP_WCS["CRVAL1"], _REAL_ASTAP_WCS["CRVAL2"]]
    assert " " not in field
    for bad in ("57.7", "11.9", "someone", "SITE"):
        assert bad not in field


def test_an_unscaled_send_keeps_the_solve_exactly():
    """A picture already under the cap is uploaded at its own size: the field
    is the solve itself, unchanged."""
    h, w = _REAL_SHAPE
    d = _json.loads(S.sky_wcs_field(dict(_REAL_ASTAP_WCS), (h, w), (w, h)))
    assert d["crpix"] == [_REAL_ASTAP_WCS["CRPIX1"], _REAL_ASTAP_WCS["CRPIX2"]]
    cd = _real_wcs().pixel_scale_matrix
    assert d["cd"] == [[cd[0, 0], cd[0, 1]], [cd[1, 0], cd[1, 1]]]


@pytest.mark.parametrize("change", [
    {"CRVAL1": float("nan")},
    {"CD_INF": None},
    {"CTYPE1": "RA---SIN", "CTYPE2": "DEC--SIN"},
    {"CTYPE1": "GLON-TAN", "CTYPE2": "GLAT-TAN"},
    {"PC1_1": 0.0, "PC1_2": 0.0},
    {"LONPOLE": 0.0},
])
def test_a_solve_the_receiver_could_misread_sends_nothing(change):
    """None rather than a field: a projection, frame or pole the receiver's
    plain TAN would not reproduce, a non-finite number or a singular matrix."""
    hdr = dict(_REAL_ASTAP_WCS)
    if "CD_INF" in change:
        hdr["PC2_2"] = float("inf")
    else:
        hdr.update(change)
    h, w = _REAL_SHAPE
    assert S.sky_wcs_field(hdr, (h, w), _thumb_size(h, w)) is None


@pytest.mark.parametrize("solved, sent", [((0, 10), (10, 10)), ((10, 10), (0, 5)),
                                          ((10, 10), (-5, 5))])
def test_a_degenerate_size_sends_nothing(solved, sent):
    assert S.sky_wcs_field(dict(_REAL_ASTAP_WCS), solved, sent) is None


def test_the_sky_field_is_posted_only_when_given_a_string():
    """No solve means no field — never an empty one, never a placeholder — and
    the rest of the payload is the same either way. Must fail against: always
    adding the key."""
    seen = []

    def opener(req, timeout=None):
        seen.append(req.data)
        return _Resp(b'{"ok":true,"errors":[]}')

    S.submit(b"img", META, "@a", opener=opener)
    S.submit(b"img", META, "@a", opener=opener, sky_wcs=None)
    S.submit(b"img", META, "@a", opener=opener, sky_wcs='{"v":1}')

    def names(body):
        import re
        return re.findall(rb'name="([^"]+)"', body)

    assert b"sky_wcs" not in seen[0] and b"sky_wcs" not in seen[1]
    with_it = names(seen[2])
    assert with_it.count(b"sky_wcs") == 1
    assert [n for n in with_it if n != b"sky_wcs"] == names(seen[0])
    assert b'name="sky_wcs"\r\n\r\n{"v":1}\r\n' in seen[2]
