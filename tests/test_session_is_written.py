"""What the session log actually records, and why each part is in it.

Task 4 of docs/superpowers/plans/2026-09-22-diagnostic-log.md. Until this
landed, every `sessionlog.write()` in the app was a silent no-op: nothing
called `start_session()`.

The GUI history panel already shows most of this, and it is not enough — it is
wiped when a project closes and gone when the app exits, which is exactly when
a support ticket gets written. The file is what a ticket can carry.
"""
import os
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from nocturne.core import sessionlog  # noqa: E402
from nocturne.core.image import AstroImage  # noqa: E402

ROOT = Path(__file__).parent.parent


@pytest.fixture
def session(tmp_path, monkeypatch):
    """A live session log in a temp home, and a reader for it."""
    monkeypatch.setattr(sessionlog, "_active", str(tmp_path / "session.log"))
    (tmp_path / "session.log").write_text("")
    return lambda: (tmp_path / "session.log").read_text()


def _img(h=16, w=16):
    return AstroImage(np.full((h, w, 3), 0.2, np.float32), is_linear=False,
                      metadata={"OBJECT": "M 42"})


def _win(qtbot, tmp_path):
    from nocturne.ui.main_window import MainWindow
    win = MainWindow(settings_path=str(tmp_path / "settings.json"))
    qtbot.addWidget(win)
    return win


# --- steps ------------------------------------------------------------------

def test_every_history_line_also_reaches_the_session_log(qtbot, tmp_path, session):
    win = _win(qtbot, tmp_path)
    img = _img()
    win._log_step("deconvolution", "medium", img, img,
                  type("S", (), {"last_engine": "BlurX"})())
    assert "Deconvolution (medium (BlurX))" in session()


def test_the_engine_travels_with_the_step(qtbot, tmp_path, session):
    """The whole point of the 2026-09-22 engine work. A ticket that says
    "Star Reduction" without saying which splitter ran is the ticket that
    starts a conversation."""
    win = _win(qtbot, tmp_path)
    img = _img()
    win._log_step("star_reduction", 0.5, img, img,
                  type("S", (), {"last_engine": "StarNet2"})())
    assert "StarNet2" in session()


# --- tools ------------------------------------------------------------------

def test_a_tool_run_is_recorded_with_its_exit_code_and_elapsed(session):
    """Recorded at run_cli's single convergence point, so a FAILING run is
    recorded too — that is the one a ticket is usually about."""
    from nocturne.tools.base import run_cli
    run_cli(["/bin/echo", "hello"])
    text = session()
    assert "/bin/echo" in text and "exit 0" in text


def test_a_FAILING_tool_run_is_recorded_before_the_error_is_raised(session):
    """`false` exits 1, so run_cli raises ToolError. The log line must already
    be written: a tool that fails is precisely what the reporter is reporting,
    and an exception must not take the record with it."""
    from nocturne.tools.base import ToolError, run_cli
    with pytest.raises(ToolError):
        run_cli(["/usr/bin/false"])
    assert "exit 1" in session()


# --- errors -----------------------------------------------------------------

def test_a_tool_failure_reaches_the_session_log(qtbot, tmp_path, session):
    """A real ToolError, because that is what the caller passes: it carries the
    command, the exit code, the stderr and the elapsed time, and all four are
    the diagnostic. Alvaro's ticket was one line of that stderr."""
    from nocturne.tools.base import ToolError
    win = _win(qtbot, tmp_path)
    win._report_tool_error("Star separation failed", ToolError(
        ["/usr/local/bin/starnet2", "--input", "in.tif"], 1, "",
        "could not import name 'lzw_decode' from 'imagecodecs'", 2.4))
    text = session()
    assert "lzw_decode" in text
    assert "Star separation failed" in text
    assert "starnet2" in text, "the command that failed is half the diagnostic"


# --- the environment, once, at startup --------------------------------------

def test_the_session_opens_with_what_this_install_is(qtbot, tmp_path, session):
    """Written ONCE at startup and cheaply — no subprocesses. A hard crash (the
    Share segfault of 2026-09-21) leaves no chance to collect anything later,
    and this file survives it."""
    from nocturne.settings import Settings
    from nocturne.ui.main_window import write_environment

    write_environment(Settings(graxpert_path="/Applications/GraXpert.app",
                               starnet_path="/x/starnet2"), "1600 x 900")
    text = session()
    from nocturne import __version__
    assert __version__ in text
    assert "GraXpert.app" in text and "/x/starnet2" in text
    assert "1600 x 900" in text


def test_the_startup_block_runs_no_subprocesses(tmp_path, session, monkeypatch):
    """Versions are probed at REPORT time, not here. A launch must not pay for
    four tool invocations, and ASTAP's takes 60 seconds (measured 2026-09-22)."""
    import subprocess
    from nocturne.settings import Settings
    from nocturne.ui.main_window import write_environment

    def forbidden(*a, **k):
        raise AssertionError("startup must not run a subprocess")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    write_environment(Settings(graxpert_path="/x/g"), "800 x 600")
    assert "/x/g" in session()


def test_startup_begins_a_session_before_the_window_exists():
    """Order matters and cannot be asserted at runtime: anything logged while
    no session is open is silently dropped, and MainWindow's construction is
    where autoconfigure and the first tool checks happen."""
    src = (ROOT / "nocturne" / "__main__.py").read_text()
    body = src.split("def main()")[1]
    assert "start_session()" in body, "nothing ever opens a session"
    assert body.index("start_session()") < body.index("MainWindow(")


def test_a_session_that_cannot_be_opened_does_not_stop_the_app(tmp_path, monkeypatch):
    """A log file is a diagnostic, never a reason for the app not to start."""
    monkeypatch.setattr(sessionlog, "_active", None)
    sessionlog.write("dropped, silently, on purpose")
