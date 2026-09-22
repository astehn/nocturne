"""Reporting a problem from inside Nocturne.

Task 6 of docs/superpowers/plans/2026-09-22-diagnostic-log.md.

This replaces a browser handoff that could not carry a diagnostic log: the URL
is a hard ceiling and the requirement is the opposite of a ceiling. Andreas,
2026-09-22: *"im alone in getting the support tickets and i need as much
valuable information as possible so that i can actually act on it."*
"""
import pytest

pytest.importorskip("PySide6")

from nocturne.settings import Settings  # noqa: E402
from nocturne.ui.report_dialog import ReportDialog  # noqa: E402

_CTX = {"app_version": "0.39.1", "os": "macOS 15.6 (arm64)",
        "screen": "2560 x 1440 at 2x", "window_size": "2364 x 1100",
        "log": "Command: starnet2\nstderr:\nlzw_decode"}


def _dlg(qtbot, sender=None, session="step  Crop\nstep  Stretch\n",
         previous="", session_age=9999.0, settings=None):
    d = ReportDialog(settings or Settings(), dict(_CTX),
                     sender=sender or (lambda *a, **k: (True, "Sent.")),
                     session_reader=lambda: session,
                     previous_reader=lambda: previous,
                     session_age=lambda: session_age,
                     summariser=lambda *a, **k: "Nocturne 0.39.1 · macOS")
    qtbot.addWidget(d)
    return d


# --- the log is included by default -----------------------------------------

def test_the_log_is_included_by_default(qtbot):
    """Andreas: always included for an app-initiated ticket. The tick is an
    opt-OUT, and a default-off box would quietly return us to the round trips
    this feature exists to end."""
    assert _dlg(qtbot).include_log.isChecked()


def test_unticking_says_what_it_costs(qtbot):
    """His words: "then no resolution might be able to be met". An opt-out
    with no consequence stated is a coin flip rather than a decision."""
    d = _dlg(qtbot)
    before = d.log_note.text()
    d.include_log.setChecked(False)
    assert d.log_note.text() != before
    assert "may not" in d.log_note.text().lower(), d.log_note.text()


def test_the_user_can_read_the_whole_log_before_sending(qtbot):
    """The consent property this design KEEPS. A URL-capped textarea could not
    show the log; a scrollable pane can, which is why posting from the app is
    better for privacy rather than merely bigger."""
    d = _dlg(qtbot, session="step  Crop\nstep  Stretch\n")
    assert "step  Stretch" in d.log_view.toPlainText()


# --- nothing leaves until Send ----------------------------------------------

def test_nothing_is_sent_until_send_is_pressed(qtbot):
    sent = []
    d = _dlg(qtbot, sender=lambda *a, **k: (sent.append(a), (True, "Sent."))[1])
    d.problem.setPlainText("it broke")
    assert sent == []


def test_opting_out_sends_no_log(qtbot):
    seen = {}

    def sender(fields, *a, **k):
        seen.update(fields)
        return True, "Sent."

    d = _dlg(qtbot, sender=sender)
    d.problem.setPlainText("it broke")
    d.include_log.setChecked(False)
    d._send()
    qtbot.waitUntil(lambda: bool(seen), timeout=2000)
    assert "diag_log" not in seen
    # AND the other one. `log` is _last_diagnostic — the failed command plus
    # its stderr, so absolute paths, so folder names, so possibly the user's
    # real name. It was copied into the payload unconditionally and never
    # shown in the pane, so unticking the box sent it anyway and the reporter
    # could not have known. Found by review 2026-09-22; reproduced with
    # "/Users/andreasstehn/Pictures/M31.tif" in it.
    assert "log" not in seen, (
        "the last tool error is diagnostic too, and the tick governs it")


def test_leaving_it_ticked_sends_the_log(qtbot):
    """Breaks the symmetry: the test above must fail because of the TICK, not
    because the dialog never sends a log at all."""
    seen = {}

    def sender(fields, *a, **k):
        seen.update(fields)
        return True, "Sent."

    d = _dlg(qtbot, sender=sender, session="step  Crop\n")
    d.problem.setPlainText("it broke")
    d._send()
    qtbot.waitUntil(lambda: bool(seen), timeout=2000)
    assert "step  Crop" in seen.get("diag_log", "")


