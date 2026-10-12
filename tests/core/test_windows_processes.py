"""Starting and stopping external tools on Windows (2026-10-12).

Windows has no process groups: a tool is started without a console window of its
own, and Cancel kills its whole tree with taskkill /T. Exercised here on any OS by
switching the module's platform flag; the real taskkill runs in the Windows suite.
"""
import os
import subprocess
import sys

import pytest

from nocturne.core import tasks


def test_posix_children_lead_their_own_session(monkeypatch):
    monkeypatch.setattr(tasks, "_WINDOWS", False)
    assert tasks.child_process_kwargs() == {"start_new_session": True}
    assert tasks.no_window_kwargs() == {}


def test_windows_children_get_no_console_and_their_own_group(monkeypatch):
    monkeypatch.setattr(tasks, "_WINDOWS", True)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x8000000, raising=False)
    assert tasks.child_process_kwargs() == {"creationflags": 0x200 | 0x8000000}
    assert tasks.no_window_kwargs() == {"creationflags": 0x8000000}


def _record_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(tasks, "_WINDOWS", True)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x8000000, raising=False)
    monkeypatch.setattr(tasks.subprocess, "run", lambda argv, **kw: calls.append(argv))
    return calls


def test_windows_cancel_kills_the_whole_tree(monkeypatch):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        calls = _record_runs(monkeypatch)
        tasks.kill_process(proc)
        assert calls == [["taskkill", "/F", "/T", "/PID", str(proc.pid)]]
    finally:
        proc.kill()
        proc.wait()


class _Fake:
    pid = 4242          # the pid that once SIGTERMed a real group (kill_process)

    def terminate(self):
        self.terminated = True


def test_windows_never_taskkills_something_that_is_not_our_popen(monkeypatch):
    calls = _record_runs(monkeypatch)
    fake = _Fake()
    tasks.kill_process(fake)
    assert calls == []
    assert fake.terminated


@pytest.mark.skipif(os.name != "nt", reason="the real taskkill exists only on Windows")
def test_taskkill_really_ends_a_child_and_its_grandchild():
    code = ("import subprocess, sys, time; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            "time.sleep(60)")
    proc = subprocess.Popen([sys.executable, "-c", code], **tasks.child_process_kwargs())
    import time
    time.sleep(1.5)
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId={proc.pid}')"
                          ".ProcessId"], capture_output=True, text=True).stdout
    kids = [int(x) for x in out.split() if x.isdigit()]
    assert kids, "the grandchild did not start"
    tasks.kill_process(proc)
    proc.wait(timeout=10)
    time.sleep(1.0)
    alive = subprocess.run(["tasklist", "/FI", f"PID eq {kids[0]}"],
                           capture_output=True, text=True).stdout
    assert str(kids[0]) not in alive
