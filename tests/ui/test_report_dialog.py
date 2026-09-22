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