# --- failure must not lose the report ---------------------------------------

def test_a_failed_send_keeps_everything_the_user_typed(qtbot):
    """A report that vanishes because the wifi dropped is worse than the
    browser handoff this replaces."""
    d = _dlg(qtbot, sender=lambda *a, **k: (False, "Could not reach the server"))
    d.problem.setPlainText("a long and carefully written description")
    d._send()
    d._finish((False, "Could not reach the server"))
    assert "a long and carefully written" in d.problem.toPlainText()
    assert "Could not reach the server" in d.status.text()
    assert d.send_btn.isEnabled(), "Retry must be possible"


def test_a_successful_send_says_so_and_stops_a_second_press(qtbot):
    d = _dlg(qtbot)
    d.problem.setPlainText("it broke")
    d._send()
    d._finish((True, "Sent. Thank you."))
    assert "Sent" in d.status.text()
    assert not d.send_btn.isEnabled(), "a second press would file it twice"


def test_an_empty_problem_cannot_be_sent(qtbot):
    """The one field the reporter must write. Everything else is prefilled."""
    d = _dlg(qtbot)
    assert not d.send_btn.isEnabled()
    d.problem.setPlainText("it broke")
    assert d.send_btn.isEnabled()
    d.problem.setPlainText("   ")
    assert not d.send_btn.isEnabled(), "whitespace is not a report"


# --- the crash signature ----------------------------------------------------

def test_the_previous_session_travels_when_this_one_is_seconds_old(qtbot):
    """The relaunched-after-a-crash signature, and the whole reason two
    sessions are kept: the app dies, the user reopens it, and only THEN thinks
    to report — by which time the session that went wrong is the previous one."""
    d = _dlg(qtbot, session="step  Crop\n", previous="ERROR segfault\n",
             session_age=2.0)
    assert "segfault" in d.log_view.toPlainText()
    assert "step  Crop" in d.log_view.toPlainText(), "and this session too"


def test_a_long_running_session_does_not_drag_the_previous_one_along(qtbot):
    """An hour in, the previous session is not evidence — it is noise in a
    ticket read by one person."""
    d = _dlg(qtbot, session="step  Crop\n", previous="ERROR segfault\n",
             session_age=3600.0)
    assert "segfault" not in d.log_view.toPlainText()


# --- the summary is built OFF the interface thread --------------------------

def test_the_dialog_opens_before_the_tools_are_probed(qtbot):
    """A review raised it: summary_block probes four tools serially and ASTAP's
    takes 60 seconds (measured 2026-09-22), so building it inline would freeze
    the dialog on exactly the machines that have the most to report."""
    import time

    def slow(*a, **k):
        time.sleep(3)
        return "Nocturne 0.39.1"

    started = time.monotonic()
    d = ReportDialog(Settings(), dict(_CTX), sender=lambda *a, **k: (True, ""),
                     session_reader=lambda: "", previous_reader=lambda: "",
                     session_age=lambda: 9999.0, summariser=slow)
    qtbot.addWidget(d)
    assert time.monotonic() - started < 1.0, "the probes ran on the UI thread"


def test_the_summary_appears_once_it_is_ready(qtbot):
    d = _dlg(qtbot)
    d._summary_ready("Nocturne 0.39.1 · GraXpert 3.0.2 · ASTAP (version unknown)")
    assert "GraXpert 3.0.2" in d.log_view.toPlainText()


def test_a_summary_that_fails_does_not_stop_the_report(qtbot):
    """A probe is a nicety; the report is the point."""
    d = _dlg(qtbot)
    d.problem.setPlainText("it broke")
    d._summary_failed(RuntimeError("probe blew up"))
    assert d.send_btn.isEnabled()


# --- what actually goes in the payload --------------------------------------

