import sys, threading, time
import pytest
from nocturne.tools.base import run_cli, ToolError
from nocturne.core.tasks import CancelToken, Cancelled

# The interpreter running the suite stands in for a tool: `true`, `sh` and
# `sleep` do not exist on Windows.
_FAIL = [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"]

def test_run_cli_success():
    run_cli([sys.executable, "-c", "pass"])     # exit 0 -> returns None

def test_run_cli_failure_carries_diagnostics():
    with pytest.raises(ToolError) as ei:
        run_cli(_FAIL)
    e = ei.value
    assert e.returncode == 3
    assert "boom" in e.stderr
    assert e.command == _FAIL
    assert e.elapsed >= 0.0

def test_run_cli_cancel_kills_child_promptly():
    tok = CancelToken()
    result = {}
    def work():
        try:
            run_cli([sys.executable, "-c", "import time; time.sleep(30)"], cancel=tok)
        except Cancelled:
            result["cancelled"] = True
        except Exception as e:               # a killed child may surface as ToolError on some shells
            result["other"] = type(e).__name__
    th = threading.Thread(target=work); th.start()
    time.sleep(0.3)
    t0 = time.time()
    tok.cancel()
    th.join(timeout=5)
    assert not th.is_alive()                 # the sleep 30 did NOT run to completion
    assert time.time() - t0 < 3              # died promptly after cancel
