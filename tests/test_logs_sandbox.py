"""The suite must never write the developer's own log files.

It did: test_startup_actually_opens_a_session calls the real `main()`, which
calls `configure_logging()` with no path, which attached a handler to the real
~/.nocturne/nocturne.log for the rest of the run. Every later test that logged
— test_preview_runner's "boom A", test_live_previews_async's "never released" —
landed in that file with worktree paths in the tracebacks. It is the file the
problem report attaches, so a user's report would carry the developer's test
noise (found 2026-10-17). session.log is the same kind of file and the same
risk, so it is sandboxed with it.
"""
import logging
import os

import nocturne.core.applog as applog
import nocturne.core.sessionlog as sessionlog

from tests.conftest import REAL_HOME


def _real(*parts):
    return os.path.join(REAL_HOME, ".nocturne", *parts)


def _snap(path):
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return st.st_size, st.st_mtime_ns


def test_the_default_app_log_is_sandboxed():
    assert os.path.normpath(applog.log_path()) != os.path.normpath(_real("nocturne.log"))
    assert not applog.log_path().startswith(_real())


def test_the_default_session_logs_are_sandboxed():
    for p in (sessionlog.session_path(), sessionlog.previous_path()):
        assert not p.startswith(_real()), f"tests resolve to a real log: {p}"


def test_an_explicit_home_still_works(tmp_path):
    """test_applog and the sessionlog tests drive `home=` deliberately."""
    assert applog.log_path(str(tmp_path)) == str(tmp_path / ".nocturne" / "nocturne.log")
    assert sessionlog.session_path(str(tmp_path)) == str(tmp_path / ".nocturne" / "session.log")


def test_what_main_does_leaves_the_real_log_unchanged(monkeypatch):
    """The exact motion that caused it: main()'s bare configure_logging(), then
    an error logged by some later code."""
    monkeypatch.setattr(applog, "_configured", False)
    before = _snap(_real("nocturne.log"))
    target = applog.configure_logging()
    logging.getLogger("nocturne.test").error("sandbox probe — must not reach the real log")
    for h in logging.getLogger("nocturne").handlers:
        h.flush()
    assert _snap(_real("nocturne.log")) == before
    assert target is not None and not target.startswith(_real())


def test_a_test_that_configures_logging_does_not_leave_it_configured():
    """main() sets propagate=False and adds a file handler on the `nocturne`
    logger. Left in place, every later test's caplog stops seeing nocturne.*
    records — so the autouse fixture undoes it after each test."""
    root = logging.getLogger("nocturne")
    assert root.propagate, "a previous test left the nocturne logger detached"
    assert not any(isinstance(h, logging.FileHandler) for h in root.handlers)
    assert applog._configured is False