def test_the_prefilled_context_is_sent(qtbot):
    seen = {}

    def sender(fields, *a, **k):
        seen.update(fields)
        return True, "Sent."

    d = _dlg(qtbot, sender=sender)
    d.problem.setPlainText("it broke")
    d._send()
    qtbot.waitUntil(lambda: bool(seen), timeout=2000)
    assert seen["app_version"] == "0.39.1"
    assert seen["os"] == "macOS 15.6 (arm64)"
    assert "lzw_decode" in seen["log"], "the last tool error still travels"


# --- Task 7: the handoff is replaced ----------------------------------------

def test_report_a_problem_opens_the_dialog_not_a_browser(qtbot, tmp_path, monkeypatch):
    """The handoff could not carry a log — the URL is a hard ceiling — and the
    requirement is the opposite of a ceiling.

    The WEB form is untouched and still serves web-initiated reports, which
    send no log: a visitor cannot be asked to find a file on their disk."""
    from PySide6.QtGui import QDesktopServices
    from nocturne.ui.main_window import MainWindow

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda u: opened.append(u))
    shown = []
    monkeypatch.setattr(ReportDialog, "exec", lambda self: shown.append(self))

    win = MainWindow(settings_path=str(tmp_path / "s.json"))
    qtbot.addWidget(win)
    win._report_problem()

    assert shown, "the in-app dialog never opened"
    assert opened == [], "a browser must not be used for an app-initiated report"


def test_the_dialog_is_given_the_context_the_handoff_used_to_carry(qtbot, tmp_path, monkeypatch):
    """_report_context is unchanged and still the source of version, OS,
    screen, window size and the last tool error — the screen line exists
    because users reported sizing problems saying only "a MacBook Pro"."""
    from nocturne.ui.main_window import MainWindow

    seen = {}
    monkeypatch.setattr(ReportDialog, "exec", lambda self: seen.update(self._context))
    win = MainWindow(settings_path=str(tmp_path / "s.json"))
    qtbot.addWidget(win)
    win._report_problem()
    assert seen.get("app_version")
    assert "screen" in seen



def test_the_last_tool_error_is_SHOWN_as_well_as_sent(qtbot):
    """The consent property is "you send what you see". A field carried in the
    payload but absent from the pane cannot be consented to, whichever way the
    tick is set."""
    d = _dlg(qtbot)
    shown = d.log_view.toPlainText()
    assert "lzw_decode" in shown, "the failure is the most important line in a ticket"


def test_the_last_tool_error_travels_when_the_box_is_ticked(qtbot):
    """Breaks the symmetry: the opt-out test above must fail because of the
    TICK, not because the field is never sent at all."""
    seen = {}

    def sender(fields, *a, **k):
        seen.update(fields)
        return True, "Sent."

    d = _dlg(qtbot, sender=sender)
    d.problem.setPlainText("it broke")
    d._send()
    qtbot.waitUntil(lambda: bool(seen), timeout=2000)
    assert "lzw_decode" in seen.get("log", "")


# --- one send, once (review 2026-09-22) -------------------------------------

def test_typing_during_a_send_does_not_start_a_second_one(qtbot):
    """`textChanged` re-enables Send, which defeated the in-flight guard: press
    Send, then fix a typo — the ordinary thing a person does — and two POSTs
    went out. Reproduced by the review as two concurrent filings."""
    sent = []

    def sender(fields, *a, **k):
        sent.append(fields["problem"])
        return True, "Sent."

    d = _dlg(qtbot, sender=sender)
    d.problem.setPlainText("it broke")
    d._send()
    d.problem.setPlainText("it broke badly")     # a typo fix, mid-flight
    assert not d.send_btn.isEnabled(), "a second send is one keystroke away"


def test_typing_after_a_SUCCESSFUL_send_does_not_re_arm_the_button(qtbot):
    """Same mechanism, worse outcome: the ticket is filed twice and the
    reporter cannot see the queue to know they did it."""
    d = _dlg(qtbot)
    d.problem.setPlainText("it broke")
    d._send()
    d._finish((True, "Sent."))
    d.problem.setPlainText("it broke, a bit more detail")
    assert not d.send_btn.isEnabled()


