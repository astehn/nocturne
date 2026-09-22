"""Build a support report and post it, from inside the app.

Andreas, 2026-09-22: *"im alone in getting the support tickets and i need as
much valuable information as possible so that i can actually act on it."* The
browser handoff this replaces could not carry a diagnostic log — the URL is a
hard ceiling, and the requirement is the opposite of a ceiling.

Shaped like `core/submit.py`, which has posted to the same server since
v0.39.0: the same multipart encoder, the same never-raises contract, and the
same rule that a refusal is reported in the ENDPOINT's words, because it knows
why it refused and this does not.

The consent property is kept and arguably improved. Nothing here runs until the
person presses Send, and unlike a URL-capped textarea the dialog can show them
the whole log first.

Qt-free: this is core/.
"""
from __future__ import annotations

import json
import urllib.request

from .submit import encode_multipart
from .update_check import SUPPORT_POST_URL

TIMEOUT = 30.0

# The five values support.php and its validator already know, shared with the
# website form. A second vocabulary for the same things would mean two code
# paths in the one place that must not break.
_CONTEXT_KEYS = ("app_version", "os", "screen", "window_size", "log")


def report_fields(problem: str, email: str, topic: str, context: dict,
                  *, diag_log: str | None) -> dict[str, str]:
    """The form fields for one report.

    `diag_log` of None or "" is OMITTED, not sent empty. "Declined" and "there
    was nothing to send" are different tickets and the admin view says so; an
    empty field would collapse them into one blank.
    """
    fields = {
        "problem": problem,
        "email": email,
        "topic": topic,
        # support.php rejects a report whose `website` is filled — that is its
        # bot gate. Sent EMPTY rather than omitted, so a future "required"
        # check on the server could not reject every app report.
        "website": "",
        # Makes the endpoint answer JSON instead of a page.
        "ajax": "1",
    }
    for key in _CONTEXT_KEYS:
        value = context.get(key)
        if value:
            fields[key] = str(value)
    if diag_log:
        fields["diag_log"] = diag_log
    return fields


def send_report(fields: dict[str, str], attachment: bytes | None = None,
                filename: str = "", content_type: str = "application/octet-stream",
                *, opener=urllib.request.urlopen, timeout: float = TIMEOUT,
                url: str = SUPPORT_POST_URL) -> tuple[bool, str]:
    """POST the report. Returns `(ok, message)` and NEVER raises.

    The message is shown to the person who pressed Send, so the endpoint's own
    wording is preferred over anything invented here.

    A failure must leave the caller able to try again with everything the
    person typed intact — a report that vanishes because the wifi dropped is
    worse than the browser handoff this replaces.
    """
    try:
        body, ctype = encode_multipart(
            fields, attachment, filename or "attachment",
            field="attachment", content_type=content_type)
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": ctype, "Content-Length": str(len(body))})
        with opener(req, timeout=timeout) as resp:
            raw = resp.read()
    except Exception as exc:                      # noqa: BLE001 — see docstring
        return False, f"Could not reach the server: {exc}"

    try:
        reply = json.loads(raw.decode("utf-8", "replace"))
    except Exception:                             # noqa: BLE001
        # A proxy or an error page answered instead of the endpoint. Saying
        # "unexpected" is honest; parsing it as a refusal would invent a reason.
        return False, "The server gave an unexpected reply. Try again later."

    if reply.get("ok"):
        return True, "Sent. Thank you — I read every one of these."
    errors = reply.get("errors") or []
    return False, str(errors[0]) if errors else "The server refused the report."
