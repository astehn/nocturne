"""Send a finished picture to the wall at nocturneastro.com.

Spec §3. Qt-free on purpose: the payload is the part worth testing, and a
dialog is a poor place to test it from. `share_dialog.py` supplies the composed
image and the consent; everything else is decided here.

WHAT THIS DELIBERATELY DOES NOT DO. It does not retry, queue, or remember. A
failed send is reported to the person who pressed the button, who can press it
again — an app holding someone's picture to upload later is an app holding
their picture.
"""
from __future__ import annotations

import json
import secrets
import urllib.request

from .fits_io import resolve_integration
from .update_check import SUBMIT_URL

TIMEOUT = 30.0

# The longest edge a SUBMISSION is composed at, independent of the size chosen
# for Export.
#
# WHY IT IS NOT THE EXPORT SIZE. Approval generates 2000 and 900 px
# derivatives, so every pixel above 2000 is discarded on arrival. Measured on a
# drizzled S30 Pro master (7680x4320): "Full size" encodes to 30.9 MB, which is
# over the endpoint's 15 MB limit — so the sender uploads 31 MB on a domestic
# connection and is then refused, for an image the wall would have thrown away
# anyway. 4096 px is 4.1 MB of the same waste.
#
# 2400 rather than exactly 2000: a little headroom above the derivative, so
# approval is downscaling rather than resampling at 1:1, and the wall's sizes
# can rise slightly without another app release.
SUBMIT_EDGE = 2400


def submission_fields(metadata: dict, handle: str) -> dict[str, str]:
    """The facts the wall renders beside a picture.

    EVERY FIELD IS NAMED. `metadata` is a raw FITS-derived dict carrying
    whatever the header held — SITELAT, SITELONG, OBSERVER — and a public
    payload built by copying it would publish a person's back garden. Naming
    them makes a leak an act rather than an oversight.

    An empty value is DROPPED rather than sent blank: the wall joins its facts
    with separators, and a blank instrument renders a dangling one.
    """
    out: dict[str, str] = {"handle": handle.strip()}

    target = str(metadata.get("target") or metadata.get("target_solved") or "").strip()
    if target:
        out["target"] = target

    integration = resolve_integration(metadata)
    if integration is not None:
        if integration.total_s:
            out["integration_s"] = str(int(round(integration.total_s)))
        if integration.frames:
            out["frames"] = str(int(integration.frames))
        if integration.per_sub_s:
            out["sub_s"] = f"{float(integration.per_sub_s):.2f}"

    # THE DATE, never the time of night. A capture time is a record of when
    # somebody was outside, which is not what a caption needs.
    captured = str(metadata.get("date") or "").strip()
    if captured:
        out["captured_on"] = captured[:10]

    instrument = str(metadata.get("creator") or metadata.get("instrument") or "").strip()
    if instrument:
        out["instrument"] = instrument

    return out


def sky_wcs_field(header: dict, solved_hw: tuple[int, int],
                  sent_wh: tuple[int, int]) -> str | None:
    """The plate solve, rescaled to the uploaded JPEG's own pixels, as the
    compact JSON of the gallery's optional `sky_wcs` field — or None.

    WHY IT GOES ALONG. A wall photo promoted to the planner has to be placed on
    the sky, and the server's ASTAP run fails on heavily processed pictures.
    With this it only has to CHECK a solve, with the same star check it already
    trusts; a field that fails the check costs nothing but the ASTAP run.

    ONLY A WHOLE-IMAGE RESIZE IS MAPPED. The caller sends this only while the
    solve's framing signature still matches, so the solved array is the
    uploaded one before thumbnail(). A resize maps outer edge to outer edge, so
    in 1-based pixels CRPIX' = (CRPIX - 0.5)*s + 0.5 per axis and each CD
    column divides by its axis's factor. `sent_wh` must be the JPEG's REAL size:
    thumbnail() rounds each axis on its own, and the factors are taken from it.

    Plain TAN only — SIP terms are dropped (the receiver builds a plain TAN,
    and the star check judges the residual). Anything that plain TAN would not
    reproduce exactly, or any non-finite or singular value, gives None: no
    field is better than one the receiver would misread.
    """
    import math

    import numpy as np
    from astropy.io import fits
    from astropy.wcs import WCS

    try:
        h, w = (int(v) for v in solved_hw)
        tw, th = (int(v) for v in sent_wh)
        if min(h, w, tw, th) <= 0:
            return None
        wcs = WCS(fits.Header(header), naxis=2)
        ctype = [str(c).upper() for c in wcs.wcs.ctype]
        if not (ctype[0].startswith("RA--") and ctype[1].startswith("DEC-")
                and all(c[4:8] == "-TAN" for c in ctype)):
            return None
        # A non-default pole rotates the projection in a way a receiver that
        # writes only CRVAL/CRPIX/CD would not repeat.
        if not math.isclose(float(wcs.wcs.lonpole), 180.0, abs_tol=1e-9):
            return None
        cd = np.array(wcs.pixel_scale_matrix, dtype=float)
        crval = [float(v) for v in wcs.wcs.crval]
        crpix = [float(v) for v in wcs.wcs.crpix]
    except Exception:                             # noqa: BLE001 — never block a send
        return None

    sx, sy = tw / w, th / h
    crpix = [(crpix[0] - 0.5) * sx + 0.5, (crpix[1] - 0.5) * sy + 0.5]
    cd = [[cd[0, 0] / sx, cd[0, 1] / sy], [cd[1, 0] / sx, cd[1, 1] / sy]]
    nums = crval + crpix + cd[0] + cd[1]
    if not all(math.isfinite(v) for v in nums):
        return None
    if cd[0][0] * cd[1][1] - cd[0][1] * cd[1][0] == 0.0:
        return None
    return json.dumps({"v": 1, "w": tw, "h": th, "crval": crval, "crpix": crpix, "cd": cd},
                      separators=(",", ":"))


