import threading, time
import pytest
from nocturne.tools.base import run_cli, ToolError
from nocturne.core.tasks import CancelToken, Cancelled

def test_run_cli_success():
    run_cli(["true"])                       # exit 0 -> returns None

def test_run_cli_failure_carries_diagnostics():
    with pytest.raises(ToolError) as ei:
        run_cli(["sh", "-c", "echo boom 1>&2; exit 3"])
    e = ei.value
    assert e.returncode == 3
    assert "boom" in e.stderr
    assert e.command == ["sh", "-c", "echo boom 1>&2; exit 3"]
    assert e.elapsed >= 0.0

def test_run_cli_cancel_kills_child_promptly():
    tok = CancelToken()
    result = {}
    def work():
        try:
            run_cli(["sleep", "30"], cancel=tok)
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
