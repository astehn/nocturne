"""Streaming a slow tool's progress out to the UI.

GraXpert prints `Progress: N%` about every two seconds; `run_cli` used
`proc.communicate()`, which blocks until the process exits and buffers
everything, so all of it was discarded. A user watched a still screen for
minutes and restarted the app believing it had hung.
"""
import sys

import pytest

from nocturne.core.tasks import CancelToken, clear_ambient, report_progress, set_ambient
from nocturne.tools.base import run_cli


def _emitter(lines, sleep=0.0):
    """A child that prints `lines` one at a time, so streaming can be observed."""
    body = "import sys,time\n"
    for ln in lines:
        body += f"print({ln!r}); sys.stdout.flush()\n"
        if sleep:
            body += f"time.sleep({sleep})\n"
    return [sys.executable, "-c", body]


def test_lines_arrive_while_the_child_is_still_running():
    seen = []
    run_cli(_emitter(["Progress: 3%", "Progress: 50%", "done"]), on_line=seen.append)
    assert seen == ["Progress: 3%", "Progress: 50%", "done"]


def test_without_a_callback_nothing_changes():
    """Every other tool — RC-Astro, ASTAP — goes through this same function and
    must be untouched."""
    run_cli(_emitter(["quiet"]))          # no on_line: must not raise


def test_a_failing_child_still_reports_its_output():
    from nocturne.tools.base import ToolError
    args = [sys.executable, "-c", "import sys; print('context line'); sys.exit(3)"]
    with pytest.raises(ToolError) as e:
        run_cli(args, on_line=lambda _l: None)
    assert e.value.returncode == 3
    assert "context line" in (e.value.stdout + e.value.stderr)


def test_progress_reaches_an_ambient_sink():
    """The sink rides on the CancelToken, which already crosses the worker-thread
    boundary — so no step or tool signature has to grow a callback."""
    got = []
    token = CancelToken()
    token.on_progress = lambda done, total: got.append((done, total))
    set_ambient(token)
    try:
        report_progress(42, 100)
    finally:
        clear_ambient()
    assert got == [(42, 100)]


def test_reporting_with_no_sink_is_harmless():
    clear_ambient()
    report_progress(1, 2)          # must not raise


def test_graxpert_progress_lines_become_progress_reports():
    """Measured from a real run on this machine (GraXpert 3.0.2):

        08:48:42  Progress: 3%
        08:48:44  Progress: 7%
        08:48:46  Progress: 11%

    — a percentage roughly every two seconds, all of it previously discarded.
    """
    from nocturne.tools.graxpert import parse_progress

    assert parse_progress("2026-09-11 08:48:42,738 MainProcess root INFO     Progress: 3%") == 3
    assert parse_progress("Progress: 100%") == 100
    assert parse_progress("MainProcess root INFO     Starting denoising") is None
    assert parse_progress("") is None
    # Not fooled by a percentage that is not progress
    assert parse_progress("Using stored batch size value 4.") is None


def test_a_graxpert_run_reports_progress_to_the_ambient_sink():
    from nocturne.core.tasks import CancelToken, clear_ambient, set_ambient
    from nocturne.tools.graxpert import GraXpert

    got = []
    token = CancelToken()
    token.on_progress = lambda d, t: got.append(d)
    set_ambient(token)

    captured = {}

    def fake_runner(args, **kw):
        captured["on_line"] = kw.get("on_line")
        for pct in (3, 47, 100):
            kw["on_line"](f"2026-09-11 08:48:42,738 MainProcess root INFO     Progress: {pct}%")

    try:
        gx = GraXpert("/nowhere/GraXpert")
        try:
            gx.denoise(_tiny_image(), 0.5, runner=fake_runner)
        except Exception:
            pass          # the fake runner writes no output file; progress is the subject
    finally:
        clear_ambient()
    assert captured.get("on_line") is not None, "GraXpert did not ask to stream"
    assert got == [3, 47, 100]


def _tiny_image():
    import numpy as np
    from nocturne.core.image import AstroImage
    return AstroImage(np.zeros((4, 4, 3), np.float32), is_linear=False, metadata={})
