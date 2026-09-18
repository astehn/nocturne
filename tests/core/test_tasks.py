import threading
from nocturne.core.tasks import CancelToken, Cancelled, set_ambient, clear_ambient, current

def test_check_raises_after_cancel():
    t = CancelToken()
    assert t.cancelled is False
    t.check()                 # no raise before cancel
    t.cancel()
    assert t.cancelled is True
    import pytest
    with pytest.raises(Cancelled):
        t.check()

def test_ambient_token_roundtrip():
    assert current() is None
    t = CancelToken()
    set_ambient(t)
    try:
        assert current() is t
    finally:
        clear_ambient()
    assert current() is None

def test_ambient_is_thread_local():
    seen = {}
    set_ambient(CancelToken())
    def worker():
        seen["child"] = current()      # a fresh thread has no ambient token
    th = threading.Thread(target=worker); th.start(); th.join()
    clear_ambient()
    assert seen["child"] is None

class _FakeProc:
    def __init__(self): self.pid = 999; self.killed = False; self.terminated = False
    def terminate(self): self.terminated = True

def test_bind_after_cancel_kills_immediately(monkeypatch):
    import nocturne.core.tasks as tasks
    killed = {}
    monkeypatch.setattr(tasks, "kill_process", lambda p: killed.setdefault("p", p))
    t = CancelToken(); t.cancel()
    p = _FakeProc()
    t.bind_process(p)             # already cancelled -> kill on bind
    assert killed["p"] is p


def test_kill_process_never_signals_its_own_process_group(monkeypatch):
    """The one that cost a Linux afternoon.

    A test fake carrying `pid = 4242` reached the real kill_process on
    2026-09-18. The number resolved to a real process group, SIGTERM went to it,
    and Andreas's SSH session died at the same point in the suite every time —
    invisible on macOS, where those pids are absent or root-owned so the call
    fails with EPERM and is swallowed.

    Every process this app kills is spawned with start_new_session=True, so a
    real child LEADS ITS OWN GROUP and can never share ours. A pid that resolves
    to our group is therefore a wrong pid, and acting on it kills Nocturne, its
    shell, and over SSH the login session.
    """
    import os
    from nocturne.core import tasks

    sent = []
    monkeypatch.setattr(tasks.os, "killpg", lambda pgid, sig: sent.append(pgid))

    class _InOurGroup:
        pid = os.getpid()          # ours, so getpgid() returns our own group
        def __init__(self): self.terminated = False
        def terminate(self): self.terminated = True

    proc = _InOurGroup()
    tasks.kill_process(proc)
    assert sent == [], "killpg was called on our own process group"
    assert proc.terminated, "it must still fall back to terminating the process"


def test_kill_process_refuses_init_and_nonsense_pids(monkeypatch):
    """pid 1 is init's group, and a fake often carries 0 or None. None of those
    is a child of ours, and all of them are catastrophic to signal as a group."""
    from nocturne.core import tasks

    sent = []
    monkeypatch.setattr(tasks.os, "killpg", lambda pgid, sig: sent.append(pgid))

    for bad in (0, 1, -1, None, "4242"):
        class _Fake:
            pid = bad
            def __init__(self): self.terminated = False
            def terminate(self): self.terminated = True
        proc = _Fake()
        tasks.kill_process(proc)
        assert sent == [], f"killpg was called for pid {bad!r}"
        assert proc.terminated


def test_a_real_child_in_its_own_session_is_still_group_killed(monkeypatch):
    """The guard must not disarm the feature: a genuine child leads its own
    group, and cancelling a stack has to take its whole tree down."""
    import os
    from nocturne.core import tasks

    sent = []
    monkeypatch.setattr(tasks.os, "killpg", lambda pgid, sig: sent.append(pgid))
    monkeypatch.setattr(tasks.os, "getpgid", lambda pid: 999999)   # not our group

    class _Child:
        pid = 12345
        def terminate(self): raise AssertionError("should not fall back")

    tasks.kill_process(_Child())
    assert sent == [999999], "a real child's group must still be signalled"