def encode_multipart(fields: dict[str, str], image: bytes | None,
                     filename: str, *, field: str = "image",
                     content_type: str = "image/jpeg") -> tuple[bytes, str]:
    """`(body, content_type)` for a multipart/form-data POST.

    Written out rather than borrowed because the standard library has no
    multipart encoder and `requests` would be a dependency in every build for
    thirty lines.

    The boundary is REGENERATED until it does not occur in the payload. A
    boundary that appears inside the image truncates the upload, and the server
    stores a corrupt file instead of reporting an error — a failure that looks
    like success on both ends.

    `image=None` means FIELDS ONLY, and it is a real case rather than a
    defensive branch: a support report of words alone is valid, and
    site/tests/report_validate_test.php asserts that on the server side. The
    `field`/`content_type` arguments exist for the same caller — a report's
    part is "attachment" and may be a PNG — and default to the gallery's
    values so its call site is unchanged.
    """
    payload = image or b""
    while True:
        boundary = secrets.token_hex(16)
        marker = ("--" + boundary).encode()
        if marker not in payload and not any(
                marker in v.encode("utf-8") for v in fields.values()):
            break

    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode("utf-8"))
    if image is not None:
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        parts.append(image)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def submit(image: bytes, metadata: dict, handle: str, *,
           opener=urllib.request.urlopen, timeout: float = TIMEOUT,
           url: str = SUBMIT_URL, sky_wcs: str | None = None) -> tuple[bool, str]:
    """POST the picture. Returns `(ok, message)` and NEVER raises.

    `sky_wcs` is `sky_wcs_field`'s output, posted only when it is a string: no
    solve means no field at all. A server older than the field ignores it.

    The message is shown to the person who pressed the button, so the
    endpoint's own wording is preferred over anything invented here — it knows
    why it refused and this does not.
    """
    if not handle.strip():
        # §3.1. Caught here as well as in the dialog: this is reachable from
        # anywhere, and a picture with no attribution is not publishable.
        return False, "Set a handle in Settings before sending a picture."

    try:
        fields = submission_fields(metadata, handle)
        # Asserted by the caller having ticked the box; the endpoint refuses a
        # submission without it, and so it must be explicit rather than implied
        # by the request existing.
        fields["consent"] = "1"
        # Makes the endpoint answer JSON instead of a page.
        fields["ajax"] = "1"
        if isinstance(sky_wcs, str):
            fields["sky_wcs"] = sky_wcs
        body, ctype = encode_multipart(fields, image, "nocturne-share.jpg")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": ctype, "Content-Length": str(len(body))})
        with opener(req, timeout=timeout) as resp:
            raw = resp.read()
    except Exception as exc:                      # noqa: BLE001 — see docstring
        return False, f"Could not reach the gallery: {exc}"

    try:
        reply = json.loads(raw.decode("utf-8", "replace"))
    except Exception:                             # noqa: BLE001
        # A proxy or an error page answered instead of the endpoint.
        return False, "The gallery gave an unexpected reply. Try again later."

    if reply.get("ok"):
        return True, "Sent. It will appear on the wall once it has been looked at."
    errors = reply.get("errors") or []
    return False, str(errors[0]) if errors else "The gallery refused the picture."
