"""Consent gates the network. These are the tests the privacy page depends on."""
import datetime

import pytest

pytest.importorskip("PySide6")
from nocturne.core import telemetry as t          # noqa: E402
from nocturne.settings import Settings, load_settings, save_settings  # noqa: E402
import nocturne.ui.main_window as mw              # noqa: E402


def _win(qtbot, tmp_path, settings: Settings, monkeypatch, telemetry=False):
    """A window with the network replaced by a spy.

    `telemetry=False` by default: these tests drive `_telemetry_first_run` and
    `_telemetry_ping` DIRECTLY, so the startup timer would only add a second,
    unsynchronised call. Leaving it on is how this file first blocked an
    unrelated test in test_main_window.py — the modal fired 400 ms later, inside
    someone else's test.
    """
    sent = []
    monkeypatch.setattr(t, "send", lambda payload, **kw: sent.append(payload) or True)
    monkeypatch.setattr(mw.telemetry_mod, "send", lambda payload, **kw: sent.append(payload) or True)
    path = str(tmp_path / "settings.json")
    save_settings(settings, path)
    win = mw.MainWindow(settings_path=path, check_updates=False, telemetry=telemetry)
    win._async_enabled = False
    qtbot.addWidget(win)
    return win, sent, path


def test_nothing_is_sent_before_the_question_is_answered(qtbot, tmp_path, monkeypatch):
    """The whole promise in one test. `unset` must never be treated as consent —
    not "ask later and send meanwhile", not "send one to see if it works"."""
    win, sent, _ = _win(qtbot, tmp_path, Settings(), monkeypatch)
    win._telemetry_ping()                       # the send path, called directly
    assert sent == []


def test_nothing_is_sent_when_the_answer_was_no(qtbot, tmp_path, monkeypatch):
    win, sent, _ = _win(qtbot, tmp_path, Settings(telemetry="off"), monkeypatch)
    win._telemetry_ping()
    assert sent == []


def test_saying_no_is_recorded_so_it_is_never_asked_again(qtbot, tmp_path, monkeypatch):
    """A question re-asked until the user gives in is not consent."""
    from nocturne.ui import telemetry_consent
    monkeypatch.setattr(telemetry_consent.TelemetryConsentDialog, "exec", lambda self: 0)
    win, sent, path = _win(qtbot, tmp_path, Settings(), monkeypatch)
    win._telemetry_first_run()
    assert load_settings(path).telemetry == "off"
    assert sent == []


def test_saying_yes_sends_first_run_and_one_daily(qtbot, tmp_path, monkeypatch):
    from nocturne.ui import telemetry_consent
    monkeypatch.setattr(telemetry_consent.TelemetryConsentDialog, "exec", lambda self: 1)
    win, sent, path = _win(qtbot, tmp_path, Settings(), monkeypatch)
    win._telemetry_first_run()
    assert load_settings(path).telemetry == "on"
    # WAIT for them. The pings go through run_async onto a QThreadPool — fire
    # and forget is the point, so the test cannot assume they have landed by the
    # time the call returns. This asserted immediately and passed alone while
    # failing in the full suite, which is the same ordering-dependence
    # CLAUDE.md records for the mouseMove tests.
    qtbot.waitUntil(lambda: len(sent) == 2, timeout=3000)
    # By event, not by position: the two go to a thread pool and land in either
    # order. Asserting the sequence made this fail about a third of the time for
    # a reason that does not matter to anyone.
    by_event = {p["event"]: p for p in sent}
    assert set(by_event) == {"first-run", "daily"}
    assert set(by_event["first-run"]) == {"event", "version"}     # no id, ever
    assert set(by_event["daily"]) == {"event", "version", "id"}
    assert len(by_event["daily"]["id"]) == 32


def test_first_run_is_sent_once_ever_and_daily_once_a_day(qtbot, tmp_path, monkeypatch):
    today = datetime.date.today().isoformat()
    win, sent, _ = _win(qtbot, tmp_path,
                        Settings(telemetry="on", telemetry_first_run_sent=True,
                                 telemetry_last_ping=today), monkeypatch)
    win._telemetry_ping()
    assert sent == [], "already counted today, and first-run already sent"


def test_a_failed_send_is_not_retried_tomorrow(qtbot, tmp_path, monkeypatch):
    """The date is recorded before the attempt. A week offline must not become a
    burst of pings that maps out when the user was away."""
    monkeypatch.setattr(mw.telemetry_mod, "send", lambda payload, **kw: False)
    win, _, path = _win(qtbot, tmp_path, Settings(telemetry="on"), monkeypatch)
    monkeypatch.setattr(mw.telemetry_mod, "send", lambda payload, **kw: False)
    win._telemetry_ping()
    after = load_settings(path)
    assert after.telemetry_last_ping == datetime.date.today().isoformat()
    assert after.telemetry_first_run_sent is True


def test_the_dialog_pressures_nobody(qtbot):
    """Neither button is the default and neither is styled as primary: Return
    must not answer a question about someone's data on their behalf."""
    from nocturne.ui.telemetry_consent import TelemetryConsentDialog
    dlg = TelemetryConsentDialog('{"event": "daily", "version": "0.34.0", "id": "7f3a…"}')
    qtbot.addWidget(dlg)
    assert not dlg.yes_btn.isDefault() and not dlg.no_btn.isDefault()
    assert dlg.yes_btn.objectName() != "primary"
    # and it must SHOW the payload, not describe it. "we collect anonymous
    # usage data" is what everyone says; nobody shows you the line.
    from PySide6.QtWidgets import QLabel
    labels = [w.text() for w in dlg.findChildren(QLabel)]
    assert any('"event": "daily"' in t for t in labels), labels


def test_the_question_is_not_asked_when_the_caller_opts_out(qtbot, tmp_path, monkeypatch):
    """The `telemetry=False` argument is what keeps the suite (and anything
    embedding MainWindow) free of a modal. It must gate the TIMER, not just the
    send."""
    win, _, _ = _win(qtbot, tmp_path, Settings(), monkeypatch, telemetry=False)
    assert not win._telemetry_timer.isActive()


def test_the_question_is_scheduled_on_a_timer_this_window_owns(qtbot, tmp_path, monkeypatch):
    """Owned by the window, so closing it cancels the question. A static
    QTimer.singleShot outlives the window and asked after it had gone."""
    win, _, _ = _win(qtbot, tmp_path, Settings(), monkeypatch, telemetry=True)
    assert win._telemetry_timer.isActive()
    assert win._telemetry_timer.parent() is win
    win._telemetry_timer.stop()          # this test is about ownership, not the dialog