def test_the_button_comes_back_after_a_FAILED_send(qtbot):
    """Breaks the symmetry: the two above must hold without freezing the form
    permanently. A failure has to be retryable."""
    d = _dlg(qtbot)
    d.problem.setPlainText("it broke")
    d._send()
    d._finish((False, "Could not reach the server"))
    assert d.send_btn.isEnabled()
    d.problem.setPlainText("it broke, clarified")
    assert d.send_btn.isEnabled()


# --- the crash window must measure the START, not the last write ------------

def test_session_age_is_measured_from_when_the_session_STARTED(tmp_path, monkeypatch):
    """It stat'ed the log's MTIME, which every step and every tool run updates.
    So a user two hours in who hits an error — which writes a line — and
    reports immediately read as "seconds old", and the whole previous session
    was appended to their ticket. The common case, always wrong, and invisible
    because both crash-window tests inject the age rather than compute it.

    Found by review 2026-09-22.
    """
    import time
    from nocturne.core import sessionlog
    from nocturne.ui import report_dialog

    sessionlog.start_session(str(tmp_path))
    assert report_dialog._session_age() < 5, "a session just opened is new"

    # Two hours in...
    monkeypatch.setattr(sessionlog, "_started_at", time.monotonic() - 7200)
    assert report_dialog._session_age() > 7000

    # ...and a write NOW is activity, not a restart.
    sessionlog.write("ERROR something failed")
    assert report_dialog._session_age() > 7000, (
        "the mtime moved; the age must not")


def test_a_session_that_never_started_is_not_treated_as_a_crash(tmp_path, monkeypatch):
    """Unknown must not read as "seconds old", or every report with no session
    would drag a previous one in."""
    from nocturne.core import sessionlog
    from nocturne.ui import report_dialog
    monkeypatch.setattr(sessionlog, "_started_at", None)
    assert report_dialog._session_age() == float("inf")


# --- the fallback the spec requires (review 2026-09-22) ---------------------

def test_a_failed_send_offers_the_browser_fallback(qtbot):
    """The spec requires it and it was wired to nothing: `grep` found
    `_report_problem_in_a_browser` only in its own def line, a docstring and a
    test. Offline, the reporter got "could not reach the server" and no route
    to the web form at all."""
    d = _dlg(qtbot, sender=lambda *a, **k: (False, "Could not reach the server"))
    d.problem.setPlainText("it broke")
    assert d.fallback_btn.isHidden(), "offered before anything has gone wrong"
    d._send()
    d._finish((False, "Could not reach the server"))
    assert not d.fallback_btn.isHidden(), \
        "no way out when the send cannot get through"


def test_the_fallback_is_not_offered_when_the_send_worked(qtbot):
    d = _dlg(qtbot)
    d.problem.setPlainText("it broke")
    d._send()
    d._finish((True, "Sent."))
    assert d.fallback_btn.isHidden()


def test_the_fallback_carries_what_was_typed(qtbot):
    """Opening a blank web form after a failed send would lose the report — the
    thing this whole path exists to prevent."""
    opened = {}
    d = _dlg(qtbot)
    d._on_fallback = lambda text: opened.setdefault("problem", text)
    d.problem.setPlainText("a long and carefully written description")
    d._send()
    d._finish((False, "offline"))
    d.fallback_btn.click()
    assert "carefully written" in opened.get("problem", "")


def test_a_late_reply_does_not_touch_a_destroyed_dialog(qtbot):
    """A probe can run for four tool timeouts and a send for thirty seconds.
    Quitting inside either window destroys the widget while the worker is still
    going, and the queued signal lands on freed memory — the v0.38.0 segfault
    shape, reached by the receiver dying rather than the runnable."""
    import shiboken6
    # NOT registered with qtbot: it closes every widget it knows at teardown,
    # and this one is deliberately destroyed inside the test.
    d = ReportDialog(Settings(), dict(_CTX), sender=lambda *a, **k: (True, ""),
                     session_reader=lambda: "", previous_reader=lambda: "",
                     session_age=lambda: 9999.0, summariser=lambda *a, **k: "")
    d.problem.setPlainText("it broke")
    shiboken6.delete(d)
    # Both callbacks must survive the object they belong to.
    ReportDialog._finish(d, (True, "Sent."))
    ReportDialog._summary_ready(d, "Nocturne 0.39.1")
