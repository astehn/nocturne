"""Building and posting a support report from inside the app.

Task 5 of docs/superpowers/plans/2026-09-22-diagnostic-log.md.

Shaped like core/submit.py, which has done a consented POST to the same server
since v0.39.0: same multipart encoder, same never-raises contract, same
preference for the endpoint's own wording over anything invented here.
"""
import json

import pytest

from nocturne.core.report import report_fields, send_report


class _Reply:
    def __init__(self, payload):
        self._raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok_opener(captured=None):
    def opener(req, timeout=None):
        if captured is not None:
            captured["body"] = req.data
            captured["url"] = req.full_url
        return _Reply({"ok": True})
    return opener


# --- the payload ------------------------------------------------------------

def test_the_log_is_OMITTED_when_the_user_opts_out():
    """Absent, not empty. The server must be able to tell "declined" from
    "there was nothing to send" — they are different tickets, and the admin
    view says so rather than showing the same blank either way."""
    fields = report_fields("it broke", "", "problem", {}, diag_log=None)
    assert "diag_log" not in fields


def test_the_log_is_present_when_it_is_included():
    fields = report_fields("it broke", "", "problem", {}, diag_log="step  Crop")
    assert fields["diag_log"] == "step  Crop"


def test_an_empty_log_is_also_omitted():
    """A session with nothing in it is "nothing to send", not "here is
    nothing" — and an empty field would read as an opt-in that found no data,
    which is a third state nobody needs."""
    assert "diag_log" not in report_fields("x", "", "problem", {}, diag_log="")


def test_the_context_travels_under_the_names_the_web_form_already_uses():
    """support.php and its validator are shared with the website form. A
    second vocabulary for the same values would mean two code paths in the one
    place that must not break."""
    ctx = {"app_version": "0.39.1", "os": "macOS", "screen": "2560x1440",
           "window_size": "1600x900"}
    fields = report_fields("it broke", "a@b.c", "problem", ctx, diag_log="x")
    for key, value in ctx.items():
        assert fields[key] == value
    assert fields["problem"] == "it broke"
    assert fields["email"] == "a@b.c"
    assert fields["topic"] == "problem"


def test_opting_out_suppresses_EVERY_diagnostic_not_just_the_session_log():
    """`log` is the failed command plus its stderr — absolute paths, folder
    names, possibly the reporter's real name. It was copied in unconditionally
    while the tick governed only `diag_log`, so unticking sent it anyway.
    Found by review 2026-09-22.

    The machine, screen and version still travel: those are what the report is
    ABOUT and carry nothing personal."""
    ctx = {"app_version": "0.39.1", "os": "macOS",
           "log": "Command: starnet2 /Users/someone/Pictures/M31.tif"}
    out = report_fields("it broke", "", "problem", ctx, diag_log=None)
    assert "log" not in out and "diag_log" not in out
    assert out["app_version"] == "0.39.1", "the version is not a diagnostic leak"


def test_ticking_it_sends_every_diagnostic():
    """Breaks the symmetry: the test above must pass because of the TICK, not
    because those fields are never sent."""
    ctx = {"app_version": "0.39.1", "log": "stderr tail"}
    out = report_fields("it broke", "", "problem", ctx, diag_log="session")
    assert out["log"] == "stderr tail" and out["diag_log"] == "session"


def test_the_honeypot_is_sent_empty():
    """support.php rejects a report whose `website` field is filled — that is
    its bot gate. The app must send it EMPTY rather than omit it, or a future
    "required" check on the server would reject every app report."""
    assert report_fields("x", "", "problem", {}, diag_log=None)["website"] == ""


def test_it_asks_the_endpoint_for_json():
    assert report_fields("x", "", "problem", {}, diag_log=None)["ajax"] == "1"


# --- the post ---------------------------------------------------------------

def test_a_successful_send_reports_success():
    ok, _msg = send_report({"problem": "x"}, opener=_ok_opener())
    assert ok is True


def test_send_never_raises_and_carries_the_reason():
    def opener(req, timeout=None):
        raise OSError("network is down")
    ok, msg = send_report({"problem": "x"}, opener=opener)
    assert ok is False and "network is down" in msg


def test_a_non_json_reply_is_reported_as_unexpected():
    """A proxy or an error page answered instead of the endpoint. Saying
    "unexpected" is honest; parsing it as a refusal would invent a reason."""
    ok, msg = send_report({"problem": "x"},
                          opener=lambda *a, **k: _Reply(b"<html>502</html>"))
    assert ok is False and "unexpected" in msg.lower()


def test_a_refusal_uses_the_ENDPOINTS_own_words():
    """It knows why it refused and this does not — the same rule submit.py
    follows."""
    ok, msg = send_report(
        {"problem": "x"},
        opener=lambda *a, **k: _Reply({"ok": False, "errors": ["Say what went wrong."]}))
    assert ok is False and msg == "Say what went wrong."


def test_a_refusal_with_no_reason_still_says_something_useful():
    ok, msg = send_report({"problem": "x"},
                          opener=lambda *a, **k: _Reply({"ok": False}))
    assert ok is False and msg.strip() != ""


# --- the attachment ---------------------------------------------------------

def test_a_report_with_no_attachment_still_posts():
    """Words alone are a valid report — site/tests/report_validate_test.php
    asserts exactly that on the server side."""
    captured = {}
    ok, _ = send_report({"problem": "x"}, opener=_ok_opener(captured))
    assert ok is True
    assert b'name="attachment"' not in captured["body"]


def test_an_attachment_is_sent_under_the_name_the_form_uses():
    captured = {}
    send_report({"problem": "x"}, attachment=b"\x89PNG\r\n", filename="shot.png",
                content_type="image/png", opener=_ok_opener(captured))
    assert b'name="attachment"; filename="shot.png"' in captured["body"]
    assert b"image/png" in captured["body"]


def test_the_diagnostic_log_is_a_FIELD_not_the_attachment():
    """They are different things and the spec says so: the attachment stays an
    optional screenshot the user chooses, the log is automatic. Sending the log
    as the attachment would silently take the slot a screenshot needs."""
    captured = {}
    fields = report_fields("x", "", "problem", {}, diag_log="step  Crop")
    send_report(fields, attachment=b"\x89PNG", filename="s.png",
                content_type="image/png", opener=_ok_opener(captured))
    body = captured["body"]
    assert b'name="diag_log"' in body
    assert b'name="attachment"; filename="s.png"' in body


def test_it_posts_to_the_support_endpoint():
    captured = {}
    send_report({"problem": "x"}, opener=_ok_opener(captured))
    assert captured["url"].endswith("support.php")


def test_it_imports_without_qt():
    """core/ is Qt-free."""
    import subprocess
    import sys
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.modules['PySide6'] = None; import nocturne.core.report"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
